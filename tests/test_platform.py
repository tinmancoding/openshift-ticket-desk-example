"""Offline contract and safety tests. No authentication or cluster mutation."""
import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import desk
import resources as r

IMAGE = 'quay.io/example/cli@sha256:' + 'a' * 64
REPO = 'https://github.com/tinmancoding/openshift-ticket-desk-example.git'


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.items = r.foundation('test-owner', REPO, IMAGE)

    def test_foundation_json_and_ownership(self):
        self.assertEqual(json.loads(json.dumps(self.items)), self.items)
        names = [(item['apiVersion'], item['kind'], item['metadata']['name']) for item in self.items]
        self.assertEqual(len(set(names)), len(names))
        for item in self.items:
            self.assertEqual(item['metadata']['labels'][r.OWNER_LABEL], 'test-owner')
            self.assertTrue(item['metadata']['name'].startswith('desk-'))

    def test_git_source_builds_have_no_automatic_triggers(self):
        builds = [item for item in self.items if item['kind'] == 'BuildConfig']
        self.assertEqual(len(builds), 2)
        for item in builds:
            spec = item['spec']
            self.assertEqual(spec['source']['type'], 'Git')
            self.assertEqual(spec['source']['git']['uri'], REPO)
            self.assertIn(spec['source']['contextDir'], ('apps/api', 'apps/renderer'))
            self.assertEqual(spec['strategy']['type'], 'Docker')
            self.assertEqual(spec['triggers'], [])

    def test_source_build_image_order_and_identity(self):
        pipeline = next(item for item in self.items if item['kind'] == 'Pipeline')
        tasks = pipeline['spec']['tasks']
        self.assertEqual([task['name'] for task in tasks], ['source-tests', 'build', 'image-tests'])
        self.assertEqual(tasks[1]['runAfter'], ['source-tests'])
        self.assertEqual(tasks[2]['runAfter'], ['build'])
        run = r.pipeline_run('owner', 'api', 'a' * 40)
        self.assertNotIn('name', run['metadata'])
        self.assertEqual(run['spec']['taskRunTemplate']['serviceAccountName'], 'desk-builder')
        self.assertEqual([spec['serviceAccountName'] for spec in run['spec']['taskRunSpecs']], ['desk-test', 'desk-test'])
        for item in self.items:
            if item['kind'] == 'ServiceAccount' and item['metadata']['name'] != 'desk-builder':
                self.assertFalse(item['automountServiceAccountToken'])

    def test_builder_has_no_release_or_secret_permissions(self):
        role = next(item for item in self.items if item['kind'] == 'Role')
        self.assertFalse(any(rule['apiGroups'] == ['*'] for rule in role['rules']))
        allowed = {'buildconfigs', 'buildconfigs/instantiate', 'builds', 'builds/log', 'imagestreams'}
        for rule in role['rules']:
            self.assertTrue(set(rule['resources']) <= allowed)
            self.assertFalse(set(rule['verbs']) & {'patch', 'update', 'delete', '*', 'bind', 'escalate'})

    def test_slots_share_database_but_not_selector(self):
        blue = r.api_slot('owner', 'blue', IMAGE, 'http://renderer.example')
        green = r.api_slot('owner', 'green', IMAGE, 'http://renderer.example')
        for item in (blue, green):
            pod = item['spec']['template']['spec']
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertEqual(pod['containers'][0]['env'], blue['spec']['template']['spec']['containers'][0]['env'])
        self.assertNotEqual(blue['spec']['selector'], green['spec']['selector'])
        services = r.api_network('owner')
        self.assertEqual(services[0]['spec']['selector']['slot'], 'blue')
        self.assertEqual(services[1]['spec']['selector']['slot'], 'green')
        self.assertEqual(r.renderer('owner', IMAGE)['spec']['template']['spec']['containers'][0]['image'], IMAGE)

    def test_repository_rejects_credentials_and_other_hosts(self):
        for repo in ('git@github.com:a/b.git', 'https://token@github.com/a/b', 'https://evil.test/a/b',
                     'https://github.com/a/b?token=x'):
            with self.assertRaises(ValueError):
                r.foundation('owner', repo, IMAGE)

    def test_build_records_exact_build_source_and_digest(self):
        script = (ROOT / 'deploy/build.sh').read_text()
        self.assertIn('--commit="$REVISION" -o name', script)
        self.assertIn('.spec.revision.git.commit', script)
        self.assertIn('.status.output.to.imageDigest', script)
        self.assertNotIn('get istag', script)
        self.assertNotIn('--from-dir', script)
        self.assertIn('Failed|Error|Cancelled', script)
        self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / 'deploy/build.sh')], capture_output=True).returncode, 0)

    def test_source_gate_uses_commit_and_safe_archive(self):
        script = (ROOT / 'deploy/source-test.py').read_text()
        self.assertIn("filter='data'", script)
        self.assertIn('member.isfile() or member.isdir()', script)
        self.assertIn("unittest.defaultTestLoader.discover('tests')", script)
        self.assertIn('suite.countTestCases() == 0', script)
        self.assertIn('check=True', script)
        compile(script, 'source-test.py', 'exec')
        compile((ROOT / 'deploy/image-test.py').read_text(), 'image-test.py', 'exec')


class ToolSafetyTests(unittest.TestCase):
    def test_digest_required(self):
        self.assertEqual(desk.immutable_image(IMAGE), IMAGE)
        for bad in ('repo:latest', 'repo@sha256:abc', 'repo@sha256:' + 'z' * 64):
            with self.assertRaises(ValueError):
                desk.immutable_image(bad)

    def test_render_never_contacts_cluster(self):
        with patch.object(sys, 'argv', ['desk.py', 'render', '--cli-image', IMAGE]), \
             patch.object(desk.subprocess, 'run', side_effect=AssertionError('No cluster calls')), \
             patch('builtins.print') as printed:
            desk.main()
        output = json.loads(printed.call_args.args[0])
        self.assertEqual(output['kind'], 'List')
        self.assertFalse(any(item['kind'] == 'Secret' for item in output['items']))

    def test_confirmation_required_before_subprocess(self):
        args = desk.parser().parse_args(['--namespace', 'learner09', 'status'])
        with patch.object(desk.subprocess, 'run', side_effect=AssertionError('No calls')):
            with self.assertRaises(ValueError):
                desk.Cluster(args)

    def test_owner_requires_receipt_and_uid(self):
        cluster = desk.Cluster.__new__(desk.Cluster)
        cluster.state = {'owner': 'owned', 'objects': [{'kind': 'services', 'name': 'desk-api', 'uid': 'original'}]}
        item = r.service('desk-api', 'owned', {'slot': 'blue'})
        item['metadata']['uid'] = 'original'
        self.assertTrue(cluster.owned(item))
        item['metadata']['uid'] = 'replacement'
        self.assertFalse(cluster.owned(item))
        item['metadata']['uid'] = 'original'
        item['metadata']['labels'][r.OWNER_LABEL] = 'other'
        self.assertFalse(cluster.owned(item))

    def test_cleanup_uses_atomic_uid_precondition_and_no_broad_deletes(self):
        script = (ROOT / 'scripts/desk.py').read_text()
        self.assertIn("'preconditions': {'uid': entry['uid']}", script)
        self.assertIn("'path': '/metadata/resourceVersion'", script)
        self.assertNotIn("'--all'", script)
        item = r.renderer('owned', IMAGE)
        self.assertEqual(desk.api_path(item, 'learner09'),
                         '/apis/serving.knative.dev/v1/namespaces/learner09/services/desk-renderer')

    def test_promotion_rejects_old_available_pods_during_update(self):
        deployment = r.api_slot('owner', 'green', IMAGE, 'http://renderer.example')
        deployment['metadata']['generation'] = 2
        deployment['status'] = dict(observedGeneration=2, updatedReplicas=1, readyReplicas=1, availableReplicas=1)
        self.assertTrue(desk.deployment_ready(deployment))
        for field, value in [('observedGeneration', 1), ('updatedReplicas', 0), ('readyReplicas', 0),
                             ('unavailableReplicas', 1)]:
            bad = copy.deepcopy(deployment)
            bad['status'][field] = value
            self.assertFalse(desk.deployment_ready(bad), field)

    def test_setup_does_not_expose_or_rotate_existing_password(self):
        cluster = desk.Cluster.__new__(desk.Cluster)
        cluster.namespace = 'learner09'
        cluster.state = {'owner': 'owner', 'objects': [{'kind': 'secrets', 'name': 'desk-db', 'uid': 'original'}]}
        secret = r.obj('v1', 'Secret', 'desk-db', 'owner', type='Opaque', stringData={'password': 'test-only'})
        existing = copy.deepcopy(secret)
        existing.pop('stringData')
        existing['data'] = {'password': desk.base64.b64encode(b'test-only').decode()}
        existing['metadata']['uid'] = 'original'
        with patch.object(cluster, 'read', return_value=existing), patch.object(cluster, 'oc') as oc:
            self.assertEqual(cluster.apply(secret), existing)
            oc.assert_not_called()
            secret['stringData']['password'] = 'unexpected-rotation'
            with self.assertRaises(ValueError):
                cluster.apply(secret)
            oc.assert_not_called()

    def test_empty_or_failing_source_suite_is_not_green(self):
        tree = ast.parse((ROOT / 'deploy/source-test.py').read_text())
        runner = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'test_runner' for target in node.targets))
        with tempfile.TemporaryDirectory() as directory:
            tests = Path(directory) / 'tests'
            tests.mkdir()
            empty = subprocess.run([sys.executable, '-c', runner], cwd=directory, capture_output=True)
            self.assertNotEqual(empty.returncode, 0)
            source = tests / 'test_gate.py'
            source.write_text('import unittest\nclass Gate(unittest.TestCase):\n def test_gate(self): self.fail("real failure")\n')
            failed = subprocess.run([sys.executable, '-c', runner], cwd=directory, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            source.write_text('import unittest\nclass Gate(unittest.TestCase):\n def test_gate(self): self.assertEqual(1 + 1, 2)\n')
            passed = subprocess.run([sys.executable, '-B', '-c', runner], cwd=directory, capture_output=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_merge_keeps_service_cluster_ip(self):
        self.assertEqual(desk.merge_defaults({'clusterIP': '10.1.1.1', 'selector': {'slot': 'blue'}},
                                             {'selector': {'slot': 'green'}}),
                         {'clusterIP': '10.1.1.1', 'selector': {'slot': 'green'}})


if __name__ == '__main__':
    unittest.main()
