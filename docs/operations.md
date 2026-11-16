# Operations, safety and limitations

## Ownership and permissions

All generated names start with `desk-`. Each installation has a random `ticket-desk.example/owner` label and an ignored private UID ledger. Setup refuses existing names it cannot prove it owns. Updates use JSON Patch tests on UID/resourceVersion; cleanup sends API DeleteOptions with UID preconditions. A matching label alone never authorizes changing/deleting a replaced object.

Use one installation per namespace and do not run simultaneous setup/build/promotion/cleanup commands. Local state writes are atomic but not a multi-user coordination service. The state directory is mode 0700; namespace state is mode 0600 and contains the database password. It is ignored by Git. Never commit it, include it in a container context, copy it to an issue, or print it in a terminal recording. Generated definitions contain Secret **references**, not values. Setup preserves an existing matching Secret; password rotation is intentionally not a setup side effect.

The build Role is namespace-only and permits named BuildConfig instantiation and build metadata/log access. Build metadata/logs are readable across that namespace, so isolation still matters. No production mutation, Secret read, SCC privilege, cluster-admin binding or operator installation is required. Test/application identities have API-token automount disabled. OpenShift's separate build identity performs registry pushes; platform-provided internal pull bindings must work for Tekton/Knative.

The current kubeconfig is used as-is. Every cluster command supplies `-n`; the tool does not switch project, read instructor credentials or escalate on failures. A private kubeconfig path can be supplied through `KUBECONFIG` using your normal secure process.

## Cleanup

From the same checkout/state used for installation:

```bash
export DESK_NAMESPACE=YOUR-NAMESPACE
export DESK_IDENTITY=YOUR-USER
desk() { python3 scripts/desk.py --confirm "$DESK_NAMESPACE" "$@"; }
desk status
oc get pipelineruns.tekton.dev,builds -n "$DESK_NAMESPACE"
```

Do not delete identities or source definitions while executions are active. A cancelled/timed-out PipelineRun can leave an independent OpenShift Build running. Inspect the exact Run and named Build first. If cancellation is needed, use your reviewed platform procedure (`tkn pipelinerun cancel RUN` and `oc cancel-build BUILD`) on only those named example executions, then wait for terminal conditions. Cleanup refuses active owned Runs/Builds.

```bash
# Remove owned runs, workload parents, routing, build recipes, Tasks and identities.
# Retain the example's database PVC and Secret for deliberate recovery.
desk cleanup

# DESTRUCTIVE alternative: also erase this example's PostgreSQL PVC and Secret.
# Use this only after explicitly deciding to discard its synthetic data.
desk cleanup --delete-data
```

Cleanup archives are not erased. Run Pods/finalizers, Builds and Knative generated resources should disappear through their parent ownership. The CLI waits for each owned parent's foreground deletion, rather than deleting arbitrary child Pods or using namespace-wide `--all` commands. A cleanup timeout is a failure to investigate, not permission to strip finalizers or force-delete platform resources.

Verify afterwards:

```bash
oc get pods,pvc,deployments,services,routes,buildconfigs,builds,imagestreams -n "$DESK_NAMESPACE"
oc get pipelineruns.tekton.dev,taskruns.tekton.dev,tasks.tekton.dev,pipelines.tekton.dev -n "$DESK_NAMESPACE"
oc get services.serving.knative.dev,revisions.serving.knative.dev -n "$DESK_NAMESPACE"
```

Without `--delete-data`, a retained `desk-db` PVC/Secret is expected; no running database remains. Re-running setup with the same private state can recreate its deleted owned resources and reattach the data. With `--delete-data`, discard/reinitialize database expectations; historical ticket IDs no longer imply existing data. If state is lost, do not relabel/adopt resources blindly—ask the owner to inspect exact UIDs and recover deliberately.

## Troubleshooting

| Symptom | Inspect |
| --- | --- |
| Wrong identity/project | `oc whoami`, explicit namespace and KUBECONFIG. Never fall back to an instructor identity. |
| Role/RoleBinding denied | Review the narrow rules with the platform owner. A server dry-run of a RoleBinding can fail if its referenced dry-run Role was never persisted. This is not permission to grant `edit`. |
| Source Task cannot fetch/install | Public HTTPS repository, **pushed full SHA**, GitHub/PyPI egress, source/archive structure and Python Task logs. |
| No tests discovered | Source gate fails intentionally rather than approving an empty test suite. |
| Build fails after source tests | Build logs, exact Git revision/contextDir, Dockerfile/base registry/package access and strategy admission. |
| CI timeout with a live Build | Inspect/cancel that exact Build separately. Do not assume Task cancellation killed it. |
| Image check cannot pull | Internal registry route/reference and namespace pull permissions. Do not add a privileged SCC. |
| Database Pending / no ready Pod | PVC binding/storage class, quota, database events/image compatibility and Secret references. |
| API readiness fails | Explicit schema initialization, PostgreSQL status, DB settings and application logs. |
| Preview returns 503 | Knative readiness/URL reachability, cold start, five-second API dependency timeout and response contract. The ticket should still exist. |
| Promotion refused | Current-generation target Deployment availability, owner/UID receipts. Still perform end-to-end candidate checks before retry. |
| Version briefly wrong after switch | EndpointSlice convergence and existing connections. Keep both slots ready; do not rebuild to solve routing. |
| Cleanup blocked | Active Runs/Builds, finalizers and exact owner references. Preserve evidence; do not force-delete unfamiliar objects. |

## Production gaps (intentional)

- No user authentication/authorization, tenant separation, audit trail, anti-abuse controls or rate limiting. **Synthetic data only.** Public API/Knative ingress is not suitable for confidential tickets.
- One PostgreSQL instance/PVC; no certified backups, HA, recovery or migration framework. Application and initial-schema command share a DB account for simplicity. Internal DB TLS/network isolation is not established by this example.
- No durable email delivery. Add an outbox/queue/idempotent worker rather than turning the preview call into an unreliable side effect.
- No ticket POST idempotency key, pagination beyond the bounded recent list, pooling or load-test claim.
- No webhook/TriggerTemplate installation, PR trust isolation, protected approval service, signed provenance, scanning or enforced organization policy. Source tests execute repository code; only build trusted commits in this demonstration.
- Direct dependency pins and mutable base/tool/database tags are not a full dependency lock or vulnerability certification. Pin verified digests, lock transitive dependencies and maintain upgrades for real use.
- Blue/green switches traffic, not data. Schema compatibility, connection draining and external side effects need a deployment-specific strategy. Never claim traffic rollback reverses database writes.

## Maintainer checks

Run `make check` after changes; platform tests must stay synchronized with definitions/scripts. Re-render and review manifests whenever RBAC, Task source, image handling, ports, selectors or ownership changes. Re-run affected live acceptance after a pushed source change. Keep failed attempts and source hashes; distinguish offline validation, live negative tests, actual successful image builds and complete release rehearsals in `VERIFICATION.md`.
