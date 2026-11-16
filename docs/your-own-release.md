# Follow-up: release your own API change

Complete the [prepared walkthrough](walkthrough.md) first. This follow-up changes application code, pushes it to your own public GitHub fork, and releases that exact commit. It does not create a GitHub Releases entry.

## Keep the prepared installation and checkout

Continue **before cleanup**, using the same repository directory, project and original terminal. Keep `.local/`: it contains your password and processed manifests. The database, renderer and both API slots should still exist, with production rolled back to blue.

You will reuse the original terminal's `API_URL`, `RENDERER_URL` and `TICKET_ID` variables. If you already cleaned up, return to the prepared walkthrough and recreate the installation first. If you kept the database disk, follow its retained-password instructions rather than choosing a new password.

Check the installation and wait for any active executions to finish:

```bash
oc whoami
oc project
oc get pipelineruns.tekton.dev
oc get builds
oc describe service desk-api
```

**Check:** your assigned identity/project, no active Runs/Builds, and the stable Service selecting blue. Do not update build/Task definitions while Runs are active.

If your original terminal is still open, keep its variables and skip the recovery block below. If it was closed but the installation is still running, restore the URL variables in a terminal opened in the **same checkout and project**:

```bash
RENDERER_URL=$(oc get services.serving.knative.dev desk-renderer -o jsonpath='{.status.url}')
API_HOST=$(oc get route desk-api -o jsonpath='{.spec.host}')
API_URL="https://$API_HOST"
curl --fail-with-body -sS "$API_URL/tickets"
```

Choose the actual ID of your earlier normal-priority ticket from that response and set `TICKET_ID` again. Do not create a duplicate just to recover an ID:

```bash
TICKET_ID=1  # replace 1 with your earlier ticket's actual ID
```

Once the variables are available, verify the running API:

```bash
curl --fail-with-body -sS "$API_URL/version"
```

**Expected:** version **1.0.0**, because the prepared walkthrough ended by rolling production back to blue.

## Add your fork to this checkout

Create a public fork in GitHub, keeping the repository name `openshift-ticket-desk-example`. **Do not clone it into a second directory.** Add it as a separate remote named `my-fork` in this existing checkout:

```bash
# Inspect the existing branch, local changes and remotes first.
git branch --show-current
git status --short
git remote -v

# Replace YOUR_ACCOUNT with the GitHub account that owns your fork.
git remote add my-fork https://github.com/YOUR_ACCOUNT/openshift-ticket-desk-example.git
git remote -v
```

**Good looks like:** the source is still API **1.0.0 on `main`**, and `my-fork` points to your repository. `origin` can stay pointed at the original repository; later push commands explicitly use `my-fork`. If that remote name already exists, inspect its URL instead of adding it again. Stop if there are unexpected local edits; preserve them before switching branches.

Use the organization's approved Git authentication method. Git needs your own author identity and permission to push to your fork. Never put a token/password in a Git URL or YAML parameter. This example uses public HTTPS source; private repositories need a separate credential design.

## Point both source readers at your fork

With no active Runs/Builds, reprocess both Templates using the **same repository parameter**. This updates the existing build recipes and source-test Tasks; it does not replace the renderer or change production routing.

```bash
# Use owner/repository, not a URL. Replace YOUR_ACCOUNT in BOTH commands.
oc process -f openshift/templates/builds.yaml \
  -p GITHUB_REPOSITORY=YOUR_ACCOUNT/openshift-ticket-desk-example \
  -o yaml > .local/builds.yaml
```

Inspect `.local/builds.yaml`: both Git URLs should point to your fork. Then apply it:

```bash
oc apply -f .local/builds.yaml

oc process -f openshift/templates/tasks.yaml \
  -p GITHUB_REPOSITORY=YOUR_ACCOUNT/openshift-ticket-desk-example \
  -o yaml > .local/tasks.yaml
```

Inspect `.local/tasks.yaml`: the source Task's archive URL should point to that same fork. Then apply it:

```bash
oc apply -f .local/tasks.yaml
```

Both source tests and the Build must fetch the same repository/commit. Local unpushed changes are invisible to both. Keep these processed files for cleanup.

## Implement the priority release yourself

Start from API **1.0.0 on `main`**, not the already-completed reference branch:

```bash
git switch -c feature/my-urgent-tickets
```

In `apps/api/ticket_api/__init__.py`, change:

```python
VERSION = "1.0.0"
PRIORITIES = {"normal", "high"}
```

to:

```python
VERSION = "1.1.0"
PRIORITIES = {"normal", "high", "urgent"}
```

Add this method to `ApiTests` in `tests/test_apps.py`:

```python
    def test_urgent_ticket(self):
        response = self.client.post('/tickets', json={'title': 'System unavailable', 'priority': 'urgent'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['priority'], 'urgent')
```

### Optional local checks

If **Python 3.12+ and Make** are installed, run the local checks:

```bash
make setup
make check
```

If those tools are unavailable, skip this optional block. The required Tekton source tests will still run before the cluster builds your image.

### Review and publish the source

Whether or not you ran the optional checks, review the change and push it to **your fork**:

```bash
git diff --check
git diff
git add apps/api/ticket_api/__init__.py tests/test_apps.py
git commit -m "Support urgent tickets without changing the schema"
git push -u my-fork feature/my-urgent-tickets
git rev-parse HEAD
```

Copy the **full SHA** printed by `git rev-parse HEAD`. It must be pushed before the cluster can fetch it. A branch name is not enough: it can move between testing and building.

## Start a Run for that exact commit

```bash
cp openshift/runs/api-green-ci.yaml .local/my-release-ci.yaml
```

Edit the copy in your editor:

- change `metadata.name` to the unused name `desk-my-release-ci`;
- keep the `component` parameter value `api`;
- replace the `revision` parameter's value with your **pushed full commit SHA**.

```bash
oc create -f .local/my-release-ci.yaml
tkn pipelinerun logs desk-my-release-ci -f
oc wait pipelinerun/desk-my-release-ci --for=condition=Succeeded --timeout=35m
```

If the Run fails, stop and inspect its logs. If its name already exists, use the [named retry procedure](walkthrough.md#6-build-and-test-the-renderer) with a new copied file/name. Keep every execution file for cleanup.

Only after whole-Run success, read and inspect its image result:

```bash
API_GREEN_IMAGE=$(oc get pipelinerun desk-my-release-ci -o jsonpath='{.status.results[?(@.name=="image")].value}')
printf '%s\n' "$API_GREEN_IMAGE"
```

**Expected:** a nonempty full image reference containing `@sha256:` and the digest. Do not select `latest` or treat an earlier Run as approval for this source revision.

## Update green, preview it and decide whether to promote

Production should still be blue. This command replaces the **green candidate's** saved manifest with your new tested image:

```bash
oc process -f openshift/templates/api-slot.yaml \
  -p SLOT=green -p API_IMAGE="$API_GREEN_IMAGE" -p RENDERER_URL="$RENDERER_URL" \
  -o yaml > .local/api-green.yaml
```

Inspect `.local/api-green.yaml`. Check `desk-api-green`, `slot: green`, your new image digest and the existing renderer URL. Then apply and wait:

```bash
oc apply -f .local/api-green.yaml
oc rollout status deployment/desk-api-green --timeout=300s
curl --fail-with-body -sS "$API_URL/version"
```

Expect production **1.0.0**. Repeat [green preview checks](walkthrough.md#13-test-green-through-the-preview-service), then the [explicit promotion and rollback](walkthrough.md#14-promote-green-then-roll-back) if you accept the results. Record the actual ticket IDs returned by your new requests; earlier examples' IDs may already be in use.

The renderer is unchanged, so no renderer rebuild is needed. When you finish, follow [cleanup](cleanup.md), including **`.local/my-release-ci.yaml` and every retry Run/Job file** you created.

## See a real test rejection

This separate experiment requires no fork or code edit. **Do it during the prepared walkthrough, before changing the build/Task Templates to your fork.** If you already switched to a fork, use your own pushed failing-test commit instead; the fork may not contain the prepared rejection SHA. Do not change definitions under active Runs.

```bash
oc create -f openshift/runs/api-rejected-ci.yaml
tkn pipelinerun logs desk-api-rejected-ci -f
tkn pipelinerun describe desk-api-rejected-ci
oc get builds
```

**Expected:** the urgent-ticket test receives **400 instead of 201**. This published commit adds the test before implementing the feature. The PipelineRun is **Failed**, build/image Tasks are skipped, and no new OpenShift Build is created. Keep the failed Run and its logs as evidence. Do not wait for an intentionally failing Run to become green.

The published `feature/urgent-tickets` history contains both that failing test and the passing implementation. It is a reference solution, not a branch to overwrite with your own exercise. When all exercises are finished, return to [cleanup](cleanup.md).
