# Verification record

## Scope and honesty boundary

This record distinguishes local tests, authorized learner09 checks and still-unverified paths. A manifest rendering successfully is not a live application acceptance result. No workshop suite result certifies this standalone repository.

## 2026-11-16 — initial implementation, before publication (historical)

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

### Limits at that checkpoint

At this pre-publication checkpoint, the implementation was not yet committed/pushed to GitHub. The following were **not claimed as passed** then; the subsequent Git-source acceptance below supersedes the applicable limits:

- successful complete source-test → Git BuildConfig → built-image-test PipelineRuns for the new components;
- actual application image compatibility/registry pull behavior;
- image-backed schema Job, API blue/green slots, ingress and full in-cluster API → Knative renderer calls;
- source v1.1.0 priority release, promotion, rollback and cross-version persistence;
- actual renderer Revision/scale-to-zero/wake-up behavior;
- Docker Compose runtime (not exercised merely by unit tests).

Publication was required for complete Git-source acceptance. No binary upload, different repository or locally mocked build was substituted.

## 2026-11-16 — published Git-source acceptance

**Result: the documented baseline → rejected contract → green preview → promotion → rollback lifecycle passed on OKD using learner09.** This is observed single-user acceptance, not a production readiness, concurrency, availability or security certification. No executable fixes or permission widening were needed during this phase.

### Published source and required CI

| Source | Purpose | PipelineRun | Observed outcome |
| --- | --- | --- | --- |
| `9865bcd86d11c41a63270d52bcfe04666357b2f5` | Baseline renderer 1.0.0 | `desk-ci-9bnlq` | Source tests, Git BuildConfig `desk-renderer-1`, image checks: all passed. |
| `9865bcd86d11c41a63270d52bcfe04666357b2f5` | Baseline API 1.0.0 | `desk-ci-489k7` | Source tests, Git BuildConfig `desk-api-1`, image checks: all passed. |
| `348652941ff39a62785f656612a8970b4e55eb49` | Urgent-ticket test **before** implementation | `desk-ci-5vnsh` | Expected rejection: real test received 400 instead of 201; build/image Tasks skipped. Build inventory unchanged. |
| `e88bfa8912e6123f86ad7b7864f9f64b8433a125` | API 1.1.0 implementing urgent tickets | `desk-ci-j4bsr` | Source tests, Git BuildConfig `desk-api-2`, image checks: all passed. |

The baseline required **30 tests**; the feature required **31 tests** including the previously failing urgent contract. The feature is published on `feature/urgent-tickets`. Its history retains the red contract commit and passing implementation. `main` remains the 1.0.0 starting point. Subsequent verification/navigation documentation does not change the tested executable content; these exact SHAs remain the build evidence, not a claim that a later documentation commit was rebuilt.

All positive builds used public GitHub source and the exact supplied SHA. The CLI checked whole-Run success, the named Build's Complete phase/recorded commit and a full immutable image reference. Actual built-image Tasks pulled those digests under the token-free test identity. Outputs were:

| Artifact | SHA256 image digest |
| --- | --- |
| Renderer 1.0.0 | `941d4d1ae200540e223aeec24471c12541e0eb82b06f79c2983d0d33eb6f84f7` |
| API blue 1.0.0 | `7686946126435ef2c154653f5b7a918e878f9adee070d59eacc120ac7b4cb758` |
| API green 1.1.0 | `d1f9916f068ef2f8d2e58ffa1b60710521be2ac47adf827ba3be8c828ed41c3e` |

These were registry repositories under `image-registry.openshift-image-registry.svc:5000/learner09/desk-{api,renderer}`. The acceptance installation and its ImageStreams have since been removed; digests identify observed artifacts, not a promise of permanent registry retention.

### Deployed application and release checks

- The **image-backed schema Job** completed and initialized the real PostgreSQL table.
- The built renderer became Knative Ready as Revision `desk-renderer-00001`; the built API blue slot rolled out and its edge-TLS Route worked with normal certificate verification.
- Blue reported **1.0.0**, created/read ticket 1 and obtained its preview through an actual **in-cluster API → Knative renderer** call.
- Green used its own tested digest, reported **1.1.0** through the preview Service, read blue's ticket 1 and created urgent ticket 2 with a matching renderer preview. The production URL still reported blue 1.0.0.
- Explicit Service-selector promotion to green converged; production smoke created urgent ticket 3, read the original ticket and passed its preview checks.
- Explicit selector rollback to blue converged; production smoke created normal ticket 4 and read the original ticket. Blue could also read green-created urgent ticket 2, while a **new** urgent POST was correctly rejected with 400. No image rebuild or schema change occurred during promotion/rollback.
- The renderer Revision remained `desk-renderer-00001` throughout the API release: backend/API routing changes did not create a Knative Revision.
- After traffic stopped, metadata polling observed the renderer reach **zero Pods**. The next preview request woke the same Revision and returned 200. The observed request took about **1.25 seconds**; this is one measurement, not a startup SLA. API/PostgreSQL remained ordinary Deployments.
- A separate owned Job using the **actual `desk-builder` ServiceAccount** verified denials for Deployment/Service patching, Secret reads, RoleBinding/ClusterRoleBinding creation and Pod reads in the default namespace. It did not impersonate another account, attempt actual forbidden mutations or grant new permissions.

### Cleanup and evidence

**Full cleanup passed.** The ownership/UID-precondition CLI removed current Runs, schema/authorization Jobs, Knative parent, API slots, routing, PostgreSQL, BuildConfigs/ImageStreams, Tasks/Pipeline, narrow namespace RBAC, identities, Secret and PVC. A final metadata-only audit of **26 resource kinds**, including EndpointSlices and Knative internal autoscaling/networking parents, found no `desk-*`/owner-label residue and zero workload Pods. Default platform resources were retained. No other learner, terminal, operator, quota or infrastructure-management operation was changed.

Ignored/private evidence includes:

- `.state/desk-ci-{9bnlq,489k7,5vnsh,j4bsr}/{run.json,logs.txt,build.json}` (Build JSON only for successful runs);
- `build/{renderer,api-blue,api-green}-ci.log`, deployment/schema logs and before/after rejected-build inventories;
- `build/{blue,green-preview,production-green,production-blue}-smoke.log`;
- `build/release-acceptance.json`, `build/knative-idle-wake.json`, `build/builder-permissions.log`;
- `build/published-cleanup.log`, `build/published-cleanup-audit.json`.

Private state/logs are not published; no credentials are included here. Expected failures remain archived separately rather than being erased or counted as successful application builds.

### Remaining boundaries

Docker Compose configuration was validated, but **Compose runtime was not exercised**. No multi-user load, HA, backups/restores, real email delivery, production authentication, database migration compatibility beyond this no-schema-change release, webhook integration or cross-cluster/image reproducibility claim is made. Mutable base/tool/database images and transitive dependencies still require an approved pin/lock/update policy for production use.
