# Operations and limitations

Start with the [walkthrough](walkthrough.md), then use the dedicated [cleanup guide](cleanup.md). This page is reference material, not another prerequisite command sequence.

## File and ownership safety

- Work only in your own isolated project; check `oc whoami` and `oc project` first.
- Reserve `desk-*` names. `oc apply` can change an existing same-named object; it does not prove you own it. Static labels are not ownership receipts.
- `openshift/` contains plain manifests, Templates, executions and patches. **Never apply it recursively.** Use the exact command/file pair from the walkthrough.
- Keep processed YAML and the password Secret in ignored `.local/`; keep the Secret file mode 0600 and do not print/share it. Do not change the database password while retaining an initialized disk.
- For retry executions, copy the Run into `.local/`, choose a new unused name and retain the failed attempt's evidence. Do not use `apply` to pretend a finished Run started again.
- No custom deployment state, UID-protection CLI or automatic release approval exists in the new native path. You must inspect names, project, success conditions and candidate behavior before acting. Historical `.state/` evidence from the retired tooling is private and ignored; it is not needed for this walkthrough.

## Credentials and permissions

The build Role allows named BuildConfig instantiation, Build metadata/log reads and the two output ImageStream reads. It cannot deploy or patch traffic, read Secrets, grant roles or change SCCs. Logs/Build metadata are readable across the namespace, so use isolation. Test/application identities disable API token automount. OpenShift's separate build identity performs image pushes, and platform-provided image pull permissions must work for Tekton/Knative.

For the prepared path, source is public and no Git credential is required. Fork/private-source authentication is a separate topic. Never embed tokens into URLs, Run parameters, YAML or recorded output.

## Troubleshooting

| Symptom | Inspect / recover |
| --- | --- |
| Wrong account/project | `oc whoami`, `oc project`; stop before applying anything. Do not use instructor credentials as a fallback. |
| Template still contains `${API_IMAGE}` | Process the Template with the required parameter first; inspect the resulting YAML. Do not apply the Template as though it were a Deployment. |
| Template parameter is required | Supply the successful image result/actual URL. An empty variable is not success. |
| Role/RoleBinding denied | Ask the platform owner to review the narrow rules; do not add `edit` or cluster-admin. |
| Secret changed but database rejects password | Retaining an initialized disk does not rotate its internal password. Recover the original matching password; do not blindly recreate credentials. |
| Run says `AlreadyExists` | Inspect the existing execution. For a deliberate retry, use a new name in a copied file and in log/wait/result commands. |
| PipelineRun Failed | `tkn pipelinerun describe NAME` and `logs NAME`. Check which Task failed; do not deploy its image. Waiting longer will not fix failed tests. |
| Source fetch/install fails | Public repository/full pushed SHA, GitHub/PyPI egress and Task logs. Prepared files use specific published snapshots. |
| Build fails | Exact Build logs, source revision/contextDir, Dockerfile/base/package access and strategy admission. |
| Task timeout but Build still running | Inspect/cancel that exact Build separately before deleting inputs or the workflow identity. |
| Image test cannot pull | Internal registry reference and namespace image pull permissions; not a reason to grant a privileged SCC. |
| Database Pod Pending | PVC/storage class, quota, database image compatibility and events. |
| API readiness fails | Schema Job completion, DB settings and PostgreSQL readiness/logs. |
| Preview returns 503 | Knative readiness/URL reachability, cold start or invalid dependency response. Retry a safe preview GET; do not retry ticket POSTs automatically. |
| Green accidentally gets production traffic | Stable Service selector; initial `03-network.yaml` selects blue and should not be reapplied casually. Use the explicit patch files. |
| Version briefly old after switching | Endpoint convergence/existing connections. Inspect Service/EndpointSlices; retry a GET after convergence. Keep both slots ready. |
| Cleanup wait times out | Active Runs/Builds and finalizers; preserve evidence. Do not strip platform finalizers or delete unrelated Pods. |

The Task Template's default CLI image is a previously tested OKD 4.21 digest. For another platform, the instructor should supply a compatible approved `CLI_IMAGE` to `oc process`. Python/PostgreSQL tags and Docker base tags are development defaults; pin/maintain approved digests and dependency locks for production.

## Production gaps (intentional)

- No user authentication/authorization, tenant separation, audit trail, anti-abuse controls or rate limiting. **Synthetic data only.** Public API/Knative ingress is not suitable for confidential tickets.
- One PostgreSQL instance/PVC; no certified backups, HA, recovery or migration framework. Application and initial-schema Job share a DB account for simplicity. Internal DB TLS/network isolation is not established here.
- No durable email delivery. Add an outbox/queue/idempotent worker rather than turning a preview call into an unreliable side effect.
- No ticket POST idempotency key, pagination beyond a bounded recent list, connection pooling or load-test claim.
- No webhook installation, PR trust isolation, protected approval service, signed provenance, scanning or enforced organization policy. Only run trusted commits in this demonstration.
- Direct dependency pins and mutable image tags are not a full lock or security certification.
- Blue/green switches traffic, not data. Schema compatibility, connection draining and external side effects need their own strategy. Traffic rollback does not reverse database writes.

## Maintainer checks

Run `make check` after changes. Tests parse canonical YAML, verify recipe/identity/selector/commit relationships and compare embedded Task scripts with `deploy/` application-test/build scripts. Python is used for offline tests, **not** to generate or modify deployment manifests. Keep the two script views in sync when deliberately changing Task implementation; a regression test fails if they diverge.

Rehearse changed native commands/manifests on an explicitly authorized test namespace. Record exact source commits, manifest hashes, outcomes and cleanup in `VERIFICATION.md`; old custom-CLI results do not certify the new path. Never make an offline test apply a cluster resource automatically.
