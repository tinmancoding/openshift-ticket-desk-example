# Verification record

## Scope and honesty boundary

This record distinguishes local tests, authorized learner09 checks and still-unverified paths. A manifest rendering successfully is not a live application acceptance result. No workshop suite result certifies this standalone repository.

## 2026-11-16 — initial implementation

### Offline

`make check` passes **30 tests**, Python compilation and shell syntax checks. `docker compose config --quiet` passes configuration validation; this does not mean Compose containers were run.

- Application contract tests: create/read/default and supported priorities, validation, malformed JSON/content type/body size, missing records, redacted DB/dependency errors, readiness versus liveness and API/renderer integration.
- Platform/tool safety tests: Git source/context/strategy/no triggers, required Task ordering and split identities, narrow build Role, slot/database separation, immutable-image validation, exact Build/commit/digest extraction, safe archive handling, empty-test rejection, ownership receipts, UID/RV guards and render-only/no-cluster behavior.
- Python syntax and shell syntax checks are part of `make check`.

The application unit tests use a memory repository double. They do not claim PostgreSQL durability. Direct dependencies are pinned, but transitive dependencies/base image tags remain mutable.

### Authorized OKD checks — learner09 only

Used the existing private learner09 kubeconfig; actual `oc whoami` and namespace both `learner09`. The namespace initially had no workload Pods. No platform installation, cluster-wide policy/quota change, instructor credential fallback, other learner change or terminal restart occurred.

1. Rendered foundation definitions and submitted server dry-run. All objects except the RoleBinding passed in the combined dry-run; RoleBinding lookup failed because a dry-run Role is not persisted. Normal ordered creation then succeeded with the exact narrow Role/RoleBinding—no permission widening.
2. Created the ownership-tracked foundation: private DB Secret, three ServiceAccounts, database PVC/Deployment/Service, two Git BuildConfigs/ImageStreams, narrow Role/RoleBinding, three Tasks and Pipeline.
3. Actual PostgreSQL image `quay.io/sclorg/postgresql-16-c9s:latest` started under namespace policy; its gp3-csi 1-GiB PVC Bound and database became Ready.
4. Ran real PostgreSQL integration over a learner-scoped port-forward. Application/renderer HTTP processes ran **on the local workstation**, not as OpenShift application images. Actual repository code initialized the schema, created/read a row, verified it through SQL, rendered its preview over HTTP, observed 503 on renderer outage and confirmed the ticket remained stored.
5. Restarted only the example database Deployment. A second integration run read the earlier row from the same PVC, repeated HTTP/SQL/outage checks and removed its synthetic test rows. This is evidence of persistence across that Pod replacement, not HA/backup certification.
6. Re-ran setup against its owned resources: it preserved the database password and Pod UID; no duplicate image builds started. Explicit non-root/drop-capabilities/seccomp settings were subsequently applied and the database/HTTP integration passed again.
7. Server dry-run accepted both API slot definitions, schema Job, stable/preview Services, edge Route and Knative Service. Dummy digest references were used only for admission checking; none of these application workloads were persisted or run.
8. Ran a deliberately **pre-publication negative PipelineRun** against the repository's existing initial commit `0573bf9c4e01e1b4bb671db79c2644b933e52ad8`. The real token-free source Task fetched that exact GitHub archive, then failed because the initial commit has no `requirements-test.txt`. PipelineRuns `desk-ci-gbh2c` and `desk-ci-g9f7h` correctly failed and skipped build/image Tasks; **no OpenShift Build was created**. The second attempt also verified the oc-based log archival fallback when tkn is absent. This proves runtime source-gate rejection, not a passing application pipeline.

Private/ignored evidence: `build/setup*.log`, `build/postgres-{first,after-restart,security-final}.log`, `.state/desk-ci-{gbh2c,g9f7h}/` and namespace ownership state. No credentials are included in this document.

**Cleanup passed:** the CLI's UID-precondition cleanup removed both Runs, owned definitions/identities, database workload, Secret and PVC. A final metadata-only audit of **22 resource kinds** found no `desk-*`/owner-label residue and zero workload Pods in learner09. Platform defaults were retained; no port-forward or local HTTP server remains. Evidence: `build/cleanup.log`, `build/cleanup-audit.json`.

### Not yet verified

The implementation has not been committed/pushed to GitHub. Consequently the cluster cannot fetch these new application/Task/test files as Git source. The following are **not claimed as passed**:

- successful complete source-test → Git BuildConfig → built-image-test PipelineRuns for the new components;
- actual application image compatibility/registry pull behavior;
- image-backed schema Job, API blue/green slots, ingress and full in-cluster API → Knative renderer calls;
- source v1.1.0 priority release, promotion, rollback and cross-version persistence;
- actual renderer Revision/scale-to-zero/wake-up behavior;
- Docker Compose runtime (not exercised merely by unit tests).

Publication of a reviewed implementation commit is the next dependency for complete Git-source acceptance. Do not substitute a binary upload, a different repository or a locally mocked build and call it that acceptance.
