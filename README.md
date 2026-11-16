# OpenShift Ticket Desk

A small support-ticket application for learning **BuildConfigs, Tekton, blue/green deployment and Knative** together.

**Start with the [step-by-step walkthrough](docs/walkthrough.md).** You apply readable YAML and fill a few OpenShift Template parameters using ordinary `oc` commands. No custom deployment CLI, Python manifest generator, GitHub fork or local Python installation is required for that first pass.

## The application

- **Ticket API:** create/read tickets stored in PostgreSQL.
- **Notification renderer:** a stateless Knative HTTP service that produces a preview. It sends no real email.
- **Blue and green:** API 1.0.0 and 1.1.0 share the same database; green adds urgent ticket priority.

```text
GitHub source -> Tekton tests -> Git-source BuildConfig -> tested image

client -> stable Service -> blue OR green API -> PostgreSQL
                                  |
                                  +-> Knative notification renderer
```

Tekton coordinates tests/builds. BuildConfigs construct images. You explicitly deploy a successful Run's digest and decide when a YAML Service-selector patch should promote or roll back traffic. The pipeline identity cannot make that decision for you.

## Pick your next step

| I want to… | Read this |
| --- | --- |
| Run the complete prepared example | [Beginner walkthrough](docs/walkthrough.md) |
| Remove my example resources safely | [Cleanup](docs/cleanup.md) |
| Make and publish my own application change | [Your own release](docs/your-own-release.md) |
| Understand the design in more depth | [Architecture](docs/architecture.md) |
| Develop/test the Python applications locally | [Local development](docs/local-development.md) |
| Troubleshoot or assess production gaps | [Operations and limitations](docs/operations.md) |
| See exact observed verification, not assumptions | [Verification record](VERIFICATION.md) |

## Files you actually use

| Path | What you do with it |
| --- | --- |
| `openshift/00-identities.yaml` | Apply the application/test/build identities and narrow build Role. |
| `openshift/01-storage.yaml`, `02-database.yaml` | Apply PostgreSQL storage and workload definitions. |
| `openshift/templates/builds.yaml` | Process/apply the two Git-source image-build recipes. |
| `openshift/templates/tasks.yaml`, `openshift/ci/pipeline.yaml` | Process/apply reusable Tasks, then apply the short workflow graph. |
| `openshift/runs/` | Create named Runs for baseline, green or an optional expected failure. |
| `openshift/templates/schema-job.yaml`, `renderer.yaml`, `api-slot.yaml` | Fill image/URL/slot parameters, inspect the YAML, then create/apply it. |
| `openshift/03-network.yaml` | Apply **initial blue** routing once. |
| `openshift/traffic/` | Patch the stable Service to blue or green. These are not whole resources. |
| `.local/` | Ignored private Secret copy and your inspected, processed YAML. Never commit it. |

These files are the source of truth, **not generated outputs**. Do not apply the entire directory recursively: Templates, executions, optional failures and patches have different purposes.

## Scope and verification

This is an unauthenticated educational application: use **synthetic data in an isolated project**, not confidential tickets or production traffic. No step installs an operator, changes quota or grants a privileged SCC.

The prepared walkthrough and cleanup were rehearsed on OKD. See [VERIFICATION.md](VERIFICATION.md) for exact source snapshots, observed results and limitations. This is not production certification.

The prepared Runs deliberately select published source snapshots rather than whatever happens to be on your local branch. `main` is the 1.0.0 baseline; `feature/urgent-tickets` is the reference 1.1.0 solution. The optional development guide explains how to select your own pushed SHA instead.

## For application developers

The application code is Python/Flask; it remains separate from Kubernetes authoring. Optional offline tests need Python 3.12+ and Make:

```bash
make setup
make check
```

Those commands test the applications and inspect the YAML in your current checkout without authenticating to or mutating a cluster. Local Docker Compose and opt-in HTTP smoke scripts remain developer tools, not prerequisites for the beginner path.
