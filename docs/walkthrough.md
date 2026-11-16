# Walkthrough: build, test and release Ticket Desk

**Start here.** You will apply readable YAML, run a Pipeline, and switch a Service between two versions. There is no custom deployment CLI, manifest generator or required Python command on your workstation.

Use the repository's `main` branch. This first pass uses two **already published application commits**: API 1.0.0 (blue) and API 1.1.0 (green, adding urgent tickets). You do not need a GitHub fork or push permission to complete it. [Releasing your own API change](your-own-release.md) is a separate follow-up.

You apply the YAML from this checkout. The prepared PipelineRuns fetch the fixed application commit SHAs recorded in `openshift/runs/`; they do **not** build your working tree or a moving `main` branch.

## What you will have at the end

```text
GitHub source -> Tekton tests -> OpenShift BuildConfig -> tested image

client -> API Service -> blue 1.0.0 OR green 1.1.0 -> PostgreSQL
                                      |
                                      +-> Knative notification renderer
```

Both API versions use the same database. You will test green before switching production traffic, then switch back to blue. The renderer produces a notification **preview**; no email is sent.

## Before you start

You need a **Bash-compatible terminal**, Git, `oc`, `tkn` (the Tekton CLI), `curl`, an editor, and an account in a prepared OpenShift/OKD cluster. On Windows, use WSL or an instructor-provided Bash/browser terminal, not PowerShell or Command Prompt.

The instructor should confirm these cluster requirements before you start:

- Working Git/Docker BuildConfigs, an internal registry, Tekton, Knative Serving, dynamic storage and ingress.
- Builds and Tasks can download public GitHub source, Python packages, and images from Docker Hub and Quay.
- Your terminal can reach the cluster API and the application's URLs, using trusted certificates.

Ask the instructor if anything is unavailable. This walkthrough does not install operators or change cluster policy.

Use **only synthetic tickets in your assigned project**. This example has no login or access controls. Do not use a shared production namespace.

Clone this repository if you have not already done so, then enter its root:

```bash
git clone https://github.com/tinmancoding/openshift-ticket-desk-example.git
cd openshift-ticket-desk-example
```

If the directory already exists, use that checkout instead of cloning over it. All relative file paths below assume you stay in this directory. Keep one main terminal open so its variables remain available; a second terminal is used only for port forwarding.

### Words you will need

| Word | Meaning here |
| --- | --- |
| Project / namespace | Your isolated workspace in the cluster. |
| YAML manifest | A file describing a resource you want the cluster to create. |
| Deployment / Pod | A running application recipe / a running copy of its container. |
| Service / selector | A stable internal address / labels identifying the Pods it sends requests to. |
| Route | OpenShift's public URL for an ordinary Service. |
| Secret / PVC | Password storage / a request for persistent disk storage. |
| BuildConfig / Build | An image-build recipe / one execution of it. |
| Task / Pipeline / PipelineRun | Reusable work / its order / one actual execution. |
| ImageStream / tag | OpenShift's named record of images / a movable pointer such as `latest`. |
| Image digest | `sha256:` followed by 64 hexadecimal characters, identifying a specific image. A full image reference looks like `registry/repository@sha256:…`; unlike a `latest` tag, it does not move. |
| Knative Service / Revision | An HTTP application managed by Knative / one immutable version of its configuration. |

### The four file operations

| Command | When to use it |
| --- | --- |
| `oc apply -f FILE.yaml` | Create or update a normal resource definition. |
| `oc process -f TEMPLATE.yaml -p NAME=value -o yaml` | Fill in an OpenShift Template's parameters and print normal YAML. It does **not** deploy it. |
| `oc create -f RUN.yaml` | Start a new named execution, such as a PipelineRun or Job. |
| `oc patch service NAME --type=merge --patch-file FILE.yaml` | Change only the fields shown in a patch file. |

A Template has `kind: Template`, a `parameters` list, and `objects`. `${API_IMAGE}` in a Template is filled by `oc process`. `$(params.revision)` in a Tekton Task is different: Tekton fills it when the Task runs.

We save processed YAML in ignored **`.local/`** so you can inspect exactly what will be applied. The output may use a normal Kubernetes `kind: List` wrapper around its objects; that is not another Template. Never run `oc apply -f openshift/ --recursive`: that directory intentionally contains different file kinds, optional failures and traffic-switch patches.

## 1. Choose and check your project

```bash
# Confirm that you are logged in as yourself.
oc whoami

# Replace YOUR_PROJECT with the project assigned to you.
oc project YOUR_PROJECT

# Confirm the selected project and inspect its current workloads.
oc project
oc get deployment,service,route,bc,is,pvc
oc get quota,limitrange
```

**Stop if the project or identity is wrong.** `oc project` selects the project for subsequent commands in this kubeconfig. Later commands omit `-n` to stay readable; they operate in this selected project.

This example uses fixed **`desk-*`** names. If they already exist and you cannot confirm they are your own earlier attempt, stop and ask the instructor. `oc apply` can update an existing object; labels alone do not prove ownership.

**Good looks like:** your own identity/project and enough available quota. The instructor should check capacity for a database, two API Pods, a renderer and sequential build/Task Pods.

## 2. Create the database password and application identities

**Choose the right path before copying anything:**

- **First installation:** create the private Secret file with the commands below.
- **Restarting with retained data:** reuse your existing `.local/database-secret.yaml`. **Skip the copy and password-editing steps.** Do not replace it or choose a new password for the retained disk. If the matching file is missing, stop and ask the instructor before changing the Secret.

For a first installation only:

```bash
mkdir -p .local
cp openshift/database-secret.example.yaml .local/database-secret.yaml
chmod 600 .local/database-secret.yaml
```

Open **`.local/database-secret.yaml`** in your editor. Replace `REPLACE_WITH_A_LONG_RANDOM_PASSWORD` with a random password of at least 32 characters. For this exercise, use only letters (`A–Z`, `a–z`) and digits (`0–9`), **starting with a letter**. This avoids YAML quoting rules. Keep `password: ` and its indentation unchanged.

Do not share/commit this file or print its contents in a recording. `stringData` accepts text; you do not need to base64-encode the password.

Once you have the correct private file—new or reused—apply it and the prepared identities:

```bash
oc apply -f .local/database-secret.yaml
oc apply -f openshift/00-identities.yaml
```

**What just happened:** `desk-app` is the application identity, `desk-test` runs token-free tests, and `desk-builder` can start the two named BuildConfigs. Its Role does **not** allow deploying applications, changing traffic or reading Secrets. If this Role/RoleBinding is denied, ask the instructor; do not grant `edit` or cluster-admin.

**Good looks like:** one Secret, three ServiceAccounts and the narrow namespace Role/RoleBinding created. On a retry, do not generate/change the password while retaining an existing database disk.

## 3. Start PostgreSQL with persistent storage

Read these files before applying them:

- `openshift/01-storage.yaml`: a 1-GiB PVC named `desk-db`.
- `openshift/02-database.yaml`: one PostgreSQL Deployment and its internal Service. The password comes from the Secret, not a literal Deployment value.

```bash
oc apply -f openshift/01-storage.yaml
oc apply -f openshift/02-database.yaml
oc rollout status deployment/desk-db --timeout=300s
oc get pvc desk-db
```

**Good looks like:** Deployment successfully rolled out; PVC is `Bound`. On a first installation, the application's table does not exist yet; we will create it with a Job after building the API image. If you kept an earlier database disk, its table and tickets may already exist.

If storage is Pending or the rollout times out, inspect `oc describe pvc desk-db` and `oc describe deployment desk-db`. Do not continue to the application steps until this is fixed.

## 4. Create the two image-build recipes

Open `openshift/templates/builds.yaml`. Notice the two Git source contexts: `apps/api` and `apps/renderer`. Both use their existing Dockerfiles and write to separate ImageStreams. `triggers: []` means applying these definitions does not start a build.

```bash
# Fill the Template's default public GitHub repository value.
oc process -f openshift/templates/builds.yaml -o yaml > .local/builds.yaml

# Inspect .local/builds.yaml in your editor, then create the recipes.
oc apply -f .local/builds.yaml
oc get bc
```

**Good looks like:** `desk-api` and `desk-renderer` BuildConfigs exist. Nothing has been deployed or built by this step.

The source repository is already configured for this walkthrough. If using a fork later, change the `GITHUB_REPOSITORY` parameter consistently in both the build and Task Templates; see [your own release](your-own-release.md).

## 5. Create the Tekton workflow

Read the short **`openshift/ci/pipeline.yaml`** first. It names three Tasks in this order:

```text
source-tests -> build -> image-tests
```

1. Test the source at an exact published commit.
2. Ask the matching Git-source BuildConfig to build **that same commit**.
3. Run a contract check inside **that exact built image**.

The longer `openshift/templates/tasks.yaml` contains those Task implementations. You do not need to edit their scripts for this first pass. Python in a Task tests the Python application; it does not generate or modify Kubernetes manifests.

```bash
oc process -f openshift/templates/tasks.yaml -o yaml > .local/tasks.yaml
oc apply -f .local/tasks.yaml
oc apply -f openshift/ci/pipeline.yaml
oc get tasks.tekton.dev,pipelines.tekton.dev
```

**Good looks like:** three Tasks and one Pipeline exist. Definitions are not executions: no PipelineRun has started yet. The Task Template includes a previously tested OKD 4.21 CLI image digest; the instructor must check compatibility and may override `CLI_IMAGE` for another cluster.

## 6. Build and test the renderer

Open **`openshift/runs/renderer-ci.yaml`**. Its name is `desk-renderer-ci`; its component is `renderer`; its revision is a full published Git commit SHA. The file selects who runs each Task as well.

**If a Run already exists:** inspect that execution instead of treating it as a new attempt. For a deliberate retry, copy its file into `.local/` and edit `metadata.name` to a new unused name. For example, copy the renderer file to `.local/renderer-ci-retry.yaml` and name its Run `desk-renderer-ci-retry`. Then use `oc create -f .local/renderer-ci-retry.yaml`—not the original file. Use the new Run name in every log, wait, result and evidence command, and keep the copied file for cleanup. Do not overwrite a failed execution's evidence.

For a new installation, start the prepared Run:

```bash
# Create a new execution; do not apply a Run as though it were a recipe.
oc create -f openshift/runs/renderer-ci.yaml

# Watch the three Tasks' output.
tkn pipelinerun logs desk-renderer-ci -f

# Wait for whole-workflow success, not just image-build completion.
oc wait pipelinerun/desk-renderer-ci --for=condition=Succeeded --timeout=35m
```

**Good looks like:** tests pass, a Build completes, built-image checks pass, and `oc wait` reports `condition met`. Unit tests deliberately exercise some error paths, so individual log lines can contain `ERROR` while their assertions pass; require the test runner's final `OK` and the whole Run's success, not just a keyword in a log. Inspect `tkn pipelinerun describe desk-renderer-ci` if it fails. A failed Run will not turn successful just because you wait longer. Stop here on failure.

Now save its approved image reference:

```bash
RENDERER_IMAGE=$(oc get pipelinerun desk-renderer-ci -o jsonpath='{.status.results[?(@.name=="image")].value}')
printf '%s\n' "$RENDERER_IMAGE"
```

`NAME=$(command)` stores a command's output in a shell variable. This fixed JSONPath expression reads the result named `image` from the Run. You do not need to invent a query: compare the printed value with **Results** in `tkn pipelinerun describe`.

**Expected:** a full registry image reference containing `@sha256:` followed by 64 hexadecimal characters. An empty value or `latest` is not an approved artifact. Only read/use results after the **whole Run** succeeds; a failed image test may still leave a built image in the registry.

## 7. Build and test blue API 1.0.0

The API Run uses the same baseline commit, but component `api` and a different execution name.

```bash
oc create -f openshift/runs/api-blue-ci.yaml
tkn pipelinerun logs desk-api-blue-ci -f
oc wait pipelinerun/desk-api-blue-ci --for=condition=Succeeded --timeout=35m

# Save the image only after the Run succeeds.
API_BLUE_IMAGE=$(oc get pipelinerun desk-api-blue-ci -o jsonpath='{.status.results[?(@.name=="image")].value}')
printf '%s\n' "$API_BLUE_IMAGE"
```

**Good looks like:** whole-Run success and another immutable image reference. No application Deployment follows the ImageStream's moving `latest` tag automatically.

If `oc create` reports `AlreadyExists`, use the [named retry procedure in step 6](#6-build-and-test-the-renderer). A completed Run is not rerun by applying or creating its definition again.

## 8. Create the initial table with a Job

A Job runs one finite operation. This one uses the approved API image to initialize the table; it does not start a web server.

```bash
oc process -f openshift/templates/schema-job.yaml \
  -p API_IMAGE="$API_BLUE_IMAGE" -o yaml > .local/schema-job.yaml

# Read the processed file, then start this execution.
oc create -f .local/schema-job.yaml
oc wait job/desk-schema --for=condition=Complete --timeout=150s
oc logs job/desk-schema
```

**Expected log:** `Ticket schema initialized (idempotent initial schema only).` If the Job fails, inspect its logs and database settings. Do not continue with an uninitialized table. This is initial setup, not a production migration framework.

**Retrying a failed Job:** fix the cause and save the failed Job's logs first. Copy `.local/schema-job.yaml` to `.local/schema-job-retry.yaml`. In that copy, change the **Job's** `metadata.name` from `desk-schema` to the unused name `desk-schema-retry`; leave the other fields unchanged. Then run:

```bash
oc create -f .local/schema-job-retry.yaml
oc wait job/desk-schema-retry --for=condition=Complete --timeout=150s
oc logs job/desk-schema-retry
```

Only continue after that new Job completes. Keep both files/logs and include the retry file in cleanup. An already-completed Job is not rerun by issuing `create` again.

## 9. Deploy the renderer with Knative

```bash
oc process -f openshift/templates/renderer.yaml \
  -p RENDERER_IMAGE="$RENDERER_IMAGE" -o yaml > .local/renderer.yaml
```

Open `.local/renderer.yaml`. Check that the Knative Service is named `desk-renderer`, its image matches the successful renderer Run's digest, and its container port is 8080. Then apply it:

```bash
oc apply -f .local/renderer.yaml
oc wait services.serving.knative.dev/desk-renderer --for=condition=Ready --timeout=300s

# Store its actual URL for the API's configuration.
RENDERER_URL=$(oc get services.serving.knative.dev desk-renderer -o jsonpath='{.status.url}')
printf '%s\n' "$RENDERER_URL"
```

**Good looks like:** Knative Ready and a nonempty URL, including `http://` or `https://` as supplied by your platform. Keep that scheme. The API calls this URL from inside the cluster; a policy/ingress problem requires instructor help, not disabled TLS verification.

Knative runs this **existing image** as an immutable Revision; it does not rebuild it. Only the renderer is managed by Knative. PostgreSQL and the API remain ordinary Deployments.

## 10. Deploy blue and create the public API address

```bash
oc process -f openshift/templates/api-slot.yaml \
  -p SLOT=blue -p API_IMAGE="$API_BLUE_IMAGE" -p RENDERER_URL="$RENDERER_URL" \
  -o yaml > .local/api-blue.yaml
```

Open `.local/api-blue.yaml`. Check the Deployment name `desk-api-blue`, Pod label `slot: blue`, tested blue image digest, and renderer URL. Then apply it:

```bash
oc apply -f .local/api-blue.yaml
oc rollout status deployment/desk-api-blue --timeout=300s

# INITIAL network setup: stable Service selects blue, preview selects green.
oc apply -f openshift/03-network.yaml
oc get route desk-api
```

**Important:** do not reapply `03-network.yaml` after promotion unless you deliberately want its blue selector restored. Later traffic changes use the small patch files instead.

```bash
# Read the Route's host and construct its HTTPS URL.
API_HOST=$(oc get route desk-api -o jsonpath='{.spec.host}')
API_URL="https://$API_HOST"
curl --fail-with-body -sS "$API_URL/version"
```

**Expected:** `{"component":"api","version":"1.0.0"}` (field order may differ). Use trusted ingress certificates; do not add `-k` to hide certificate problems.

## 11. Create a ticket and request its preview

```bash
curl --fail-with-body -sS "$API_URL/tickets" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Printer is offline","priority":"normal"}'
```

**Expected:** a stored ticket containing `id`, `title`, `priority` and `created_at`. Record its **actual** ID. It is often 1 in a fresh database, but retained data can change that.

```bash
TICKET_ID=1  # replace 1 with the ID in YOUR response
curl --fail-with-body -sS "$API_URL/tickets/$TICKET_ID"
curl --fail-with-body -sS "$API_URL/tickets/$TICKET_ID/notification-preview"
```

**Expected:** the same stored ticket, then a preview whose `ticket_id` matches and whose subject includes `Printer is offline`. That proves the running API can read PostgreSQL and call the Knative renderer—not merely that a readiness probe passed.

If a cold renderer causes a temporary 503, retry the **preview GET** after a few seconds. Do not automatically retry the ticket-creation POST: it could create a duplicate.

## 12. Build green API 1.1.0 and keep it isolated

The prepared green Run selects a published commit that accepts `urgent` priority. Existing `normal`/`high` requests still work. The database schema is unchanged. You can inspect the [source change](https://github.com/tinmancoding/openshift-ticket-desk-example/commit/e88bfa8912e6123f86ad7b7864f9f64b8433a125) without implementing it yet. If this Run already exists, follow the [step 6 retry procedure](#6-build-and-test-the-renderer) with a new name.

```bash
oc create -f openshift/runs/api-green-ci.yaml
tkn pipelinerun logs desk-api-green-ci -f
oc wait pipelinerun/desk-api-green-ci --for=condition=Succeeded --timeout=35m

# Stop on failure; otherwise record its exact tested image.
API_GREEN_IMAGE=$(oc get pipelinerun desk-api-green-ci -o jsonpath='{.status.results[?(@.name=="image")].value}')
printf '%s\n' "$API_GREEN_IMAGE"

oc process -f openshift/templates/api-slot.yaml \
  -p SLOT=green -p API_IMAGE="$API_GREEN_IMAGE" -p RENDERER_URL="$RENDERER_URL" \
  -o yaml > .local/api-green.yaml
```

Open `.local/api-green.yaml`. Check the Deployment name `desk-api-green`, Pod label `slot: green`, tested green image digest, and the same renderer URL used by blue. Then apply it:

```bash
oc apply -f .local/api-green.yaml
oc rollout status deployment/desk-api-green --timeout=300s
```

**Good looks like:** green successfully rolled out. Production must still be blue:

```bash
curl --fail-with-body -sS "$API_URL/version"
oc describe service desk-api
```

Expect version **1.0.0** and selector **`app=desk-api,slot=blue`**. The green image has not been promoted just because it was built or deployed.

## 13. Test green through the preview Service

In a **second terminal**, select the same project, then keep this command running:

```bash
oc project YOUR_PROJECT
oc port-forward service/desk-preview 18080:8080
```

Port forwarding maps your second terminal's local port 18080 to green's port 8080. If working in browser terminals, both terminals must share the same network environment for localhost access; otherwise use an instructor-approved preview endpoint.

Back in the **original terminal**, where your variables still exist:

```bash
curl --fail-with-body -sS http://127.0.0.1:18080/version
curl --fail-with-body -sS "http://127.0.0.1:18080/tickets/$TICKET_ID"
curl --fail-with-body -sS http://127.0.0.1:18080/tickets \
  -H 'Content-Type: application/json' \
  -d '{"title":"Checkout is unavailable","priority":"urgent"}'
```

**Expected:** green reports **1.1.0**, can read blue's earlier ticket, and accepts the new urgent ticket. Record its actual ID:

```bash
URGENT_TICKET_ID=2  # replace 2 with the ID in YOUR green response
curl --fail-with-body -sS "http://127.0.0.1:18080/tickets/$URGENT_TICKET_ID/notification-preview"
curl --fail-with-body -sS "$API_URL/version"
```

Expect the urgent ticket's preview and production still reporting **1.0.0**. The candidate shares the database, so its test writes are real even before promotion. Use synthetic data only.

Stop the forward with **Ctrl+C in the second terminal** when finished. Keep the original terminal open.

## 14. Promote green, then roll back

Open **`openshift/traffic/to-green.patch.yaml`**. It contains only a Service selector:

```yaml
spec:
  selector:
    app: desk-api
    slot: green
```

This is a **patch**, not a whole Service to apply. Before switching, verify both slots have finished rolling out and you have accepted the preview results:

```bash
oc rollout status deployment/desk-api-blue --timeout=300s
oc rollout status deployment/desk-api-green --timeout=300s
oc patch service desk-api --type=merge --patch-file openshift/traffic/to-green.patch.yaml
oc describe service desk-api
curl --fail-with-body -sS "$API_URL/version"
```

**Expected:** selector green and version **1.1.0**. Endpoint changes are asynchronous: existing requests may finish on blue; if necessary inspect/retry a GET after convergence. Do not change the expected version to conceal a problem.

Create an urgent ticket through the production URL to verify the new capability:

```bash
curl --fail-with-body -sS "$API_URL/tickets" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Production release check","priority":"urgent"}'
```

Now restore blue **without rebuilding**:

```bash
oc patch service desk-api --type=merge --patch-file openshift/traffic/to-blue.patch.yaml
oc describe service desk-api
curl --fail-with-body -sS "$API_URL/version"
curl --fail-with-body -sS "$API_URL/tickets/$URGENT_TICKET_ID"
```

**Expected:** version **1.0.0**, and the green-created urgent ticket is still readable. Blue rejects *creating* a new urgent ticket, but can read the stored value. This release deliberately avoids a schema change.

**What just happened:** rollback changed traffic, not data. `rollout undo` is not the relevant operation because neither Deployment changed during the switch. Keep both slots available until verification finishes. A real database migration requires its own backwards-compatibility/rollback design.

## 15. Understand Knative and finish

Stop making preview requests. After the platform's idle window, inspect:

```bash
oc get pods -l serving.knative.dev/service=desk-renderer
oc get deployments
```

Depending on policy/other traffic, the renderer may reach zero Pods. API and PostgreSQL Deployments remain running. Use the stable API URL and your original ticket ID to request another preview:

```bash
curl --fail-with-body -sS "$API_URL/tickets/$TICKET_ID/notification-preview"
```

A cold start may add latency; retry this safe GET after a few seconds if it returns a temporary 503. Do not infer scale-to-zero from a fixed sleep or claim the whole application is serverless.

**You are done when you can explain:** which component built the images, how Tekton gated those builds, why green was initially isolated, which YAML patch promoted/rolled back traffic, and what Knative manages.

If you want to continue, do the [optional failing-test experiment](your-own-release.md#see-a-real-test-rejection) before switching to a fork, then [release your own API change](your-own-release.md). Keep the installation running, stay in this checkout/project, and keep your original terminal open.

When you are finished with all exercises, follow [cleanup](cleanup.md). If you only wanted the prepared walkthrough, you can clean up now.

### Command quick reference

| Command | Why you used it |
| --- | --- |
| `oc project` | Select and verify the target namespace. |
| `oc apply -f` | Create/update a known ordinary YAML definition. |
| `oc process … -o yaml > .local/FILE.yaml` | Fill a Template's visible parameters and keep inspectable output. |
| `oc create -f` | Start a named PipelineRun/Job once. |
| `tkn pipelinerun logs` / `describe` | Inspect execution output, status and image results. |
| `oc wait` / `oc rollout status` | Wait for a specific success/readiness condition. |
| `oc get … -o jsonpath=…` | Read a named result/URL into a variable without a custom script. |
| `oc port-forward` | Reach the isolated green preview from the same terminal environment. |
| `oc patch … --patch-file` | Promote or roll back by changing only the Service selector. |
| `curl` | Verify real API behavior rather than trusting resource status alone. |
