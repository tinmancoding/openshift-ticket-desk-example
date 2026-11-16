# OpenShift Ticket Desk

A standalone, hands-on example of **Tekton orchestrating Git-source OpenShift BuildConfigs**, followed by an explicit **blue/green API release** and a **Knative notification-preview service**.

This is an educational application, not a production ticketing system. It has no authentication: use synthetic data in an isolated namespace. It does not depend on workshop materials, install cluster operators, grant privileged SCCs, or deploy anything just because you run tests.

## What you will build

- **Ticket API:** create/read tickets backed by PostgreSQL; request a plain-text notification preview.
- **Notification renderer:** stateless HTTP service, independently built and deployed with Knative Serving. It generates a preview; it does **not** send email.
- **PostgreSQL:** persistent ticket storage shared by blue and green API slots.
- **CI pipeline:** test a GitHub commit → start its Git-source BuildConfig → inspect that Build → test the resulting image → record its immutable digest.
- **Release procedure:** deploy a candidate digest, verify it, change the stable Service selector, and verify rollback without rebuilding images.

```text
GitHub commit ──► Tekton source tests ──► BuildConfig at the SAME commit
                                                │
                                                ▼
                                OpenShift Build → registry digest
                                                │
                                                ▼
                                      built-image contract tests
                                                │
                                 successful Run + image evidence
                                                │
                                   explicit human deployment gate
                                                ▼
client → stable Service → API blue / green → PostgreSQL (shared)
                                  │
                                  └→ Knative renderer → notification preview
```

**The division of responsibility matters:** BuildConfigs build images; Tekton coordinates and validates; a separate human-authorized operation deploys/promotes. The pipeline identity cannot change production routing.

## Start here

1. Read [the architecture and design decisions](docs/architecture.md).
2. Run offline tests or [start the application locally](docs/local-development.md).
3. Follow [the complete OpenShift release walkthrough](docs/walkthrough.md).
4. Read [operations, cleanup and production limitations](docs/operations.md).
5. Check [what has actually been verified](VERIFICATION.md) before treating a path as tested.

```bash
make setup
make check
```

These commands do not authenticate to or mutate a cluster. The opt-in HTTP smoke test creates a synthetic ticket only when explicitly requested.

## Baseline and reference release

| Branch | Purpose |
| --- | --- |
| `main` | API **1.0.0** baseline and the complete walkthrough. Start here to implement the release yourself. |
| `feature/urgent-tickets` | API **1.1.0** reference solution. Its history first adds the failing urgent-ticket contract, then implements it. |

The full Git-source CI, candidate preview, promotion, rollback, cross-version persistence and Knative idle/wake path have been exercised on OKD with a namespace-scoped learner account. The exact commits, image digests, expected failure and cleanup evidence are recorded in [VERIFICATION.md](VERIFICATION.md). This is example acceptance, not production certification.

Use a **new branch name** for your own exercise; do not overwrite the published reference branch. Main's offline suite has 30 tests; the reference release has 31.

## Repository map

| Path | Contents |
| --- | --- |
| `apps/api/` | Flask API, PostgreSQL repository and Dockerfile. |
| `apps/renderer/` | Stateless notification renderer and Dockerfile. |
| `deploy/` | Source-test, build and built-image test scripts embedded into Tekton Tasks. |
| `scripts/resources.py` | Readable render-only definitions for OpenShift/Kubernetes/Tekton/Knative resources. |
| `scripts/desk.py` | Explicit setup, CI, schema, slot, promotion, status and UID-safe cleanup commands. |
| `scripts/smoke.py` | End-to-end HTTP acceptance against a chosen API URL. |
| `tests/` | Application contracts and offline orchestration/safety regressions. |
| `compose.yaml` | Local development with a real PostgreSQL database. |
| `docs/` | Architecture, local development, release walkthrough and operational boundaries. |
| `PLAN.md` | Implementation scope and acceptance plan. |
| `.state/` | Ignored private state: database password, ownership/UID receipts and execution evidence. Never commit or share. |

Manifests are rendered as Kubernetes-compatible **JSON**, not maintained in a second YAML copy. `render` only prints definitions; it creates neither Secrets nor cluster resources. GitHub source must contain your implementation before a Git-source build can fetch it; uncommitted/unpushed local code is not an alternative source transport.
