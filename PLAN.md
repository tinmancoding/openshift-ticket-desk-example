# Ticket Desk implementation and teaching plan

## Objective

A standalone example connecting Git-source BuildConfigs, Tekton, an explicit blue/green API release and a stateless Knative renderer, with PostgreSQL persistence. It must be understandable through normal OpenShift resources and commands—not a custom deployment framework.

## Current teaching decisions

- Canonical **YAML** in `openshift/`; small native OpenShift Templates expose repository, image digest, slot, renderer URL and compatible CLI image parameters. No Python Kubernetes manifest generator or deployment/modification CLI.
- Separate recipes, executions and traffic patches. Learners see exactly which file creates a BuildConfig, starts a Run, deploys a slot or changes a Service selector.
- A prepared first pass uses already-published 1.0.0/1.1.0 source commits. No fork, push credential, local Python setup or source editing is required for that platform walkthrough.
- Optional follow-ups teach a real failing test and the learner's own pushed release. Application Python and developer tests remain separate from manifest authoring.
- Each step introduces its vocabulary/command forms, has expected evidence and says when to stop. Processed files live in ignored `.local/` and are inspected before apply.
- Native commands do not inherit the retired custom tool's owner/UID guards. Explicit project/name checks, known-file cleanup and data-retention decisions are taught honestly. No namespace-wide deletes or policy escalation.

## Application/release decisions retained

- Flask ticket API with PostgreSQL; separate HTTP renderer returns notification previews without sending email.
- Tekton tests source, invokes a Git-source Docker BuildConfig at the same full SHA, then tests the exact built digest. No binary uploads, privileged build Tasks or automatic build/production image-change triggers.
- CI identity cannot deploy or promote. A human validates green and applies a visible Service-selector patch; rollback selects the existing blue image without rebuilding.
- Both slots share one database. Urgent priority is a backwards-compatible, no-schema-change release. Rolling back traffic does not reverse data writes.
- Knative manages only the stateless renderer; the API/database are ordinary workloads.

## Acceptance

The earlier custom-tool implementation and reference urgent release were tested on learner09; exact historical evidence remains in `VERIFICATION.md`. The simplified native path has now passed its **own** 29-test offline checks and authorized learner09 rehearsal using the exact published application snapshots, including named retry, source rejection, release switches and native cleanup/data-retention behavior. Manifest hashes and precise limits are recorded separately; old tool results do not automatically certify new commands or unpublished source.

Accepted findings from two independent read-only editorial reviews have since been applied to restart, continuation, cleanup and terminology guidance. Only documentation and its text-regression assertions changed in that follow-up; no additional test suite or cluster rehearsal was run.

## Not in scope

Production authentication/authorization, durable email/outbox, HA/backup certification, incompatible schema migration orchestration, automatic production approval, operator installation, quota changes or broad SCC/RBAC grants. See [operations](docs/operations.md) and [verification](VERIFICATION.md).
