"""Render Kubernetes/OpenShift objects only. Importing this module never contacts a cluster."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OWNER_LABEL = 'ticket-desk.example/owner'
APP_LABEL = 'app.kubernetes.io/part-of'
DATABASE_IMAGE = 'quay.io/sclorg/postgresql-16-c9s:latest'
PYTHON_IMAGE = 'python:3.12-slim'


def metadata(name, owner):
    return {'name': name, 'labels': {APP_LABEL: 'ticket-desk', OWNER_LABEL: owner}}


def obj(api, kind, name, owner, **fields):
    return dict(apiVersion=api, kind=kind, metadata=metadata(name, owner), **fields)


def security_context():
    return {'runAsNonRoot': True, 'allowPrivilegeEscalation': False,
            'capabilities': {'drop': ['ALL']}, 'seccompProfile': {'type': 'RuntimeDefault'}}


def resources(memory='256Mi'):
    return {'requests': {'cpu': '25m', 'memory': '64Mi'},
            'limits': {'cpu': '1', 'memory': memory}}


def database_env():
    return [{'name': 'DB_HOST', 'value': 'desk-db'},
            {'name': 'DB_NAME', 'value': 'desk'}, {'name': 'DB_USER', 'value': 'desk'},
            {'name': 'DB_PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'desk-db', 'key': 'password'}}}]


def pod_spec(container):
    container['securityContext'] = security_context()
    return {'serviceAccountName': 'desk-app', 'automountServiceAccountToken': False,
            'containers': [container]}


def service(name, owner, selector, port=8080):
    return obj('v1', 'Service', name, owner,
               spec={'selector': selector, 'ports': [{'name': 'http' if port == 8080 else 'postgres',
                                                     'port': port, 'targetPort': port}]})


def foundation(owner, repository, cli_image, python_image=PYTHON_IMAGE, database_image=DATABASE_IMAGE):
    match = re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', repository)
    if not match:
        raise ValueError('Use a public HTTPS GitHub repository URL without credentials')
    archive = f'https://codeload.github.com/{match[1]}/{match[2]}/tar.gz'
    items = [obj('v1', 'ServiceAccount', name, owner,
                 automountServiceAccountToken=(name == 'desk-builder'))
             for name in ('desk-app', 'desk-test', 'desk-builder')]
    items += [obj('v1', 'PersistentVolumeClaim', 'desk-db', owner, spec={
        'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '1Gi'}}})]
    database = {'name': 'postgres', 'image': database_image,
                'env': [{'name': 'POSTGRESQL_USER', 'value': 'desk'},
                        {'name': 'POSTGRESQL_DATABASE', 'value': 'desk'},
                        {'name': 'POSTGRESQL_PASSWORD', 'valueFrom': {
                            'secretKeyRef': {'name': 'desk-db', 'key': 'password'}}}],
                'ports': [{'containerPort': 5432}], 'resources': resources('512Mi'),
                'volumeMounts': [{'name': 'data', 'mountPath': '/var/lib/pgsql/data'}],
                'readinessProbe': {'exec': {'command': ['pg_isready', '-U', 'desk', '-d', 'desk']},
                                   'initialDelaySeconds': 10, 'periodSeconds': 5}}
    spec = pod_spec(database)
    spec['volumes'] = [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'desk-db'}}]
    items += [obj('apps/v1', 'Deployment', 'desk-db', owner, spec={
        'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app': 'desk-db'}},
        'template': {'metadata': {'labels': dict(metadata('unused', owner)['labels'], app='desk-db')},
                     'spec': spec}}), service('desk-db', owner, {'app': 'desk-db'}, 5432)]
    for component in ('api', 'renderer'):
        name = 'desk-' + component
        items += [obj('image.openshift.io/v1', 'ImageStream', name, owner),
                  obj('build.openshift.io/v1', 'BuildConfig', name, owner, spec={
                      'runPolicy': 'Serial',
                      'source': {'type': 'Git', 'git': {'uri': repository, 'ref': 'main'},
                                 'contextDir': 'apps/' + component},
                      'strategy': {'type': 'Docker', 'dockerStrategy': {'dockerfilePath': 'Dockerfile'}},
                      'output': {'to': {'kind': 'ImageStreamTag', 'name': name + ':latest'}},
                      'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'},
                                    'limits': {'cpu': '1', 'memory': '1Gi'}},
                      'successfulBuildsHistoryLimit': 3, 'failedBuildsHistoryLimit': 3,
                      'triggers': []})]
    items += [obj('rbac.authorization.k8s.io/v1', 'Role', 'desk-builder', owner, rules=[
        {'apiGroups': ['build.openshift.io'], 'resources': ['buildconfigs'],
         'resourceNames': ['desk-api', 'desk-renderer'], 'verbs': ['get']},
        {'apiGroups': ['build.openshift.io'], 'resources': ['buildconfigs/instantiate'],
         'resourceNames': ['desk-api', 'desk-renderer'], 'verbs': ['create']},
        {'apiGroups': ['build.openshift.io'], 'resources': ['builds'], 'verbs': ['get', 'list', 'watch']},
        {'apiGroups': ['build.openshift.io'], 'resources': ['builds/log'], 'verbs': ['get']},
        {'apiGroups': ['image.openshift.io'], 'resources': ['imagestreams'],
         'resourceNames': ['desk-api', 'desk-renderer'], 'verbs': ['get']},
    ]), obj('rbac.authorization.k8s.io/v1', 'RoleBinding', 'desk-builder', owner,
            subjects=[{'kind': 'ServiceAccount', 'name': 'desk-builder'}],
            roleRef={'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'desk-builder'})]
    items += tekton(owner, archive, cli_image, python_image)
    return items


def task(owner, name, params, step, results=None):
    step['securityContext'] = security_context()
    spec = {'params': [{'name': name, 'type': 'string'} for name in params], 'steps': [step]}
    if results:
        spec['results'] = [{'name': name, 'type': 'string'} for name in results]
    return obj('tekton.dev/v1', 'Task', name, owner, spec=spec)


def tekton(owner, archive, cli_image, python_image):
    common_env = [{'name': 'REVISION', 'value': '$(params.revision)'}]
    source = task(owner, 'desk-source-test', ['revision'], {
        'name': 'test-github-source', 'image': python_image,
        'env': common_env + [{'name': 'ARCHIVE_ROOT', 'value': archive},
                             {'name': 'HOME', 'value': '/work'},
                             {'name': 'PYTHONDONTWRITEBYTECODE', 'value': '1'}],
        'computeResources': resources('512Mi'),
        'volumeMounts': [{'name': 'work', 'mountPath': '/work'}],
        'script': (ROOT / 'deploy/source-test.py').read_text()})
    source['spec']['volumes'] = [{'name': 'work', 'emptyDir': {}}]
    build = task(owner, 'desk-build', ['revision', 'component'], {
        'name': 'openshift-build', 'image': cli_image,
        'env': common_env + [{'name': 'COMPONENT', 'value': '$(params.component)'}],
        'computeResources': resources('256Mi'),
        'script': (ROOT / 'deploy/build.sh').read_text()}, ['image', 'build'])
    image = task(owner, 'desk-image-test', ['image', 'component'], {
        'name': 'test-image', 'image': '$(params.image)', 'workingDir': '/app',
        'env': [{'name': 'COMPONENT', 'value': '$(params.component)'},
                {'name': 'PYTHONDONTWRITEBYTECODE', 'value': '1'}],
        'computeResources': resources('256Mi'),
        'script': (ROOT / 'deploy/image-test.py').read_text()})
    pipeline = obj('tekton.dev/v1', 'Pipeline', 'desk-ci', owner, spec={
        'params': [{'name': name, 'type': 'string'} for name in ('revision', 'component')],
        'results': [{'name': 'image', 'value': '$(tasks.build.results.image)'},
                    {'name': 'build', 'value': '$(tasks.build.results.build)'}],
        'tasks': [
            {'name': 'source-tests', 'taskRef': {'name': 'desk-source-test'},
             'params': [{'name': 'revision', 'value': '$(params.revision)'}]},
            {'name': 'build', 'runAfter': ['source-tests'], 'taskRef': {'name': 'desk-build'},
             'params': [{'name': key, 'value': f'$(params.{key})'} for key in ('revision', 'component')]},
            {'name': 'image-tests', 'runAfter': ['build'], 'taskRef': {'name': 'desk-image-test'},
             'params': [{'name': 'component', 'value': '$(params.component)'},
                        {'name': 'image', 'value': '$(tasks.build.results.image)'}]},
        ]})
    return [source, build, image, pipeline]


def pipeline_run(owner, component, revision):
    item = obj('tekton.dev/v1', 'PipelineRun', 'unused', owner, spec={
        'pipelineRef': {'name': 'desk-ci'},
        'taskRunTemplate': {'serviceAccountName': 'desk-builder'},
        'taskRunSpecs': [{'pipelineTaskName': name, 'serviceAccountName': 'desk-test'}
                         for name in ('source-tests', 'image-tests')],
        'timeouts': {'pipeline': '35m0s'},
        'params': [{'name': 'component', 'value': component}, {'name': 'revision', 'value': revision}]})
    del item['metadata']['name']
    item['metadata']['generateName'] = 'desk-ci-'
    return item


def schema_job(owner, image, suffix):
    container = {'name': 'schema', 'image': image,
                 'command': ['python', '-m', 'ticket_api.repository'],
                 'env': database_env(), 'resources': resources()}
    return obj('batch/v1', 'Job', 'desk-schema-' + suffix, owner,
               spec={'backoffLimit': 0, 'activeDeadlineSeconds': 120,
                     'template': {'metadata': {'labels': metadata('unused', owner)['labels']},
                                  'spec': dict(pod_spec(container), restartPolicy='Never')}})


def api_slot(owner, slot, image, renderer_url):
    labels = dict(metadata('unused', owner)['labels'], app='desk-api', slot=slot)
    container = {'name': 'api', 'image': image, 'ports': [{'containerPort': 8080}],
                 'env': database_env() + [{'name': 'RENDERER_URL', 'value': renderer_url}],
                 'resources': resources(),
                 'readinessProbe': {'httpGet': {'path': '/readyz', 'port': 8080},
                                    'initialDelaySeconds': 2, 'periodSeconds': 5},
                 'livenessProbe': {'httpGet': {'path': '/healthz', 'port': 8080},
                                   'initialDelaySeconds': 10, 'periodSeconds': 10}}
    return obj('apps/v1', 'Deployment', 'desk-api-' + slot, owner, spec={
        'replicas': 1, 'selector': {'matchLabels': {'app': 'desk-api', 'slot': slot}},
        'template': {'metadata': {'labels': labels}, 'spec': pod_spec(container)}})


def api_network(owner):
    return [service('desk-api', owner, {'app': 'desk-api', 'slot': 'blue'}),
            service('desk-preview', owner, {'app': 'desk-api', 'slot': 'green'}),
            obj('route.openshift.io/v1', 'Route', 'desk-api', owner, spec={
                'to': {'kind': 'Service', 'name': 'desk-api'}, 'port': {'targetPort': 'http'},
                'tls': {'termination': 'edge', 'insecureEdgeTerminationPolicy': 'Redirect'}})]


def renderer(owner, image):
    return obj('serving.knative.dev/v1', 'Service', 'desk-renderer', owner, spec={
        'template': {'metadata': {'annotations': {'autoscaling.knative.dev/min-scale': '0',
                                                 'autoscaling.knative.dev/max-scale': '2'}},
                     'spec': {'serviceAccountName': 'desk-app', 'automountServiceAccountToken': False,
                              'timeoutSeconds': 30, 'containers': [{
                                  'name': 'renderer', 'image': image,
                                  'securityContext': security_context(),
                                  'ports': [{'containerPort': 8080}], 'resources': resources(),
                                  'readinessProbe': {'httpGet': {'path': '/readyz', 'port': 8080}}}]}}})
