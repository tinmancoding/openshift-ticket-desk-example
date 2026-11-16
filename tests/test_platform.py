"""Read canonical YAML and exercise local clients only; never authenticate or apply."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPENSHIFT = ROOT / 'openshift'


def load(path):
    return yaml.safe_load((OPENSHIFT / path).read_text())


def objects(path):
    return list(yaml.safe_load_all((OPENSHIFT / path).read_text()))


def named(items, name):
    return next(item for item in items if item['metadata']['name'] == name)


class ManifestTests(unittest.TestCase):
    def test_every_file_is_parseable_and_has_an_explicit_purpose(self):
        files = list(OPENSHIFT.rglob('*.yaml'))
        self.assertEqual(len(files), 17)
        for path in files:
            text = path.read_text()
            self.assertTrue(text.startswith('# '), path)
            self.assertFalse(any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken))
                                 for token in yaml.scan(text)), path)
            for item in yaml.safe_load_all(text):
                if path.parent.name == 'traffic':
                    self.assertEqual(set(item), {'spec'})
                    continue
                self.assertIn('apiVersion', item)
                self.assertIn('kind', item)
                self.assertTrue(item['metadata']['name'].startswith('desk-'))
                self.assertNotIn('namespace', item['metadata'])

    def test_templates_declare_their_parameters(self):
        for path in (OPENSHIFT / 'templates').glob('*.yaml'):
            item = yaml.safe_load(path.read_text())
            self.assertEqual(item['kind'], 'Template')
            parameters = {entry['name'] for entry in item['parameters']}
            # Bash ${#REVISION} is a length expression, not a Template parameter.
            used = set(re.findall(r'\$\{([A-Z_][A-Z_0-9]*)\}', json.dumps(item['objects'])))
            self.assertEqual(used, parameters, path)
            self.assertTrue(all(entry['required'] for entry in item['parameters']))

    def test_image_templates_require_explicit_successful_run_inputs(self):
        for path, parameter in [('api-slot.yaml', 'API_IMAGE'), ('schema-job.yaml', 'API_IMAGE'),
                                ('renderer.yaml', 'RENDERER_IMAGE')]:
            params = load('templates/' + path)['parameters']
            image = next(item for item in params if item['name'] == parameter)
            self.assertTrue(image['required'])
            self.assertNotIn('value', image)
        self.assertIn('@sha256:', load('templates/tasks.yaml')['parameters'][1]['value'])

    def test_only_example_secret_is_committed(self):
        secret = load('database-secret.example.yaml')
        self.assertEqual(secret['kind'], 'Secret')
        self.assertEqual(secret['stringData'], {'password': 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD'})
        self.assertIn('.local/', (ROOT / '.gitignore').read_text())
        for path in (OPENSHIFT / 'templates').glob('*.yaml'):
            self.assertFalse(any(item['kind'] == 'Secret' for item in yaml.safe_load(path.read_text())['objects']))

    def test_git_source_builds_and_tests_share_repository_parameter(self):
        builds = load('templates/builds.yaml')
        tasks = load('templates/tasks.yaml')
        self.assertEqual(builds['parameters'][0], tasks['parameters'][0])
        recipes = [item for item in builds['objects'] if item['kind'] == 'BuildConfig']
        self.assertEqual(len(recipes), 2)
        for recipe in recipes:
            spec = recipe['spec']
            self.assertEqual(spec['source']['type'], 'Git')
            self.assertEqual(spec['source']['git']['uri'], 'https://github.com/${GITHUB_REPOSITORY}.git')
            self.assertIn(spec['source']['contextDir'], ('apps/api', 'apps/renderer'))
            self.assertEqual(spec['strategy']['type'], 'Docker')
            self.assertEqual(spec['triggers'], [])
        source = named(tasks['objects'], 'desk-source-test')
        archive = next(env['value'] for env in source['spec']['steps'][0]['env'] if env['name'] == 'ARCHIVE_ROOT')
        self.assertEqual(archive, 'https://codeload.github.com/${GITHUB_REPOSITORY}/tar.gz')

    def test_pipeline_has_three_required_gates_and_no_deployment_task(self):
        pipeline = load('ci/pipeline.yaml')
        tasks = pipeline['spec']['tasks']
        self.assertEqual([task['name'] for task in tasks], ['source-tests', 'build', 'image-tests'])
        self.assertEqual(tasks[1]['runAfter'], ['source-tests'])
        self.assertEqual(tasks[2]['runAfter'], ['build'])
        for task in tasks:
            self.assertNotIn('when', task)
        image = named(load('templates/tasks.yaml')['objects'], 'desk-image-test')
        self.assertEqual(image['spec']['steps'][0]['image'], '$(params.image)')
        for name in ('desk-build', 'desk-image-test'):
            step = named(load('templates/tasks.yaml')['objects'], name)['spec']['steps'][0]
            self.assertEqual(next(env['value'] for env in step['env'] if env['name'] == 'HOME'), '/tmp')

    def test_runs_select_explicit_published_commits_and_split_identities(self):
        revisions = {}
        names = []
        for path in sorted((OPENSHIFT / 'runs').glob('*.yaml')):
            run = yaml.safe_load(path.read_text())
            names.append(run['metadata']['name'])
            self.assertNotIn('generateName', run['metadata'])
            self.assertEqual(run['spec']['taskRunTemplate']['serviceAccountName'], 'desk-builder')
            self.assertEqual([entry['serviceAccountName'] for entry in run['spec']['taskRunSpecs']],
                             ['desk-test', 'desk-test'])
            params = {entry['name']: entry['value'] for entry in run['spec']['params']}
            self.assertRegex(params['revision'], r'^[0-9a-f]{40}$')
            self.assertIn(params['component'], ('api', 'renderer'))
            revisions[path.stem] = params['revision']
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(revisions['api-blue-ci'], revisions['renderer-ci'])
        self.assertNotEqual(revisions['api-green-ci'], revisions['api-blue-ci'])
        self.assertNotEqual(revisions['api-green-ci'], revisions['api-rejected-ci'])

    def test_ci_identity_cannot_release_read_secrets_or_grant_permissions(self):
        items = objects('00-identities.yaml')
        role = next(item for item in items if item['kind'] == 'Role')
        allowed = {'buildconfigs', 'buildconfigs/instantiate', 'builds', 'builds/log', 'imagestreams'}
        for rule in role['rules']:
            self.assertTrue(set(rule['resources']) <= allowed)
            self.assertFalse(set(rule['verbs']) & {'patch', 'update', 'delete', '*', 'bind', 'escalate'})
        for item in items:
            if item['kind'] == 'ServiceAccount' and item['metadata']['name'] != 'desk-builder':
                self.assertFalse(item['automountServiceAccountToken'])

    def test_embedded_task_scripts_match_application_ci_sources(self):
        tasks = load('templates/tasks.yaml')['objects']
        for name, source in [('desk-source-test', 'source-test.py'), ('desk-build', 'build.sh'),
                             ('desk-image-test', 'image-test.py')]:
            embedded = named(tasks, name)['spec']['steps'][0]['script']
            self.assertEqual(embedded, (ROOT / 'deploy' / source).read_text())
        self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / 'deploy/build.sh')], capture_output=True).returncode, 0)

    def test_build_uses_exact_build_commit_and_digest_not_latest(self):
        script = named(load('templates/tasks.yaml')['objects'], 'desk-build')['spec']['steps'][0]['script']
        self.assertIn('--commit="$REVISION" -o name', script)
        self.assertIn('.spec.revision.git.commit', script)
        self.assertIn('.status.output.to.imageDigest', script)
        self.assertIn('Failed|Error|Cancelled', script)
        self.assertNotIn('get istag', script)
        self.assertNotIn('--from-dir', script)

    def test_application_templates_share_database_and_disable_tokens(self):
        slot = load('templates/api-slot.yaml')['objects'][0]
        schema = load('templates/schema-job.yaml')['objects'][0]
        self.assertEqual(slot['metadata']['name'], 'desk-api-${SLOT}')
        self.assertEqual(slot['spec']['selector']['matchLabels']['slot'], '${SLOT}')
        slot_pod = slot['spec']['template']['spec']
        job_pod = schema['spec']['template']['spec']
        for pod in (slot_pod, job_pod, load('templates/renderer.yaml')['objects'][0]['spec']['template']['spec']):
            self.assertFalse(pod['automountServiceAccountToken'])
            context = pod['containers'][0]['securityContext']
            self.assertTrue(context['runAsNonRoot'])
            self.assertFalse(context['allowPrivilegeEscalation'])
        database_vars = [env for env in slot_pod['containers'][0]['env'] if env['name'].startswith('DB_')]
        self.assertEqual(database_vars, job_pod['containers'][0]['env'])
        self.assertEqual(next(env['value'] for env in database_vars if env['name'] == 'DB_HOST'), 'desk-db')
        self.assertNotIn('volumes', slot_pod)

    def test_network_and_patches_make_routing_change_visible(self):
        items = objects('03-network.yaml')
        self.assertEqual(named(items, 'desk-api')['spec']['selector'], {'app': 'desk-api', 'slot': 'blue'})
        self.assertEqual(named(items, 'desk-preview')['spec']['selector'], {'app': 'desk-api', 'slot': 'green'})
        for slot in ('blue', 'green'):
            self.assertEqual(load('traffic/to-' + slot + '.patch.yaml'),
                             {'spec': {'selector': {'app': 'desk-api', 'slot': slot}}})

    def test_empty_or_failing_tests_never_make_a_green_source_gate(self):
        script = (ROOT / 'deploy/source-test.py').read_text()
        self.assertIn("filter='data'", script)
        tree = ast.parse(script)
        runner = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'test_runner' for target in node.targets))
        with tempfile.TemporaryDirectory() as directory:
            tests = Path(directory) / 'tests'
            tests.mkdir()
            self.assertNotEqual(subprocess.run([sys.executable, '-c', runner], cwd=directory, capture_output=True).returncode, 0)
            source = tests / 'test_gate.py'
            source.write_text('import unittest\nclass Gate(unittest.TestCase):\n def test_gate(self): self.fail("real failure")\n')
            self.assertNotEqual(subprocess.run([sys.executable, '-B', '-c', runner], cwd=directory, capture_output=True).returncode, 0)
            source.write_text('import unittest\nclass Gate(unittest.TestCase):\n def test_gate(self): self.assertEqual(1 + 1, 2)\n')
            self.assertEqual(subprocess.run([sys.executable, '-B', '-c', runner], cwd=directory, capture_output=True).returncode, 0)

    @unittest.skipUnless(shutil.which('oc'), 'Optional native client check; YAML tests still run without oc')
    def test_native_template_processing_is_local_and_preserves_tekton_tokens(self):
        env = dict(os.environ, KUBECONFIG='/nonexistent-ticket-desk-offline-test')
        result = subprocess.run(['oc', 'process', '--local=true', '-f', str(OPENSHIFT / 'templates/tasks.yaml'),
                                 '-p', 'GITHUB_REPOSITORY=example/fork', '-o', 'json'],
                                env=env, capture_output=True, text=True, check=True)
        tasks = json.loads(result.stdout)['items']
        build_script = named(tasks, 'desk-build')['spec']['steps'][0]['script']
        self.assertIn('${#REVISION}', build_script)
        self.assertIn('$(results.image.path)', build_script)
        source_env = named(tasks, 'desk-source-test')['spec']['steps'][0]['env']
        self.assertEqual(next(env['value'] for env in source_env if env['name'] == 'ARCHIVE_ROOT'),
                         'https://codeload.github.com/example/fork/tar.gz')
        missing = subprocess.run(['oc', 'process', '--local=true', '-f', str(OPENSHIFT / 'templates/api-slot.yaml')],
                                 env=env, capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)


class BeginnerDocumentationTests(unittest.TestCase):
    def test_main_walkthrough_uses_native_commands_and_prepared_snapshots(self):
        text = (ROOT / 'docs/walkthrough.md').read_text()
        commands = re.findall(r'```bash\n(.*?)```', text, re.S)
        joined = '\n'.join(commands)
        self.assertNotIn('scripts/desk.py', joined)
        self.assertNotIn('scripts/resources.py', joined)
        self.assertNotIn('git push', joined)
        self.assertNotIn('make ', joined)
        self.assertNotRegex(joined, r'(^|\n)desk\s')
        self.assertFalse((ROOT / 'scripts/desk.py').exists())
        self.assertFalse((ROOT / 'scripts/resources.py').exists())
        for path in re.findall(r'openshift/[A-Za-z0-9_/.-]+\.yaml', joined):
            self.assertTrue((ROOT / path).is_file(), path)
        for path in ['renderer-ci.yaml', 'api-blue-ci.yaml', 'api-green-ci.yaml']:
            self.assertIn('oc create -f openshift/runs/' + path, joined)
        self.assertIn('--patch-file openshift/traffic/to-green.patch.yaml', joined)
        self.assertIn('--patch-file openshift/traffic/to-blue.patch.yaml', joined)
        self.assertIn('**Good looks like:**', text)
        self.assertIn('The four file operations', text)
        self.assertLess(text.index('Restarting with retained data'),
                        text.index('cp openshift/database-secret.example.yaml'))
        self.assertIn('starting with a letter', text)
        for block in commands:
            result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_documentation_links_and_cleanup_have_no_broad_deletes(self):
        paths = [ROOT / 'README.md', ROOT / 'PLAN.md', *sorted((ROOT / 'docs').glob('*.md'))]
        for path in paths:
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text()):
                if '://' not in target and not target.startswith('#'):
                    self.assertTrue((path.parent / target.split('#')[0]).is_file(), f'{path}: {target}')
        cleanup = (ROOT / 'docs/cleanup.md').read_text()
        commands = '\n'.join(re.findall(r'```bash\n(.*?)```', cleanup, re.S))
        self.assertNotIn('--all', commands)
        self.assertNotRegex(commands, r'oc delete (?:project|namespace)')
        self.assertIn('PVC and database Secret remain', cleanup)
        self.assertIn('do not verify ownership for you', cleanup)
        self.assertNotIn('UID-precondition guard', cleanup)
        self.assertIn('oc delete -f .local/my-release-ci.yaml', commands)
        self.assertIn('oc delete -f .local/schema-job-retry.yaml', commands)
        self.assertIn('do not remove `.local/database-secret.yaml`', cleanup)
        release = (ROOT / 'docs/your-own-release.md').read_text()
        self.assertIn('Do not clone it into a second directory', release)
        self.assertIn('git push -u my-fork feature/my-urgent-tickets', release)
        for block in re.findall(r'```bash\n(.*?)```', release, re.S):
            self.assertFalse('make setup' in block and 'git push' in block)


if __name__ == '__main__':
    unittest.main()
