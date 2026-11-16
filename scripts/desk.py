#!/usr/bin/env python3
"""Explicit namespace-scoped operations. No cluster mutation on import or render."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

import resources as r

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = 'https://github.com/tinmancoding/openshift-ticket-desk-example.git'
PLURALS = {'ServiceAccount': 'serviceaccounts', 'PersistentVolumeClaim': 'persistentvolumeclaims',
           'Deployment': 'deployments', 'Service': 'services', 'ImageStream': 'imagestreams',
           'BuildConfig': 'buildconfigs', 'Role': 'roles', 'RoleBinding': 'rolebindings',
           'Task': 'tasks', 'Pipeline': 'pipelines', 'PipelineRun': 'pipelineruns',
           'Secret': 'secrets', 'Route': 'routes', 'Job': 'jobs'}


def resource_type(item):
    group = item['apiVersion'].split('/')[0] if '/' in item['apiVersion'] else ''
    return PLURALS[item['kind']] + ('.' + group if group else '')


def api_path(item, namespace):
    version = item['apiVersion']
    base = '/apis/' + version if '/' in version else '/api/' + version
    return f"{base}/namespaces/{namespace}/{PLURALS[item['kind']]}/{item['metadata']['name']}"


def immutable_image(value):
    if not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', value):
        raise ValueError('A complete image repository@sha256:digest is required')
    return value


def deployment_ready(item):
    desired = item['spec'].get('replicas', 1)
    status = item.get('status', {})
    return (desired >= 1 and status.get('observedGeneration', 0) >= item['metadata']['generation']
            and all(status.get(field, 0) == desired
                    for field in ('updatedReplicas', 'readyReplicas', 'availableReplicas'))
            and status.get('unavailableReplicas', 0) == 0)


def merge_defaults(current, desired):
    """Retain API-assigned fields (e.g. Service clusterIP) while replacing desired lists."""
    if isinstance(current, dict) and isinstance(desired, dict):
        return {**current, **{key: merge_defaults(current.get(key), value) for key, value in desired.items()}}
    return desired


class Cluster:
    def __init__(self, args):
        self.namespace = args.namespace
        if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]*[a-z0-9])?', self.namespace):
            raise ValueError('An explicit valid namespace is required')
        if args.confirm != self.namespace or not args.identity:
            raise ValueError('Mutations require --confirm NAMESPACE and --identity EXPECTED_USER')
        self.directory = ROOT / '.state'
        if self.directory.is_symlink():
            raise ValueError('Refusing symlink state directory')
        self.directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / (self.namespace + '.json')
        if self.path.is_symlink():
            raise ValueError('Refusing symlink state file')
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'namespace': self.namespace, 'owner': secrets.token_hex(8), 'objects': [], 'releases': []}
        if self.state['namespace'] != self.namespace:
            raise ValueError('State namespace mismatch')
        actual = self.oc('whoami').strip()
        if actual != args.identity:
            raise ValueError(f'Wrong identity: expected {args.identity}, got {actual}')
        # Never change the caller's current project/context.
        self.oc('get', 'namespace', self.namespace, '-o', 'name')
        self.save()

    def oc(self, *args, payload=None, check=True, timeout=120):
        result = subprocess.run(['oc', '-n', self.namespace, *args],
                                input=None if payload is None else json.dumps(payload),
                                capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            # Never print submitted manifests (a Secret may be among them).
            raise RuntimeError(f"oc {' '.join(args[:3])} failed: {result.stderr.strip()}")
        return result.stdout if check else result

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, indent=2)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @property
    def owner(self):
        return self.state['owner']

    def read(self, kind, name):
        raw = self.oc('get', kind, name, '--ignore-not-found', '-o', 'json')
        return json.loads(raw) if raw.strip() else None

    def receipt(self, item):
        kind = resource_type(item)
        meta = item['metadata']
        entry = dict(kind=kind, name=meta['name'], uid=meta['uid'], apiVersion=item['apiVersion'],
                     objectKind=item['kind'])
        self.state['objects'] = [old for old in self.state['objects']
                                 if (old['kind'], old['name']) != (kind, meta['name'])] + [entry]
        self.save()

    def owned(self, item):
        meta = item['metadata']
        return meta.get('labels', {}).get(r.OWNER_LABEL) == self.owner and any(
            entry['kind'] == resource_type(item) and entry['name'] == meta['name']
            and entry['uid'] == meta['uid'] for entry in self.state['objects'])

    def apply(self, item):
        item['metadata']['namespace'] = self.namespace
        kind = resource_type(item)
        name = item['metadata'].get('name')
        existing = self.read(kind, name) if name else None
        if existing:
            if not self.owned(existing):
                raise ValueError(f'Refusing unowned or replaced {kind}/{name}')
            if item['kind'] == 'Secret':
                desired = {key: base64.b64encode(value.encode()).decode()
                           for key, value in item.get('stringData', {}).items()}
                if existing.get('data') != desired:
                    raise ValueError('Database Secret differs from private state; investigate, do not rotate blindly')
                # Never place a password in process arguments or rotate it on setup reruns.
                return existing
            # Atomic UID/resourceVersion tests prevent changing a replaced resource.
            patches = [{'op': 'test', 'path': '/metadata/uid', 'value': existing['metadata']['uid']},
                       {'op': 'test', 'path': '/metadata/resourceVersion',
                        'value': existing['metadata']['resourceVersion']}]
            for key, value in item.items():
                if key not in ('apiVersion', 'kind', 'metadata'):
                    patches.append({'op': 'add', 'path': '/' + key,
                                    'value': merge_defaults(existing.get(key), value)})
            output = self.oc('patch', kind, name, '--type=json', '-p', json.dumps(patches), '-o', 'json')
        else:
            output = self.oc('create', '-f', '-', '-o', 'json', payload=item)
        created = json.loads(output)
        self.receipt(created)
        print(f"Owned {resource_type(created)}/{created['metadata']['name']}", file=sys.stderr)
        return created

    def poll(self, kind, name, condition, timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.read(kind, name)
            if item and condition(item):
                return item
            time.sleep(3)
        raise TimeoutError(f'Inspect {kind}/{name}; bounded wait expired')

    def require_owned(self, kind, name):
        item = self.read(kind, name)
        if not item or not self.owned(item):
            raise ValueError(f'Missing/unowned/replaced {kind}/{name}')
        return item

    def release(self, component, image):
        immutable_image(image)
        if not any(entry['component'] == component and entry['image'] == image
                   for entry in self.state['releases']):
            raise ValueError('Image is not recorded from a successful whole PipelineRun in this state')
        return image


def run_pipeline(cluster, component, revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use the full pushed commit SHA')
    # Protect the reviewed definitions from another example's fixed names.
    for kind, name in [('pipelines.tekton.dev', 'desk-ci'), ('serviceaccounts', 'desk-builder'),
                       ('serviceaccounts', 'desk-test'), ('buildconfigs.build.openshift.io', 'desk-' + component)]:
        cluster.require_owned(kind, name)
    run = cluster.apply(r.pipeline_run(cluster.owner, component, revision))
    name = run['metadata']['name']
    def terminal(item):
        return any(c['type'] == 'Succeeded' and c['status'] in ('True', 'False')
                   for c in item.get('status', {}).get('conditions', []))
    print(f'Waiting for {name}; follow with: tkn pipelinerun logs {name} -f -n {cluster.namespace}', file=sys.stderr)
    final = cluster.poll('pipelineruns.tekton.dev', name, terminal, timeout=2160)
    evidence = cluster.directory / name
    evidence.mkdir(mode=0o700)
    (evidence / 'run.json').write_text(json.dumps(final, indent=2))
    if shutil.which('tkn'):
        logs = subprocess.run(['tkn', '-n', cluster.namespace, 'pipelinerun', 'logs', name],
                              capture_output=True, text=True, timeout=120)
    else:
        # Keep evidence even on a workstation with oc but without tkn.
        logs = cluster.oc('logs', '-l', 'tekton.dev/pipelineRun=' + name,
                          '--all-containers=true', '--prefix=true', '--tail=-1', check=False)
    (evidence / 'logs.txt').write_text(logs.stdout + logs.stderr)
    if not any(c['type'] == 'Succeeded' and c['status'] == 'True'
               for c in final['status']['conditions']):
        raise RuntimeError(f'{name} failed; evidence archived. Do not deploy. Inspect any active Build before cleanup.')
    results = {entry['name']: entry['value'] for entry in final['status'].get('results', [])}
    image = immutable_image(results['image'])
    build = cluster.oc('get', results['build'], '-o', 'json')
    build = json.loads(build)
    if build['status']['phase'] != 'Complete' or build['spec']['revision']['git']['commit'] != revision:
        raise ValueError('Build evidence does not match the requested source')
    (evidence / 'build.json').write_text(json.dumps(build, indent=2))
    cluster.state['releases'].append(dict(component=component, revision=revision, image=image,
                                         run=name, build=build['metadata']['name']))
    cluster.save()
    print(image)


def cleanup(cluster, delete_data):
    # Fail closed while runs or independent Builds are still active.
    for kind in ('pipelineruns.tekton.dev', 'builds.build.openshift.io'):
        objects = json.loads(cluster.oc('get', kind, '-o', 'json'))['items']
        for item in objects:
            if kind.startswith('pipelineruns'):
                owned = item['metadata'].get('labels', {}).get(r.OWNER_LABEL) == cluster.owner
                terminal = any(c['type'] == 'Succeeded' and c['status'] in ('True', 'False')
                               for c in item.get('status', {}).get('conditions', []))
            else:
                owned = any(ref.get('uid') in {e['uid'] for e in cluster.state['objects']}
                            for ref in item['metadata'].get('ownerReferences', []))
                terminal = item.get('status', {}).get('phase') in ('Complete', 'Failed', 'Error', 'Cancelled')
            if owned and not terminal:
                raise ValueError(f"Active execution {item['metadata']['name']}; inspect/cancel explicitly first")
    # Runs first (finalizers), then workload parents, definitions, identities, storage last.
    order = {'PipelineRun': 0, 'Job': 1, 'Service': 2, 'Deployment': 3, 'Route': 4,
             'Pipeline': 5, 'Task': 6, 'BuildConfig': 7, 'ImageStream': 8,
             'RoleBinding': 9, 'Role': 10, 'ServiceAccount': 11, 'Secret': 12, 'PersistentVolumeClaim': 13}
    for entry in sorted(cluster.state['objects'], key=lambda e: order[e['objectKind']]):
        if entry['objectKind'] in ('Secret', 'PersistentVolumeClaim') and not delete_data:
            print('Retained data resource:', entry['kind'], entry['name'], file=sys.stderr)
            continue
        item = cluster.read(entry['kind'], entry['name'])
        if item is None:
            continue
        if not cluster.owned(item):
            raise ValueError(f"Refusing changed cleanup target {entry['kind']}/{entry['name']}")
        options = {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                   'preconditions': {'uid': entry['uid']}, 'propagationPolicy': 'Foreground'}
        cluster.oc('delete', '--raw', api_path(item, cluster.namespace), '-f', '-', payload=options)
        deadline = time.monotonic() + 420
        while cluster.read(entry['kind'], entry['name']) is not None:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Cleanup finalizers still active: {entry['name']}")
            time.sleep(2)
        print('Deleted', entry['kind'], entry['name'], file=sys.stderr)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--namespace', default=os.environ.get('DESK_NAMESPACE', ''))
    cli.add_argument('--identity', default=os.environ.get('DESK_IDENTITY', ''))
    cli.add_argument('--confirm', default='')
    commands = cli.add_subparsers(dest='command', required=True)
    for name in ('render', 'setup'):
        command = commands.add_parser(name)
        command.add_argument('--repository', default=DEFAULT_REPO)
        command.add_argument('--cli-image', required=True, type=immutable_image)
        command.add_argument('--python-image', default=r.PYTHON_IMAGE)
        command.add_argument('--database-image', default=r.DATABASE_IMAGE)
    build = commands.add_parser('build')
    build.add_argument('component', choices=['api', 'renderer'])
    build.add_argument('revision')
    for name in ('schema', 'renderer'):
        command = commands.add_parser(name)
        command.add_argument('--image', required=True, type=immutable_image)
    slot = commands.add_parser('slot')
    slot.add_argument('slot', choices=['blue', 'green'])
    slot.add_argument('--image', required=True, type=immutable_image)
    slot.add_argument('--renderer-url', required=True)
    commands.add_parser('network')
    promote = commands.add_parser('promote')
    promote.add_argument('slot', choices=['blue', 'green'])
    commands.add_parser('status')
    clean = commands.add_parser('cleanup')
    clean.add_argument('--delete-data', action='store_true')
    return cli


def main():
    args = parser().parse_args()
    if args.command == 'render':
        items = r.foundation('RENDER-ONLY', args.repository, args.cli_image, args.python_image, args.database_image)
        if args.namespace:
            for item in items:
                item['metadata']['namespace'] = args.namespace
        print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=2))
        return
    cluster = Cluster(args)
    if args.command == 'setup':
        if 'password' not in cluster.state:
            cluster.state['password'] = secrets.token_urlsafe(32)
            cluster.save()
        secret = r.obj('v1', 'Secret', 'desk-db', cluster.owner, type='Opaque',
                       stringData={'password': cluster.state['password']})
        cluster.apply(secret)
        for item in r.foundation(cluster.owner, args.repository, args.cli_image, args.python_image, args.database_image):
            cluster.apply(item)
        cluster.oc('rollout', 'status', 'deployment/desk-db', '--timeout=300s', timeout=330)
    elif args.command == 'build':
        run_pipeline(cluster, args.component, args.revision)
    elif args.command == 'schema':
        cluster.release('api', args.image)
        job = cluster.apply(r.schema_job(cluster.owner, args.image, secrets.token_hex(4)))
        name = job['metadata']['name']
        final = cluster.poll('jobs.batch', name, lambda item: item.get('status', {}).get('succeeded', 0) > 0
                             or item.get('status', {}).get('failed', 0) > 0, timeout=150)
        print(cluster.oc('logs', 'job/' + name))
        if not final.get('status', {}).get('succeeded'):
            raise RuntimeError('Schema initialization failed')
    elif args.command == 'renderer':
        cluster.release('renderer', args.image)
        cluster.apply(r.renderer(cluster.owner, args.image))
        cluster.oc('wait', 'services.serving.knative.dev/desk-renderer', '--for=condition=Ready',
                   '--timeout=300s', timeout=330)
        item = cluster.require_owned('services.serving.knative.dev', 'desk-renderer')
        print(item['status']['url'])
    elif args.command == 'slot':
        cluster.release('api', args.image)
        if not re.fullmatch(r'https?://[^\s/]+', args.renderer_url):
            raise ValueError('Use the exact Knative status URL without a path')
        cluster.apply(r.api_slot(cluster.owner, args.slot, args.image, args.renderer_url))
        print(cluster.oc('rollout', 'status', 'deployment/desk-api-' + args.slot,
                         '--timeout=300s', timeout=330))
    elif args.command == 'network':
        for item in r.api_network(cluster.owner):
            if cluster.read(resource_type(item), item['metadata']['name']):
                cluster.require_owned(resource_type(item), item['metadata']['name'])
                print('Retained existing routing:', item['metadata']['name'], file=sys.stderr)
            else:
                cluster.apply(item)
    elif args.command == 'promote':
        deployment = cluster.require_owned('deployments.apps', 'desk-api-' + args.slot)
        if not deployment_ready(deployment):
            raise ValueError('Candidate is not fully rolled out and available at its current generation')
        cluster.release('api', deployment['spec']['template']['spec']['containers'][0]['image'])
        service = cluster.require_owned('services', 'desk-api')
        patches = [{'op': 'test', 'path': '/metadata/uid', 'value': service['metadata']['uid']},
                   {'op': 'test', 'path': '/metadata/resourceVersion', 'value': service['metadata']['resourceVersion']},
                   {'op': 'replace', 'path': '/spec/selector', 'value': {'app': 'desk-api', 'slot': args.slot}}]
        cluster.oc('patch', 'service', 'desk-api', '--type=json', '-p', json.dumps(patches))
        print('Selected', args.slot, '- verify endpoints and real requests; this is not a transactional cutover.')
    elif args.command == 'status':
        print(cluster.oc('get', 'deployments,services,routes,buildconfigs,pipelineruns.tekton.dev,services.serving.knative.dev',
                         '-l', r.OWNER_LABEL + '=' + cluster.owner))
    elif args.command == 'cleanup':
        cleanup(cluster, args.delete_data)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
