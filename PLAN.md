# Implementation plan

## Objective

A standalone, runnable and self-documented OpenShift example: a persistent support-ticket API, a stateless Knative notification-preview renderer, and a GitHub-to-digest release workflow. No workshop files or credentials are required.

## Architecture decisions

- Python/Flask HTTP components; PostgreSQL stores tickets. Rendered previews are returned on demand, not delivered as email. No unreliable synchronous email delivery is disguised as a durable event system.
- Git-source Docker-strategy BuildConfigs own image construction. Tekton owns source tests, build invocation and image-contract checks. Both source checkout and Build use the same full Git SHA.
- No binary uploads, privileged image-builder Tasks, automatic BuildConfig triggers or production image-change triggers.
- Explicit human candidate deployment, distributed verification and blue/green Service-selector promotion. Promotion reuses a tested digest, never rebuilds it.
- Both API slots share one database. The initial schema already contains priority; the example release adds an accepted priority value without a schema change. Rollback is traffic routing, not data rollback.
- Renderer runs through Knative Serving; API and PostgreSQL remain ordinary Deployments. Knative does not magically make the database serverless.
- Namespace-only build permissions; workflow identity cannot deploy or promote. Applications receive no API token.
- Renderer is internal to the application's contract, but its Knative URL can be public depending on the platform. No authentication is provided: synthetic data only.

## Delivery slices and acceptance

1. Application: validation, durable repository, dependency error handling, real unit tests, Dockerfiles and local setup.
2. Platform: render-only manifest generation, storage/schema initialization, scoped build identity, two Git BuildConfigs, Tekton definitions, slots and stable/preview Services.
3. Release: CLI that checks namespace/identity, waits for exact Run/Build, archives source/digest evidence, verifies candidates and changes routing explicitly.
4. Documentation: architecture, walkthrough, operations/limitations and verification record. No default command mutates a cluster.
5. Authorized acceptance: learner09 only; preflight identity/API/quota, local tests, then Git-source live checks after source publication. Record actual outcomes and any untested paths. Clean only owned example resources; never change platform/other users.

## Current status

The initial implementation and authorized Git-source release acceptance are complete. `main` preserves API 1.0.0 as the baseline; `feature/urgent-tickets` supplies the 1.1.0 reference solution. Source rejection, successful builds/image tests, deployed schema/API/Knative calls, candidate isolation, promotion, rollback, cross-version reads, actual CI permission denials and owned-resource cleanup were observed. Exact evidence and remaining limits are in [VERIFICATION.md](VERIFICATION.md). Local Compose runtime and production capabilities remain outside that acceptance claim.

## Not in scope

Production authentication, authorization, rate limiting, durable notification delivery/outbox, Git webhook installation, automatic production approval, schema migration orchestration, high availability, backup/restore certification, cluster operator installation or broad SCC/RBAC grants. These are documented production gaps, not implied features.
