# Cleanup: remove only your Ticket Desk resources

Run this from the same checkout/project used for all your exercises. Finish any follow-up release or failing-test experiment **before** starting cleanup. Preserve `.local/`: it contains the exact processed manifests, execution files and private Secret copy. If you keep the database disk, you must also keep the matching password file after cleanup.

## 1. Check where you are and whether work is still running

```bash
oc whoami
oc project
oc get pipelineruns.tekton.dev
oc get builds
```

Confirm your own project and **only your own `desk-*` resources**. Names and labels are convenient inventory aids, not proof of ownership. If another person changed/replaced an object, stop and investigate rather than deleting it by name.

Finish work or cancel only the specific active executions first. For example, replacing `RUN_NAME`/`BUILD_NAME` with the names you inspected:

```bash
# Only if cancellation is actually needed; these are example command forms.
# tkn pipelinerun cancel RUN_NAME
# oc cancel-build BUILD_NAME
```

A timed-out/cancelled Tekton Task does **not** necessarily cancel the OpenShift Build it already submitted. Verify terminal Run/Build states before deleting their inputs or identities. Stop any port-forward with Ctrl+C.

## 2. Save evidence before deleting Runs

The main walkthrough used fixed names. Save each Run's status/results/logs if you want to retain them; repeat these two commands with the other actual Run names:

```bash
oc get pipelinerun desk-api-blue-ci -o yaml > .local/api-blue-result.yaml
tkn pipelinerun logs desk-api-blue-ci > .local/api-blue-logs.txt
```

Do not delete/recreate a failed Run just to hide the failure. If you made retry copies with new names, retain and clean those exact named copies too.

## 3. Delete executions first

```bash
oc delete -f openshift/runs/renderer-ci.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f openshift/runs/api-blue-ci.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f openshift/runs/api-green-ci.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f openshift/runs/api-rejected-ci.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f .local/schema-job.yaml --ignore-not-found --wait=true --timeout=180s
```

The optional rejected Run may never have existed; `--ignore-not-found` handles a missing **cluster object**, not a missing local file. If you did not reach the schema step, skip its command.

If you completed **your own API release**, delete that custom Run too:

```bash
oc delete -f .local/my-release-ci.yaml --ignore-not-found --wait=true --timeout=180s
```

If you used the walkthrough's named **renderer or schema Job retry**, delete those executions from their copied files:

```bash
oc delete -f .local/renderer-ci-retry.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f .local/schema-job-retry.yaml --ignore-not-found --wait=true --timeout=180s
```

Skip commands for local files you did not create. Repeat `oc delete -f` for **every other renamed Run or retry Job file** you created, using its actual path. Keep each file until its execution has been deleted and checked.

Tekton may need time to finalize logs/owned Pods. A timeout is a problem to inspect, not permission to strip finalizers.

## 4. Remove application workloads and routing

Only run file commands for stages you actually created:

```bash
oc delete -f .local/renderer.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f .local/api-green.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f .local/api-blue.yaml --ignore-not-found --wait=true --timeout=180s
oc delete -f openshift/03-network.yaml --ignore-not-found
oc delete -f openshift/02-database.yaml --ignore-not-found --wait=true --timeout=180s
```

Deleting the Knative parent removes its generated Revision/workload/ingress through ownership. Deleting Deployments removes their Pods. Do not mass-delete arbitrary Pods or manually remove unfamiliar Knative children.

## 5. Remove recipes and identities

These are the **processed YAML files**, not the Template definitions:

```bash
oc delete -f .local/builds.yaml --ignore-not-found
oc delete -f openshift/ci/pipeline.yaml --ignore-not-found
oc delete -f .local/tasks.yaml --ignore-not-found
oc delete -f openshift/00-identities.yaml --ignore-not-found
```

BuildConfigs normally own their Builds. Inspect any leftovers and owner references before deleting only the named exercise objects. Never use namespace-wide `--all` cleanup, delete the project, or change platform defaults to make the inventory look empty.

## 6. Decide what to do with the data

So far the **PVC and database Secret remain**. This is intentional: you can recreate PostgreSQL using the same password and disk. Do not change the Secret's password while retaining an initialized disk; the database password is not automatically rotated by changing a Kubernetes Secret.

If you deliberately want to erase the example's synthetic tickets too:

```bash
# DESTRUCTIVE: erase the example disk and its password Secret.
oc delete -f openshift/01-storage.yaml --ignore-not-found
oc delete -f .local/database-secret.yaml --ignore-not-found
```

These commands delete **cluster objects**. They do not remove `.local/database-secret.yaml` from your computer.

- **Keeping the disk:** keep that matching local password file private and available for recreating PostgreSQL. Do not copy the example over it on restart.
- **Discarding the data:** after the PVC and cluster Secret have been deleted, you may remove the local Secret copy separately when it is no longer needed. Keep any non-secret evidence you want to retain.

## 7. Verify

```bash
oc get deployment,pod,service,route,pvc,bc,build,is
oc get tasks.tekton.dev,taskruns.tekton.dev,pipelines.tekton.dev,pipelineruns.tekton.dev
oc get services.serving.knative.dev,revisions.serving.knative.dev
```

**Good looks like:** no exercise workloads/Runs/recipes remain. If you kept data, `desk-db` PVC/Secret remain by choice; platform defaults and unrelated work must remain. Shared labels are not automatically copied to every child, so inspect names and owner references instead of trusting a label-only query.

These commands delete named resources in your selected project; they do not verify ownership for you. Check the project and each resource before deleting it, and retain the files used to create it. Never apply this cleanup blindly in a shared namespace.
