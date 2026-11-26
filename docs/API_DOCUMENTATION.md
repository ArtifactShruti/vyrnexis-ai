# API reference

Base URL for local development: `http://127.0.0.1:8001`. Interactive OpenAPI is available at `/docs`.

All `/api/v1` business routes require a bearer access token except registration, login, refresh, and logout. Organization scope is taken from the authenticated account. Supplying a different tenant or an object from another tenant is rejected.

## Authentication

- `POST /api/v1/auth/register` — create organization owner and session.
- `POST /api/v1/auth/login` — authenticate with email and password.
- `POST /api/v1/auth/refresh` — rotate a refresh token; replay is rejected.
- `POST /api/v1/auth/logout` — revoke the refresh session.
- `GET /api/v1/auth/me` — current user and organization.

## Operational data

- `GET /api/v1/dashboard` — tenant-scoped counts and recent records.
- `GET, POST /api/v1/incidents` — list and create incidents. Create is role restricted and begins an audited event history.
- `GET /api/v1/assets?search=&status=` — return up to 500 tenant assets, optionally filtered by name/type/identifier and lifecycle status.
- `POST /api/v1/assets` — role-checked, tenant-scoped, audited asset creation with validated criticality and lifecycle status.
- `GET /api/v1/security-events` — list recent events for the signed-in organization. Filter by `search`, `severity`, and `status`. The default limit is 100 and the maximum is 500.
- `POST /api/v1/security-events` — record a security observation from an authorized source. Ingestion requires a write role and creates an audit entry. Optional `occurred_at` is stored as UTC.
- For authentication detection, use `event_type=authentication`, `login`, or `sign_in` and supply `account`, optional `device`, and `outcome` (`success` or `failure`). An optional `external_id` deduplicates identical submissions per organization and normalized source. Reusing the ID with changed data returns 409.
- `GET /api/v1/detection-rules` and `PUT /api/v1/detection-rules/{kind}` — inspect or configure `failed_signins` and `unfamiliar_device`. Settings include severity, look-back, enabled state, and the failure threshold. Only the owner, organization admin, or security analyst can change a rule.
- `GET /api/v1/detection-runs` and `GET /api/v1/detection-status` — list recent rule evaluations and processing state.
- `GET /api/v1/security-alerts` and `GET /api/v1/security-alerts/{id}/events` — list alerts and inspect the underlying observations.
- `POST /api/v1/security-alerts/{id}/incident` — create one incident after analyst confirmation. Repeat requests return the original incident. `GET /api/v1/incidents/{id}/security-events` returns its supporting records.
- `POST /api/v1/security-alerts/{id}/false-positive` with a `note` resolves an open alert and stores the reason in the audit log.
- `PATCH /api/v1/security-events/{id}/status` — mark a new event `reviewed` or `dismissed`. Requires a write role. Repeating the same decision succeeds without a second audit entry. Changing a completed decision returns 409.
- `PATCH /api/v1/incidents/{id}/status` — role-checked status transition with a validated state machine and optional note.
- `GET /api/v1/incidents/{id}/history` — tenant-scoped creation and status event history.
- `GET /api/v1/intelligence/entities` — list tenant entities.
- `GET /api/v1/intelligence/graph` — tenant graph traversal.
- `GET, POST /api/v1/intelligence/graph/bookmarks` — user-owned bookmarks with tenant validation.
- `POST /api/v1/intelligence/relationships` — create a relationship between two tenant entities.
- `GET /api/v1/evidence` — list tenant-scoped evidence metadata.
- `POST /api/v1/evidence` — bounded upload (25 MiB) to local storage outside the web root with SHA-256/SHA-512 digests and audit metadata.
- `GET /api/v1/evidence/{id}/download` — tenant-checked download after re-verifying both digests.
- `GET, POST /api/v1/workflows` lists or creates legacy workflow definitions. Workflow Studio provides execution.
- `POST /api/v1/intelligence/correlate` — explainable grouping over saved relationship records; correlation is not causation.

## Agent analysis

- `GET /api/v1/agents` — authenticated registry of seven local deterministic analyzers.
- `POST /api/v1/agents/executions` — run `analyze_organization` with JSON `{ "agent": "SENTINEL", "incident_id": "optional-tenant-incident-id" }`.
- `GET /api/v1/agents/executions?limit=50` — saved run history; limit is 1–100.

The supported agents are ORACLE, SENTINEL, TRACE, AEGIS, MERCURY, NEXUS, and VERITAS. This individual execution route remains synchronous. It reads authorized tenant records, saves history and audit activity, and returns record references, limitations, null confidence, and review guidance. The persisted Nexus pipeline has separate endpoints below.

## Ingestion, commerce, and forensic inspection

- `GET/POST /api/v1/data-sources` lists or creates a security, commerce, or asset source. `GET/POST /api/v1/data-sources/{id}/batches` lists reports or ingests an authorized batch. `GET /api/v1/data-sources/{id}/batches/{batch_id}` returns per-row results.
- Submit UTF-8 JSON with `{"version":1,"records":[...]}` or CSV with a `schema_version=1` cell on each row. Include `record_type`, `external_id`, and timezone-aware `occurred_at`. JSON and CSV have a 512 KiB body limit and a default 100-row batch limit. The limit can be configured with `VYRNEXIS_MAX_BATCH_ROWS` up to 200. Sources accept up to 12 new batches per minute.
- Send `Idempotency-Key` on submission. Identical request replays return the prior report. Reusing a request or source event ID with changed data reports a conflict. Row results tell clients what to correct. To retry correcting rejected rows, submit a new batch with a new key.
- Owners and organization admins can issue and revoke expiring keys under `/api/v1/data-sources/{id}/keys`. A key is shown once. Submit to `POST /api/v1/ingestion/webhooks/{id}` with `X-Ingestion-Key` and `Idempotency-Key`.
- `GET /api/v1/commerce/records` lists stored payment and refund observations. `GET /api/v1/commerce/totals` groups counts and integer minor-unit totals by currency and record kind. Amount totals are decimal strings to preserve precision.
- `GET/PUT /api/v1/commerce/policy` reads or updates the correlation window and thresholds. `POST /api/v1/commerce/refunds/{id}/evaluate` lets an analyst rerun evaluation after late observations arrive. `GET /api/v1/commerce/findings/{id}/sources` lists supporting refunds, authentication events, and evidence references.
- `POST /api/v1/commerce/findings/{id}/incident` confirms the review and returns one incident on repeat calls. `POST /api/v1/commerce/findings/{id}/dismiss` requires feedback and records the reason in the audit log.
- `POST /api/v1/evidence/{id}/verify` checks both hashes and returns size and a file signature hint. `GET /api/v1/evidence/{id}/activity` lists bounded upload and verification audit entries.
- Evidence upload, forensic-role inventory, and successful verification return `image_metadata`. It includes inspection status, inspection time, and available dimension, orientation, and embedded capture time fields. Older files can have a null metadata record until verified. Enrolled files use case custody verification.

## Forensic cases

These paths are under `/api/v1/forensic-cases`. Owners, admins, and forensic investigators can write. Security analysts can read. Assignment and reopening require an owner or organization admin.

| Method and suffix | Behavior |
| --- | --- |
| `GET /`, `POST /`, `GET /{case}` | List, create, or inspect a case. List accepts `query`, `status`, `assigned`, `sort`, `offset`, and `limit`. |
| `GET /investigators` | List eligible same-tenant investigators. |
| `PUT /{case}/assignment` | Set an investigator or team with `expected_version`. |
| `POST /{case}/transition` | Supply `status`, `reason`, and `expected_version`. Closure requires assignment and a latest review note. |
| `POST /{case}/links` | Attach a tenant-owned incident, finding, or entity. |
| `POST /{case}/notes`, `POST /{case}/notes/{note}/revisions` | Add a categorized note with optional authorized references. Revisions require `expected_revision`. |
| `POST /{case}/evidence` | Enroll an uploaded file with `evidence_id`, classification, purpose, optional tags and custodian. |
| `GET/POST /{case}/evidence/{evidence}/custody` | Inspect the chain or change custody using `action`, `purpose`, and `expected_sequence`. |
| `POST /{case}/evidence/{evidence}/export` | Provide a purpose to export a digest-checked, non-archived file and append a custody event. |
| `GET/POST /{case}/reports`, `GET /{case}/reports/{report}/{format}` | List or generate a bounded snapshot, then download it as `json` or `pdf`. |

Stale versions, stale custody sequences, and digest conflicts return 409. The legacy evidence download and verify routes require the case workflow after enrollment.

## Investigation Nexus

- `GET /api/v1/investigations/worker` reports worker mode and heartbeat availability. `GET /api/v1/investigations` lists tenant runs.
- `POST /api/v1/investigations` accepts `request_key` with exactly one of `case_id` and `incident_id`. The same tenant, key, and scope return the same run. Changed scope for a reused key returns 409.
- `GET /api/v1/investigations/{run}` returns dependencies, attempts, results, and human review state. `POST /{run}/cancel` cancels an active run and discards late results. `POST /{run}/review` accepts `decision` of `approved` or `rejected` and a `note` from a forensic writer.
- `GET /api/v1/investigations/{run}/report` exports finished processing as JSON with a SHA-256 hash over the canonical snapshot. The response distinguishes pending, approved, and rejected review.
- Investigation submission accepts optional `agents`; the plan includes their prerequisite closure. Forensic writers can `POST /api/v1/investigations/{run}/replay` for a finished run with failures. A replay requires an idempotent `request_key` and optionally specific failed agents. The original run retains its status, results, and attempts.
- `GET/POST /api/v1/investigations/{run}/tasks/{task}/interpretations` reads or requests separate model interpretations of a completed task. Submitting requires hybrid mode and explicit context acknowledgement. A forensic writer can review a completed interpretation through `POST .../interpretations/{id}/review`.
- `GET/POST /api/v1/commerce/findings/{finding}/scenarios` lists or creates isolated hypothetical comparisons. The `scenario` field accepts `exclude_device`, `legitimate_refund`, `exclude_event` with a linked `event_id`, or `adjust_thresholds` with a correlation `policy`.

## Browser same-origin API

The Next.js app proxies `/api/dashboard`, `/api/incidents`, `/api/assets`, `/api/agents`, and `/api/evidence` using server-held HttpOnly access cookies. Browser code does not receive bearer tokens. `GET /api/agents?view=history` reads run history; `POST /api/agents` executes an analysis; evidence upload/list and download use same-origin endpoints.

`/api/forensic/forensic-cases/…` and `/api/forensic/investigations/…` proxy the allowlisted methods above. The proxy caps JSON bodies at 64 KiB, rejects cross-origin writes, and forwards attachment headers on exports.

## AI workspace

- `GET /api/v1/ai/availability` reports the tenant mode and whether model assistance is enabled by configuration. Admin-only `GET/PUT /api/v1/ai/settings` manages model policy and shows recent usage. `POST /api/v1/ai/test` checks the saved connection.
- `GET/POST /api/v1/knowledge/documents` lists or indexes documents. A create payload contains `title`, `filename`, `content_base64`, `visibility`, and `retention_days`. Append a new file with `POST /documents/{id}/versions`, adjust access via `PUT /documents/{id}/policy`, and delete via `DELETE /documents/{id}`. `GET /api/v1/knowledge/search?query=...` returns authorized passages and provenance.
- `GET/POST /api/v1/copilot/conversations` lists and creates account-owned conversations with optional case or incident context. Use `GET/DELETE /conversations/{id}` and `GET /conversations/{id}/export` to inspect, delete, or export. `POST /conversations/{id}/turns` takes `text`, an idempotent `request_key`, and mode. Model assistance requires `acknowledge_model_context`. Stop an active request with `POST /conversations/{id}/cancel/{request_key}`.
- The browser uses the allowlisted same-origin `/api/workspace` proxy and HttpOnly session cookies. No provider credentials or raw source files enter the browser through the settings route.

## Workflow Studio

Base path `/api/v1/workflow-studio`. List templates with `GET /templates` and manage drafts with `GET/POST /workflows` and `GET/PUT /workflows/{workflow_id}`. Validate with `POST /validate`. Publish a draft or adjust its state with the workflow's `POST /publish` and `POST /lifecycle` subroutes. Updates and publication require the current draft revision.

Start a manual or dry-run evaluation with `POST /workflows/{workflow_id}/executions`. List and inspect runs at `GET /executions` and `GET /executions/{execution_id}`. Run commands use `POST /executions/{execution_id}/cancel`, `POST /executions/{execution_id}/replay`, and `POST /executions/{execution_id}/approvals/{node_id}`. An approval records a reviewer decision and rationale. PostgreSQL worker triggers apply to published schedules and supported tenant event types.

## Digital Twin and Business Intelligence

- `GET /api/v1/digital-twin/topology` reads the authorized topology. `POST /api/v1/digital-twin/dependencies` records an explicit relationship. `GET/POST /api/v1/digital-twin/simulations` lists and creates simulations. `GET /api/v1/digital-twin/simulations/{scenario_id}` and its `/export` subroute read saved snapshots.
- `GET /api/v1/business-intelligence/report` and `GET /api/v1/business-intelligence/export` read recorded commerce over the selected UTC range and optional currency. Export supports JSON and CSV.

## Hybrid search and Copilot streams

- `GET /api/v1/knowledge/embeddings/availability` returns deployment availability. `GET/POST /api/v1/knowledge/documents/{document_id}/embedding` checks or queues indexing. `POST /api/v1/knowledge/search/hybrid` performs hybrid retrieval after local-processing acknowledgement or returns an explicit keyword fallback.
- `POST /api/v1/copilot/conversations/{conversation_id}/stream` accepts the same body as the normal turn endpoint. It returns server-sent events. Use the persisted final turn for citations and exports. Transport failures and user cancellation can interrupt provisional text.
