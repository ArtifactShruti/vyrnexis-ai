# Architecture

VYRNEXIS starts as a modular monolith with FastAPI domain modules and an independently runnable worker boundary. PostgreSQL can replace SQLite by setting `DATABASE_URL`. The frontend uses Next.js and calls versioned API routes.

## Core boundaries

- Identity, organizations, user roles, and revocable authentication sessions.
- Tenant-scoped intelligence entities, relationships, graph traversal, bookmarks, and event timelines.
- Incident and evidence metadata management; asset inventory with tenant-scoped list/filter, role-checked creation, and audit events.
- Security event ingestion and analyst triage. Event data and review decisions are tenant scoped. Review writes use a conditional update and commit with their audit entry.
- The SQLite stack evaluates detections inline. The PostgreSQL stack stores pending evaluations in PostgreSQL and uses Redis for wake signals and worker readiness. The worker rechecks pending rows even when a wake signal is lost. Jobs, rule runs, alerts, and source relationships persist in the database.
- Each rule uses a rolling event-time window. Matching alerts for the same rule, account, and grouping interval are consolidated. The unfamiliar-device rule also groups by device and requires an earlier observed successful sign-in. Confirmed alerts preserve their source set and link the incident to source events and reported account/device labels.

## Schema ownership

The isolated PostgreSQL Compose stack applies the `0001` baseline, `0002` detection, and `0003` intake and commerce revisions via an explicit migration service. The default SQLite demo keeps its additive table initialization for compatibility with existing local databases. Run Alembic with an explicit URL against a fresh database or a reviewed schema migration target.

Batch uploads are bounded UTF-8 requests. A source write lock serializes its rate check and receipts. Row savepoints preserve accepted records alongside validation results. The batch report, accepted records, receipt keys, and audit entry commit together. PostgreSQL security records enqueue detection work in the same transaction. Redis messages only wake the worker.

Commerce batches store payment and refund observations in integer minor units with explicit currency. Tenant-scoped rules compare reported account/device identifiers and event times. Resolved findings keep the reviewed source references. Confirmation writes the incident, creation history, graph relationships, and audit entry together.
- Agent registry with synchronous deterministic local execution and persisted history; external providers and background orchestration are not implemented.
- Workflow persistence (execution engine is not yet implemented).
- Audit event persistence for supported authentication and domain mutations.

## Authentication boundary

The browser uses Next.js API routes as a same-origin backend-for-frontend. Access and refresh tokens are stored in `HttpOnly`, `SameSite=Strict` cookies and are never returned to browser JavaScript. The BFF forwards bearer access tokens to FastAPI. FastAPI reloads the user and session for protected requests, checks session revocation/expiry, and derives the organization from the stored user membership. A client-supplied organization ID is accepted only as an optional consistency check and cannot change scope.

Access tokens live for 15 minutes. Refresh tokens are single-use, rotated using a stored SHA-256 hash of their JTI, and expire after seven days. Logout revokes the active server-side session. If `JWT_SECRET` is omitted in development, the API generates an ephemeral key; configure a stable high-entropy secret to preserve sessions across restarts. Production mode refuses an absent, placeholder, or short secret.

The current membership model assigns each user to one organization. Supported roles are enforced on write endpoints; reads remain organization-scoped for active members. MFA, password recovery, login throttling, invitation lifecycle, and multi-organization membership remain future work.

## Intelligence graph

Graph endpoints return only the authenticated user's organization. A focused traversal returns the selected entity plus its directly connected entities and relationships. Full graph reads are bounded and report truncation. Bookmarks are scoped to both organization and owner. The timeline combines persisted relationship, incident, and evidence records; timestamps and references are returned from stored data.

## Local data

The default SQLite URL is `sqlite:///./vyrnexis.db`. The deterministic synthetic demonstration workspace is isolated at `.dev-logs/vyrnexis-demo.db`. Tests create a separate temporary SQLite database per test and also isolate the app's import-time schema initialization in the system temp directory.

Docker Compose runs the API and web containers on host ports 8001 and 3000. It bind mounts only the demo SQLite file and `.dev-logs/evidence`. The compose signing key is generated locally in ignored `.env`, which is also excluded from the Docker build context. This Compose environment is for local demonstration and verification, not production deployment.
## Agent execution

The individual agent registry and executor live in the API. Individual runs execute deterministic analysis synchronously over records scoped to the authenticated organization. They persist structured request/output, status, actor, timestamps, and an audit event. Investigation Nexus uses the same execution history with a separate durable pipeline. The same-origin `/api/agents` routes forward requests using HttpOnly access cookies.

## Evidence storage

Evidence bytes are stored under `VYRNEXIS_EVIDENCE_DIR` (default `.dev-logs/evidence`), outside the Next.js static tree. Organization directory names are SHA-256 digests, and object filenames are server-generated evidence IDs. Bounded uploads are atomically renamed from a temporary file, and metadata and audit records stay in the tenant database. Downloads check tenant ownership and recompute both digests. Local storage needs a stable protected path and backups.

### Forensic Laboratory and Investigation Nexus

Alembic revision `0004` adds forensic cases and Nexus without rewriting existing tables. The SQLite compatibility app adds the same tables using its existing startup mode.

Cases link tenant-owned incidents, commerce findings, intelligence entities, and evidence. A conditional case update serializes case writes. Registration adds one ledger per evidence item. Custody events retain the previous digest and custodian, and every protected write checks the chain and its head. Report creation snapshots the case, notes, sources, activity, custody, and latest eligible Nexus run. JSON carries the full snapshot, while the text-only PDF presents material from it.

Revision `0005` adds a metadata table keyed by evidence ID. Uploads send a bounded header prefix to a separate Python process with reduced environment, registered fields, and a wall-clock deadline. Linux adds CPU and memory limits. Inspection reads JPEG APP1 EXIF or standard TIFF directories and stores dimensions, orientation, and claimed capture time where available. Verifying older evidence can populate the table only after both hashes match. [CIPA Exif standards](https://www.cipa.jp/e/std/std-sec.html) · [TIFF 6.0 specification](https://printtechnologies.org/standards/files/tiff-v6.pdf)

On PostgreSQL, the worker checks detection and investigation tasks. PostgreSQL holds runs, dependency edges, task leases, results, and attempt history. Redis wakes the worker and supplies an expiring heartbeat. The worker runs each investigation task in a child process and kills and reaps it on deadline. A token check prevents the supervisor from overwriting a new lease or a result already committed. Downstream tasks can report gaps after an upstream terminal error. In SQLite, a bounded pipeline advances in the submission request.

Nexus tasks read tenant-scoped stored observations, findings, and hashes. VERITAS checks that upstream references resolve within the tenant. Before accessing enrolled evidence bytes, it records an examination in the matching case under the requesting forensic writer's identity. An authorized reviewer can approve or reject the result. The decision updates the run's review state.

## AI workspace

The API owns provider credentials, connection checks, and the usage ledger. OpenAI-compatible, Anthropic, Gemini, and Ollama protocol adapters share bounded asynchronous HTTP transport, structured response validation, and versioned prompts. Settings store no secrets. The server and tenant policies both gate model requests. External request accounting reserves a conservative estimate before submission and reconciles reported token counts when available. [OpenAI Chat](https://developers.openai.com/api/reference/resources/chat) · [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create) · [Gemini generateContent](https://ai.google.dev/api/generate-content) · [Ollama Chat](https://docs.ollama.com/api/chat)

Knowledge ingestion extracts bounded plaintext in a child process. Tenant, document visibility, and expiry filters run before the keyword query. Results carry version and passage provenance. Copilot stores questions and source keys per account and resolves citations again when opening history. Model-assisted responses require authorization and can only cite the selected source keys.

Nexus uses the same gateway for explicitly requested interpretations of completed deterministic findings. Review decisions apply to each interpretation. A replay creates a separate run with linkage to the original. Selective runs include prerequisite closure. Counterfactual commerce scenarios reuse the read-only rule calculation and save a separate result snapshot.

## Workflow Studio, Digital Twin, and Business Intelligence

Workflow Studio keeps editable drafts separate from published graph versions. A run binds to one graph and persists each node transition in the same transaction as its output. The PostgreSQL worker advances due schedules, observes new tenant records after publication, and recovers queued steps after a restart. Redis messages act as wake signals. SQLite handles bounded manual execution inline. Approval nodes wait on persisted decisions, and replay creates a linked run.

Digital Twin uses entitled intelligence entities and explicitly recorded dependency relationships. Each bounded traversal keeps the source topology and simulation assumptions in a saved snapshot. Alternative exclusions apply to the simulation only. Business Intelligence uses the stored commerce records and refund reviews. It calculates integer minor-unit totals and aligned period comparisons for each currency. The UI and JSON/CSV exports share that reporting query.

## Local embeddings and Copilot streaming

An authorized document owner or operator can request indexing of the newest accessible document version. The worker batches passages for a configured local Ollama model. The database tracks the job profile, attempts, and per-passage vectors. Hybrid search filters entitled current passages, ranks a bounded set of candidates, and combines cosine and lexical rankings. If the model is disabled, unavailable, or has no eligible vectors, the endpoint returns keyword results with an explicit reason.

Copilot can consume provider-native SSE or NDJSON. The same-origin proxy forwards provisional plain text. Final structured output still passes the shared accounting, citation, and persistence path. The default deterministic mode stays available in the same workspace.
