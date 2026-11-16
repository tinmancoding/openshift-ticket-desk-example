# GitHub to a controlled release

This is an opt-in walkthrough, not a run-all script. Start from a clean **`main` baseline (API 1.0.0)**; `feature/urgent-tickets` is the already-completed 1.1.0 reference solution. Preserve any local edits before changing branches. Read the architecture first. Do not continue after a failed command. Use only your assigned isolated namespace and synthetic data. Keep your Git checkout, CLI state and evidence until cleanup is audited.

## 1. Platform prerequisites

You need Bash, Python 3.12+, Git, `oc`, and optionally `tkn` for archived Task logs. The CLI uses the current kubeconfig, but always supplies an explicit namespace. Log in using your own authorized account before beginning. No step installs operators or grants a privileged SCC.

The cluster must already provide:

- OpenShift/OKD Git-source Docker builds, ImageStreams and an internal registry;
- Tekton `tekton.dev/v1` and Knative Serving `serving.knative.dev/v1`;
- dynamic RWO PVC provisioning, usable PostgreSQL image, ingress and trusted TLS;
- namespace permission to create the listed workloads, BuildConfigs, ServiceAccounts and narrow Role/RoleBinding;
- sufficient quota for PostgreSQL, blue/green API Pods, Knative renderer and **sequential** build/Task Pods;
- egress to public GitHub, image registries and Python package repositories.

```bash
# Example authorized test namespace. Replace these for your own installation.
export DESK_NAMESPACE=learner09
export DESK_IDENTITY=learner09
oc whoami
oc get namespace "$DESK_NAMESPACE"
oc api-resources --api-group=build.openshift.io
oc api-resources --api-group=tekton.dev
oc api-resources --api-group=serving.knative.dev
oc get quota,limitrange -n "$DESK_NAMESPACE"
oc auth can-i create buildconfigs.build.openshift.io -n "$DESK_NAMESPACE"
oc auth can-i create roles.rbac.authorization.k8s.io -n "$DESK_NAMESPACE"
oc auth can-i create rolebindings.rbac.authorization.k8s.io -n "$DESK_NAMESPACE"
```

The tools reject a different `oc whoami` identity. They never switch the current project or use instructor credentials as a fallback. Reserve all `desk-*` names. Existing unowned/replaced resources cause a refusal, not silent adoption.

## 2. Publish source and review definitions

Clone your own repository/fork. Push the implementation before using it as a build source. Do not put access tokens into repository URLs, Task parameters, files or evidence. This example supports public HTTPS GitHub source; private source needs a separately reviewed credential design.

```bash
REPOSITORY=https://github.com/tinmancoding/openshift-ticket-desk-example.git
BASE_SHA=$(git rev-parse HEAD)
# Verify this exact commit is already pushed/reachable in REPOSITORY.
git status --short
git remote -v
```

Resolve an approved OpenShift CLI image **by digest**. For example, where your platform publishes this ImageStreamTag:

```bash
CLI_IMAGE=$(oc get istag cli:latest -n openshift -o jsonpath='{.image.dockerImageReference}')
# Inspect the value; it must contain a full @sha256:digest and be pullable by Task Pods.
printf '%s\n' "$CLI_IMAGE"
mkdir -p build
python3 scripts/desk.py --namespace "$DESK_NAMESPACE" render \
  --repository "$REPOSITORY" --cli-image "$CLI_IMAGE" > build/foundation.json
```

Read `build/foundation.json`: database/PVC, token-free identities, two Git BuildConfigs, namespace build Role/RoleBinding, three Tasks and Pipeline. Rendering does not contact a cluster or generate a Secret. The Python task and PostgreSQL image have configurable development tags; an instructor/production adaptation should supply approved digests through `--python-image` and `--database-image` on both render and setup. Dockerfile base tags are separate and should also be pinned for reproducible delivery.

Do not apply the render-only output manually: its owner marker is not an installation receipt. Use the ownership-aware setup command after review. You can use server dry-run to check admission without persisting it, but that is not runtime acceptance.

## 3. Create the foundation

Define a convenience function that still requires the explicit namespace confirmation on every mutation:

```bash
desk() { python3 scripts/desk.py --confirm "$DESK_NAMESPACE" "$@"; }
desk setup --repository "$REPOSITORY" --cli-image "$CLI_IMAGE"
```

Setup creates a private random database password in an OpenShift Secret and ignored mode-0600 local state. It never prints the Secret. Protect `.state/` like credentials; do not commit/copy it into source archives. The CLI records owner labels and exact UIDs for cleanup. Retain that state; losing it intentionally prevents the tool from claiming ownership of existing resources.

**Expected:** PostgreSQL Ready with a Bound 1-GiB PVC; two BuildConfigs with `source.type: Git`, per-component contexts and `triggers: []`; no image build merely from applying definitions. The API table is not initialized yet. The separate schema Job below is intentional.

## 4. Run CI at one exact Git commit

```bash
# Sequentially test source, build via BuildConfig and test the actual image.
RENDERER_IMAGE=$(desk build renderer "$BASE_SHA")
API_BLUE_IMAGE=$(desk build api "$BASE_SHA")
printf '%s\n' "$RENDERER_IMAGE" > build/renderer-image.txt
printf '%s\n' "$API_BLUE_IMAGE" > build/api-blue-image.txt
```

Only continue if **both commands succeed** and both outputs contain immutable `@sha256:…` references. In Bash, check command failures before reading old files or reusing old variables. No later command should infer approval from `latest`.

Follow a run independently if desired:

```bash
oc get pipelineruns.tekton.dev -n "$DESK_NAMESPACE"
# Replace RUN with its actual name.
# tkn pipelinerun logs RUN -f -n "$DESK_NAMESPACE"
```

Each source Task downloads the repository at `BASE_SHA`, runs all required tests and gates the Build. The Build task asks OpenShift to fetch the same Git commit, waits for that exact Build, checks its recorded commit and returns its output digest. The image Task then tests that digest. No Task builds with Buildah, uploads local files or deploys an application.

The CLI archives final Run/Build JSON in `.state/desk-ci-*/` and logs if `tkn` is available. Successful release digests are recorded in private namespace state. Deployment commands refuse an image that has no successful whole-Run record there. This is a classroom safeguard, not a cryptographically signed approval system.

### Optional rejection demonstration

On a separate Git branch, add a deliberately failing unit test, commit/push it, then invoke `desk build api FAILED_SHA`. **Expected:** source-tests fails; build and image-tests do not run. Inspect the Run and verify no new application Build was instantiated. Restore the passing source and push before proceeding. Do not weaken/remove real tests to make the release green.

## 5. Initialize the schema and deploy the renderer

```bash
# The initial migration is idempotent CREATE TABLE, not a full migration system.
desk schema --image "$API_BLUE_IMAGE"
RENDERER_URL=$(desk renderer --image "$RENDERER_IMAGE")
printf '%s\n' "$RENDERER_URL"
```

The renderer command waits for Knative Ready and prints its actual status URL. Use that URL as the API's dependency; do not invent a hostname or assume HTTPS. The API calls it from inside the cluster. If the platform's external URL is not reachable internally, resolve supported internal ingress with the platform owner rather than modifying arbitrary system resources.

Inspect its Revision and image:

```bash
oc get services.serving.knative.dev/desk-renderer -n "$DESK_NAMESPACE"
oc get revisions.serving.knative.dev -n "$DESK_NAMESPACE" \
  -l serving.knative.dev/service=desk-renderer
```

## 6. Bring up blue and exercise a real ticket

```bash
desk slot blue --image "$API_BLUE_IMAGE" --renderer-url "$RENDERER_URL"
desk network
API_URL=https://$(oc get route/desk-api -n "$DESK_NAMESPACE" -o jsonpath='{.spec.host}')
python3 scripts/smoke.py --url "$API_URL" --expected-version 1.0.0 --confirm-create
```

The network command creates stable blue and preview green Services and an edge-TLS API Route. On reruns it **retains** owned routing rather than accidentally promoting/rolling back. Green has no endpoints yet. Use trusted ingress certificates; do not hide CA issues with `curl -k`.

**Expected:** API reports 1.0.0; a normal-priority ticket is stored/read; its preview includes the same ticket ID and title. Keep the printed `ticket_id` as `OLD_TICKET_ID` for persistence checks. The smoke script creates synthetic data and retries only safe preview GETs when a cold renderer returns a temporary 503.

```bash
OLD_TICKET_ID=1  # replace with the ID actually printed by your smoke run
```

## 7. Make a realistic backwards-compatible release

Create a feature branch in a repository where you have push permission:

```bash
git switch -c feature/my-urgent-tickets
```

In `apps/api/ticket_api/__init__.py`:

- change `VERSION = "1.0.0"` to `VERSION = "1.1.0"`;
- add `"urgent"` to `PRIORITIES`, keeping `normal` and `high`.

Add a test method to `ApiTests` in `tests/test_apps.py`:

```python
    def test_urgent_ticket(self):
        response = self.client.post('/tickets', json={'title': 'System unavailable', 'priority': 'urgent'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['priority'], 'urgent')
```

This requires no table change: priority is already a short string. Blue can read urgent tickets, even though it rejects creating them. We deliberately avoid mixing a traffic-switch exercise with an unsafe incompatible database migration.

```bash
make check
git diff --check
git diff
git add apps/api/ticket_api/__init__.py tests/test_apps.py
git commit -m "Support urgent tickets without changing existing clients"
git push -u origin feature/my-urgent-tickets
GREEN_SHA=$(git rev-parse HEAD)
API_GREEN_IMAGE=$(desk build api "$GREEN_SHA")
desk slot green --image "$API_GREEN_IMAGE" --renderer-url "$RENDERER_URL"
```

The renderer did not change; do not rebuild/redeploy it merely because the API changed. Green uses the same database and renderer URL as blue.

## 8. Verify green before production traffic

Keep this port-forward running in one terminal:

```bash
oc port-forward -n "$DESK_NAMESPACE" service/desk-preview 18080:8080
```

In another terminal in the repository, substitute your earlier ticket ID:

```bash
python3 scripts/smoke.py --url http://127.0.0.1:18080 \
  --expected-version 1.1.0 --priority urgent --existing-id 1 --confirm-create
```

**Expected:** green reports 1.1.0, reads the earlier blue ticket, persists an urgent ticket and gets its renderer preview. Keep that urgent ticket's ID. Production must still report blue:

```bash
curl --fail-with-body -sS "$API_URL/version"
oc describe svc desk-api -n "$DESK_NAMESPACE"
```

Stop the forward with Ctrl+C. A candidate test can write to the shared database even before promotion; isolation of traffic is not isolation of data. Use synthetic records only.

## 9. Promote and roll back without rebuilding

```bash
# Explicit human approval after reviewing candidate evidence.
desk promote green
oc describe svc desk-api -n "$DESK_NAMESPACE"
python3 scripts/smoke.py --url "$API_URL" --expected-version 1.1.0 \
  --priority urgent --existing-id "$OLD_TICKET_ID" --confirm-create

# Rollback changes the same Service selector, not image tags or Deployment history.
desk promote blue
oc describe svc desk-api -n "$DESK_NAMESPACE"
python3 scripts/smoke.py --url "$API_URL" --expected-version 1.0.0 \
  --existing-id "$OLD_TICKET_ID" --confirm-create
```

Endpoint convergence is asynchronous. If a version check briefly sees the old slot, inspect EndpointSlices and retry after convergence. Do not change expected versions to disguise a failed release. Also read the urgent ticket through blue after rollback: it remains stored. A rollback does not erase data or reverse a migration. New urgent POSTs to blue should be rejected with 400.

`rollout undo` is not the correct routing rollback: the release changed a Service selector, not either Deployment template. Keep both slots ready until rollback has been verified. The CLI checks availability before selecting a slot; it does not automatically substitute a smoke-test approval.

## 10. Observe Knative independently

Stop sending requests to the renderer/API preview endpoint. After the configured idle window, inspect:

```bash
oc get pods -n "$DESK_NAMESPACE" -l serving.knative.dev/service=desk-renderer
oc get deployments -n "$DESK_NAMESPACE"
```

Whether scale-to-zero occurs depends on policy and traffic. PostgreSQL and both API slots remain ordinary running Deployments. Request another ticket preview to observe wake-up. A new API release/selector does not create a new renderer Revision; changing the renderer template/image would.

## 11. Cleanup deliberately

Follow [operations and cleanup](operations.md). The data PVC and Secret are retained by default. Only use `desk cleanup --delete-data` when you explicitly intend to erase the example's database too. Inspect/cancel active Runs/Builds first, retain evidence and verify generated children disappear with their parents.
