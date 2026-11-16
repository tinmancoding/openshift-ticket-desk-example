# Architecture and rationale

## A credible, deliberately small business workflow

A caller creates a support ticket and later requests a notification preview. Ticket creation commits to PostgreSQL independently of the renderer. If the renderer is unavailable, the preview request returns 503 and the ticket remains durable. A preview GET can be retried; automatically retrying a ticket POST could create duplicates.

The renderer accepts ticket JSON and returns a JSON object containing a notification `subject` and body `text`. It stores nothing and sends no external message. Bursty, stateless HTTP rendering is a plausible Knative workload; a persistent transactional database is not. Production notification delivery would need durable intent/outbox, queueing, idempotency and retries. This example does not pretend that a synchronous call solves those concerns.

### HTTP contract

| API | Behavior |
| --- | --- |
| `POST /tickets` | JSON `title` (required), `description` (optional), `priority` (default `normal`). Returns 201 and a Location header. |
| `GET /tickets` | Latest 50 tickets. No pagination or production tenant isolation. |
| `GET /tickets/{id}` | Stored ticket or 404. |
| `GET /tickets/{id}/notification-preview` | Calls the renderer; returns its preview, or 503 without deleting the ticket. |
| `GET /healthz` | Process liveness; does not depend on PostgreSQL. |
| `GET /readyz` | API checks database connectivity **and the tickets table**. Renderer is independent. |
| `GET /version` | Component identity and source-defined application version. |
| Renderer `POST /render` | Accepts `id`, `title`, `priority`; returns `subject`, `text`, `ticket_id`, `renderer_version`. |

## Tekton plus BuildConfigs: who owns what?

**Tekton owns the workflow.** Its graph has three required Tasks:

1. Download the public GitHub source archive at an exact SHA and run all unit/safety tests.
2. Start the existing Git-source Docker BuildConfig with `--commit=SHA`. Wait for that named Build, reject failures, verify its recorded Git commit, and return its output digest.
3. Start a Task step using that exact image and check its packaged HTTP contract.

The PipelineRun only becomes release-eligible when all three succeed. The API image check deliberately does not claim database integration; that comes from deployed smoke tests. A failed image test can leave a perfectly built image/tag in the registry. That tag is not approval.

**BuildConfigs own image construction.** They define public GitHub source, component `contextDir`, Dockerfile strategy, resource budgets, registry output and serial build execution. There are no binary uploads or privileged image builders inside Tekton. All automatic BuildConfig triggers are disabled so a Git push cannot bypass the source test gate or launch duplicate builds.

The source-test archive and OpenShift Build fetch source separately. Both use the same full commit SHA. A branch name is not adequate: it can move between test and build. Neither fetch reads local unpushed files.

**A digest identifies the artifact.** The build Task reads `.status.output.to.imageDigest` from its exact Build and composes `registry/repository@sha256:…`. It never resolves a later `latest` tag. Promotion reuses that image; it does not rebuild. Mutable Docker base tags and Python transitive dependencies mean the same source SHA can still build different bytes on different days. Pin approved base/tool/database digests and maintain dependency locks for a production adaptation.

## Release ownership and blue/green

The CI ServiceAccount may instantiate only `desk-api` and `desk-renderer`, read Builds/logs and resolve those ImageStreams. It cannot read Secrets, deploy applications, or patch routing. Test Tasks use a separate token-free identity. Ordinary application/database Pods also have no Kubernetes API token. Namespace internal-registry pull permissions still need platform verification.

Both API slots use the same database and renderer URL. The stable `desk-api` Service selects blue initially; `desk-preview` selects green. Promotion changes the stable selector. The preview Service stays on green; rollback selects blue again.

A Service-selector switch is not a distributed transaction. Endpoint changes take time, and existing connections may finish on the old slot. Keep both versions protocol/data compatible. The example release adds `urgent` to accepted priorities without changing the schema. Blue can still **read** an urgent ticket after rollback; it simply rejects new urgent-ticket POSTs. Database writes are not undone by routing rollback.

## Knative's boundary

Knative owns only the renderer's Revision/workload/ingress. Deploying a different renderer digest or changing its template produces a new Revision. Changing the API's blue/green selector does not. The API and PostgreSQL remain ordinary workloads even if the renderer reaches zero Pods.

Cold starts can exceed the API's five-second dependency timeout. The optional developer smoke script retries safe preview GETs for a bounded interval, while reporting unrecoverable failures. The beginner walkthrough explains explicitly when to retry a preview GET instead of silently automating it. Platform policy/traffic may prevent scale-to-zero. Never interpret a fixed sleep or `Ready=True` alone as proof of scale-to-zero or end-to-end reachability.

## Manifest model: native YAML and small Templates

`openshift/` is the canonical, hand-maintained manifest source. Stable resources and the Pipeline graph are plain YAML. A few OpenShift Templates expose only the values that vary: image digest, slot, renderer URL, public GitHub repository or compatible CLI image. `oc process -o yaml` fills them; you inspect/save the ordinary YAML in ignored `.local/` and apply it explicitly. There is no custom deployment/generation CLI or private state ledger.

Prepared PipelineRun files select known published source commits, so the first walkthrough does not require a fork, push credentials or a local development environment. Implementing a new release is a separate follow-up. Source tests and the Git Build still use the same exact commit. Python inside a Task is application test code, not Kubernetes manifest generation.

Fixed `desk-*` names make commands readable. **Native apply/delete does not verify ownership for you.** The learner selects/checks the project, reserves the names, retains the files and inspects existing resources before updates/cleanup. Static labels are inventory aids, not proof of ownership. The previous tool's UID guards do not apply to this new path. Kubernetes/OpenShift/Tekton/Knative controllers still own their generated children; remove known parents, not arbitrary Pods.

The initial network file selects blue. Reapplying it after promotion would restore that selector; later switches deliberately use separate small YAML merge patches. This keeps exactly what changes visible. See the [walkthrough](walkthrough.md) and [cleanup](cleanup.md).
