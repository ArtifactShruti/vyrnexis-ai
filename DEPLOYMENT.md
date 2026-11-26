# Local deployment and verification

Run these commands from the repository root with Docker Desktop running and the local signing settings already provisioned as described in [README.md](README.md).

```powershell
docker compose up -d --build --wait --wait-timeout 120
docker compose --env-file .env.postgres -f docker-compose.postgres.yml up -d --build --wait --wait-timeout 120
docker compose ps
docker compose --env-file .env.postgres -f docker-compose.postgres.yml ps
docker compose --env-file .env.postgres -f docker-compose.postgres.yml exec -T api alembic current
docker compose --env-file .env.postgres -f docker-compose.postgres.yml exec -T api alembic check
```

| Local stack | Web | API docs | Durable state |
| --- | --- | --- | --- |
| PostgreSQL and Redis | [Open](http://localhost:3001) | [Open](http://127.0.0.1:8002/docs) | Dedicated database and evidence volumes. Alembic applies through `0018`. |
| SQLite compatibility | [Open](http://127.0.0.1:3000) | [Open](http://127.0.0.1:8001/docs) | `.dev-logs/vyrnexis-demo.db` and `.dev-logs/evidence`. API startup creates missing tables and adds legacy organization or incident fields in place. |

PostgreSQL keeps durable jobs, results, and trigger cursors. The worker polls PostgreSQL for work and uses Redis for wake signals and heartbeat. SQLite supports manual workflow execution and compatible read/report routes. Use [the test guide](docs/TESTING.md) for isolated checks and signed-in acceptance. Run worker restart checks only on the dedicated local PostgreSQL demo.

## Optional model configuration

Generation provider choices and their settings are documented in [README.md](README.md). For local embeddings, set `VYRNEXIS_EMBEDDINGS_ENABLED=1`, `VYRNEXIS_EMBEDDING_URL` to an operator-controlled local Ollama server reachable by the API and worker, `VYRNEXIS_EMBEDDING_MODEL` to an installed embedding model, and `VYRNEXIS_EMBEDDING_REVISION` to an operator-managed revision. Supply these through ignored Compose environment settings. A revision change calls for re-indexing. The Ollama service must have cloud functionality disabled. Verify using synthetic documents first. Keyword search remains available without this configuration. See the [Ollama embedding endpoint](https://docs.ollama.com/api/embed).

The PostgreSQL worker stays on an internal Docker network. An operator who enables embeddings can attach a private Ollama service to that network with the service name `ollama`. Verify the local URL from both containers before indexing.

## Database and evidence preservation

Keep the original `vyrnexis.db` separate from the demo bind mount. Before a stateful upgrade, copy a consistent database and related evidence snapshot into administrator-controlled storage. For PostgreSQL use a credentialed logical dump and a matching evidence copy, then rehearse restoration in a separate environment. For SQLite use its backup mechanism and keep the matching evidence snapshot. Verify row counts, original evidence hashes, and access after restore. Keep existing volumes and needed encryption/signing configuration intact during a local rebuild.

Public deployment requires explicit authorization and separate acceptance of TLS, backup restoration, recovery targets, least-privilege database roles, audit retention, monitoring, and the controls in [SECURITY.md](SECURITY.md).

## Release checks

The GitHub Actions workflow in `.github/workflows/verify.yml` defines isolated backend tests and frontend lint, production build, and TypeScript checks. Its commands ran locally. A hosted run requires a connected repository. See [GitHub's workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Local performance sample

On the local Docker Desktop host on November 26, 2026, five sequential loopback requests per endpoint returned HTTP 200. SQLite API health took 8–27 ms and PostgreSQL API health took 9–14 ms. The initial Workflow Studio route response took 27–61 ms on SQLite and 42–59 ms on PostgreSQL. These route timings cover the HTTP response only. A single Docker snapshot reported about 72 MiB for the PostgreSQL worker, 101 MiB for its web service, and 98 MiB for the SQLite web service. The Next.js build reported 144 kB of first-load JavaScript for the platform module route and 103 kB shared. Loaded-user latency, large graphs, and live vector retrieval still need dedicated measurements.
