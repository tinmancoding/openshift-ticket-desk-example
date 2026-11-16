# Local development

## Offline application and platform tests

Use Python 3.12 or later, Git and Make:

```bash
make setup
make check
```

The application suite uses a memory repository **only as a unit-test double**. It tests request validation, create/read behavior, priorities, missing IDs, database/dependency errors and the API/renderer contract. Platform tests inspect Git-source build definitions, exact-commit/digest handling, Task ordering, least privilege, ownership and render-only behavior. They do not prove PostgreSQL, a real image build, cluster admission, ingress or Knative works.

## Run with a real local database

With Docker and Docker Compose available:

```bash
docker compose up --build -d
docker compose logs schema api renderer
curl --fail-with-body -sS http://127.0.0.1:8080/version
python3 scripts/smoke.py --url http://127.0.0.1:8080 \
  --expected-version 1.0.0 --confirm-create
```

Compose initializes PostgreSQL, runs the explicit initial-schema command, then starts the API. The local renderer is a normal container, **not Knative**. Its functional contract is the same; autoscaling/Revision behavior needs OpenShift verification.

The local password is intentionally development-only, not a cluster credential. PostgreSQL and renderer have no host port mapping. The API binds to loopback only. Do not expose this unauthenticated application to an untrusted network.

```bash
# Stop containers and preserve the local data volume.
docker compose down
# DESTRUCTIVE, optional: erase local synthetic tickets too.
docker compose down --volumes
```

## Optional real-PostgreSQL integration utility

`scripts/check_database.py` exercises actual repository SQL and local HTTP API/renderer processes against a database you explicitly choose. It creates the initial schema and a synthetic ticket, verifies the stored SQL row and preview/outage behavior, then removes its own ticket. It is **not** a cluster image/ingress test and is excluded from offline discovery.

For an already authorized OpenShift example database, keep `oc port-forward -n YOUR-NAMESPACE service/desk-db 15432:5432` running separately. In Bash, obtain the password through your approved private process, without putting it into history:

```bash
.venv/bin/python -m pip install -r apps/api/requirements.txt
export DB_HOST=127.0.0.1 DB_PORT=15432 DB_NAME=desk DB_USER=desk
read -r -s -p 'Example database password: ' DB_PASSWORD
printf '\\n'
export DB_PASSWORD
.venv/bin/python scripts/check_database.py --confirm-database desk
unset DB_PASSWORD
```

Use only the example's synthetic-data database. `--keep-ticket` deliberately retains a test row; a later `--existing-id ID` verifies and removes that earlier synthetic row. Stop the port-forward afterwards. Do not point this schema-initialization/test utility at a production database.

## Source changes

Application versions are source constants in each package's `__init__.py`, not deployment environment flags. The release walkthrough changes API code and tests, commits/pushes the change and builds that exact revision. This makes the source-to-artifact connection observable.

For a production fork, lock transitive dependencies, pin base images by digest, scan dependencies/images, add authorization, use pooling and upgrade tests against a real PostgreSQL fixture. This initial example's direct dependency pins are not a reproducible lock or a security certification.
