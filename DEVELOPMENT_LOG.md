# Development Log

## Repository and dashboard presentation

- Added a README cover illustration, an architecture flow, and a dashboard roadmap.
- Added a tenant-scoped 7/30-day UTC activity chart, selected-day totals, and the running database label. The dashboard query now limits recent incident and entity lookups at the database.
- The older SQLite demo required an additive schema update for organization and incident fields. The demo startup upgrades only the isolated file and preserves existing rows.
- Passed 58 isolated backend tests, frontend lint, TypeScript, and the production build. Regression tests cover UTC and tenant boundaries, incident opening versus current status, and legacy SQLite row preservation.

## 2026-11-25

- Replaced dashboard mock records and decorative relationships with tenant dashboard API data; unsupported posture and health scores are shown as unavailable.
- Added a deterministic synthetic organization seed isolated at `.dev-logs/vyrnexis-demo.db`; preserved `vyrnexis.db`.
- Added JWT auth, refresh rotation/replay denial, logout revocation, current-user/session checks, role-gated writes, tenant and object checks, and audit events across supported API domains.
- Added temporary per-test SQLite fixtures and a bounded pytest script. The original stalled TestClient run was traced to local socket creation under restricted execution. The bounded run with local socket access completed with 6 passing tests and one upstream deprecation warning.
- Replaced client-side token storage with same-origin Next.js auth routes and HttpOnly SameSite cookies. Protected dashboard, graph, bookmark, and incident proxies forward server-held access tokens.
- Implemented an interactive tenant-aware graph workspace with traversal, search/filter, pan/zoom, minimap, timeline inspection, bookmarks, and JSON export.
- Implemented Incident Manager listing, search/severity filters, persisted counts, and role-checked incident creation.
- Refined sign-in and organization registration into a branded, accessible dark entry flow.
- Fixed an invalid dashboard incident-row JSX fragment found by lint/type checking. Final lint, TypeScript check, and production build passed.
- Visual browser check confirmed the production sign-in styling. Anonymous incident API access returns 401 and the protected Incident Manager redirects to sign-in.
- During runtime verification, multiple VYRNEXIS dev servers were found sharing `.next`; they were ownership-checked and stopped before the final production build. The production frontend is now running on 3000 and the demo API on 8001. The unrelated listener on 8000 was not changed.
- Updated the implementation page matrix and recorded unimplemented enterprise modules and production gaps. Do not mark those items complete until they have meaningful behavior, authorization, and verification.
- Added deterministic analysis for ORACLE, SENTINEL, TRACE, AEGIS, MERCURY, NEXUS, and VERITAS over tenant-scoped incidents, graph records, and evidence metadata. Runs persist structured input/output and audit events, cite records, state limitations, and require human review where relevant; there are no provider calls or model claims.
- Added an authenticated agent control center with selection, run submission, optional incident scoping, local-only/provider-unconfigured notice, and execution history.
- Added tests for agent registry authentication, run persistence, history, tenant/object isolation, and validation.
- Verification: isolated backend suite passed (7 tests); frontend lint, TypeScript, and separate-directory production build passed. Build emitted an Autoprefixer `align-items: end` compatibility warning, corrected in source afterward. Docker Compose could not be invoked because the Docker executable was not discoverable in this shell.
- Added role-checked incident status transitions (open, investigating, review, contained, closed), a state-transition validation map, per-incident tenant-scoped creation/status history, audit events, and a functional status control in Incident Manager.
- Verification after incident changes: isolated backend suite passed (8 tests); frontend lint, TypeScript, and isolated production build passed. Local HTTP service smoke checks remained unavailable because server processes did not stay reachable across shell sessions.
- Implemented a file-backed Evidence Vault with tenant-scoped upload/list/download and digest re-verification; added seven deterministic, persisted tenant-scoped agent executions and a UI; added incident status transitions, event history, and audit records.
- Hardened the Docker web image with lockfile installation, lint, TypeScript, and production build steps; excluded local databases and demo files from Docker build context. Compose binds only `.dev-logs/vyrnexis-demo.db` and `.dev-logs/evidence`, leaving `vyrnexis.db` unmounted.
- Updated frontend dependencies to patched Next.js 15.5.29, PostCSS 8.5.23, and Sharp 0.35.5; `npm audit` reported zero vulnerabilities. Docker rebuild completed and both services are running on 3000 and 8001.
- Docker smoke verification: `/login` returned 200, API `/health` returned 200, and anonymous agent/evidence API requests returned 401. The Compose signing secret was a temporary process value for this local run; no project secret file was created.
- Read-only database check: one synthetic evidence record exists; the expected demo owner is absent from both the isolated demo database and the preserved `vyrnexis.db`. Authenticated browser verification remains blocked on creating the account through the masked local seed prompt.
- User created the demo owner through the masked local prompt. Browser verification then confirmed authenticated dashboard access and the linked demo scenario, incident creation persisted after refresh, search and severity filtering, graph neighbor expansion, a persisted SENTINEL run with two references, evidence inventory, sign-out, and protected-route redirect. No password was viewed or entered by the agent.
- Added `.gitignore` and `.dockerignore` safeguards for `.env`, generated data, and local build artifacts. Generated a random local Docker signing key in ignored `.env`; Compose rebuilt/restarted with the stable key. Final post-restart Docker smoke checks returned `/health` 200, `/login` 200, and anonymous agent/evidence routes 401.
- Final isolated backend verification: **8 passed, 1 warning in 3.94s**. The only warning remains upstream Starlette/AnyIO `BlockingPortal` deprecation. Docker web build checks lint, TypeScript, and production build; the final image rebuild reused the successful cached checks.
- Added the asset inventory vertical slice: `assets` persistence, authenticated tenant-scoped list/search/status filters, role-checked audited creation, cookie-backed same-origin proxy, responsive UI, and navigation. Tests cover unauthenticated access, tenant read/write isolation, filters, viewer write denial, and audit creation. Final isolated suite: **9 passed, 1 warning in 6.07s**.
- Frontend checks after asset work: lint, TypeScript, Next.js 15.5.29 production build passed. `npm ci` reported zero vulnerabilities. Docker rebuilt both images with the new asset API/UI; browser verification confirmed asset create, refresh persistence, search, and status filtering.
- Added Security Operations with manual event ingestion, tenant-scoped search and filters, and audited review or dismissal. Seeded two labeled synthetic events in the isolated lab. The dashboard now displays recorded incident timestamps and drops the inactive time-range label.
- Verified 10 isolated API tests, lint, the production build, and TypeScript. Rebuilt both Docker services with loopback bindings and an API health check. Health and login returned 200, and anonymous event requests returned 401 at both API entry points. Authenticated testing of Security Operations in the browser remains pending after the browser access denial.

### Phase 4

- Added a separate local Compose stack with PostgreSQL, Redis, Alembic, API, web, and a detection worker. Generated separate ignored secrets.
- Added normalized event submission, source-ID deduplication, configurable authentication rules, persisted worker jobs, rule history, alerts, and analyst false-positive feedback. Analyst confirmation links source events to a single incident and writes provenance into the tenant graph.
- Added a three-panel detection workspace, incident source view, and a graph link focused on the confirmed incident. The SQLite seed supplies two rules and a reproducible synthetic five-event scenario.
- Verified 13 isolated tests, lint, TypeScript, and the web build. PostgreSQL migration, Redis persistence, and worker recovery passed with five queued events, two alerts, and idempotent incident confirmation. The earlier browser restriction remains in force.

### Phase 5

- Added additive migration `0003`, source management, bounded JSON/CSV batch intake, scoped expiring keys, replay handling, and persisted row outcomes. Existing detection processing handles authentication observations submitted by a batch.
- Added refund correlation, a three-panel review workspace, structured report export, and analyst confirmation with source event, account, device, refund, and evidence graph links. The isolated SQLite seed now yields three refund observations and three findings on repeat runs.
- Added entity and UTC date filters, bookmark restoration, and connecting paths to the graph. Added evidence inspection, digest re-verification, header signature hints, and audit activity. MERCURY now uses stored refund findings. VERITAS checks the bytes of up to four scoped evidence files.
- Final isolated backend suite passed 16 tests. Frontend lint, the production build, and the explicit TypeScript check passed. Visual browser verification remains pending under the earlier permission restriction.
- Rebuilt both Compose stacks and applied migration `0003` on PostgreSQL. The PostgreSQL/Redis smoke check passed through the authenticated web proxy, including replay, worker detection, cross-tenant denial, and single-incident confirmation. Both local apps are running, and the original SQLite database checksum is unchanged.

### Phase 6

- Added additive migration `0004` for forensic cases, source links, note revisions, file metadata, custody, report snapshots, and durable investigation runs. Existing SQLite user records and the original database were preserved.
- Added assignment and status controls, note revision history, ledger validation, evidence export with an access purpose, and PDF/JSON case reports. Seeded a repeatable synthetic case on the isolated SQLite stack.
- Added dependency and lease processing to the PostgreSQL worker and retained SQLite inline execution. All seven Nexus tasks execute bounded local analysis. VERITAS validates tenant-owned references and records case examinations. Human reviewers record run disposition through Nexus.
- Added the Forensic cases workspace, Evidence Vault case links, Investigation Nexus, and dashboard case and task metrics. The same-origin proxy verifies sessions and attachment responses.
- The isolated backend suite passed 20 tests. Frontend lint, the production build, and the explicit TypeScript check passed. Live checks covered concurrent updates, recovery after an expired worker lease, API and authenticated web exports, and the SQLite pipeline. Phase 5 intake regression also passed.
- Signed-in visual acceptance remains pending and has a walkthrough in `docs/TESTING.md`. The next implementation slice is isolated evidence processing and worker hardening, followed by the provider gateway and cited retrieval.

## 2026-11-26

- Added migration `0005` to store JPEG and standard TIFF header inspection results. Upload and verified read share a bounded child process. The vault and case show allowlisted fields, and reports snapshot them. Original bytes and custody history are preserved.
- Added a PostgreSQL task supervisor with a configurable deadline. The worker terminates overdue child processes, then records the attempt and preserves retry backoff if its task lease is still active.
- Ran 25 isolated backend tests, frontend lint, TypeScript, and the production build. Both stacks were rebuilt. The preserved SQLite file matched its original checksum, and signed-in visual acceptance remains pending.

### Phase 8

- Added migrations `0006`–`0008` for tenant AI settings and usage, versioned knowledge documents, Copilot conversations, reviewed model interpretations, replay lineage, and separate counterfactual snapshots.
- Added four provider adapters with mocked protocol verification, explicit context authorization, bounded requests, and usage accounting. Added functional AI Settings, Knowledge Base, and a cited Copilot workspace.
- Extended Nexus with task selection, prerequisite closure, audited replay, and optional interpretations that preserve source findings. Added four hypothetical refund scenarios backed by the same deterministic factor calculation.
- Passed 34 isolated backend tests, frontend lint, TypeScript, and the production build. Signed-in visual checks and authorized live provider testing remain pending.
- Rebuilt both stacks and verified migration `0008`, tenant-scoped record search, authenticated Copilot exports, replay of a synthetic terminal failure on the PostgreSQL worker, and persisted counterfactual comparisons.

### Phase 9

- Added migrations `0009`–`0011` for workflow versioning and execution, saved topology simulations, and optional document embeddings. The original SQLite checksum matched after rebuilding the local stacks.
- Delivered the Workflow Studio editor and approvals, isolated Digital Twin traversal, and currency-aware business reporting. PostgreSQL smoke checks restarted the worker around a queued workflow and exercised a real tenant-event trigger. SQLite verified inline execution.
- Added local hybrid retrieval with keyword fallback. Tested the OpenAI-compatible, Anthropic, Gemini, and Ollama stream transports with mocks. A live provider and a local embedding model remain unverified. PostgreSQL did not expose a pgvector extension.
- Passed 47 isolated backend tests, frontend lint and type checking, a production build, and smoke checks for Phase 9, AI workspace, intake, and forensics. Updated Phase 9 coverage in the 32-page acceptance matrix. Signed-in visual acceptance remains pending.
- Ran the linked synthetic flagship from authentication and payment/refund ingestion through detections, incident confirmation, EXIF and custody, investigation, cited Copilot record search, a counterfactual, workflow approval, impact simulation, forensic reports, and updated business totals. Added local web health checks and prepared a GitHub Actions verification workflow. Hosted CI execution remains pending.

### PostgreSQL recovery and organization configuration

- Recovered the PostgreSQL stack by using the existing ignored `.env.postgres`; no credentials were exposed or replaced. Existing PostgreSQL, Redis, and evidence volumes were preserved.
- Rebuilt and verified both SQLite and PostgreSQL Compose stacks. PostgreSQL reached Alembic `0012 (head)`, passed `alembic check`, remained healthy for API/web/worker/Redis/PostgreSQL, and passed the isolated worker recovery smoke.
- Added organization timezone, currency, industry, branding, settings, and onboarding persistence plus migration `0012`.
- Added organization settings/onboarding, role-matrix, audit, organization configuration, and protected owner/user administration APIs and frontend workspaces.
- Prevented owner self-deactivation and owner-account deactivation through the organization administration API.
- Complete isolated backend suite: **49 passed** with one existing Starlette/AnyIO deprecation warning.
- Frontend lint, TypeScript, and production build passed. Signed-in visual, live provider, and hosted CI acceptance remain pending.

### Asset management completion slice

- Added migration `0013` and persisted asset assignments, team ownership, lifecycle/change history, and vulnerability remediation records.
- Added tenant-scoped asset detail, assignment, lifecycle update, vulnerability creation/status update, audit, and cross-tenant denial APIs.
- Extended the Asset Inventory UI with an inspector, assignment controls, lifecycle selection, vulnerability records, and change history.
- Both SQLite and PostgreSQL stacks were rebuilt; PostgreSQL reached `0013 (head)` and passed migration parity.
- Full isolated backend suite: **49 passed**. Frontend lint, TypeScript, and production build passed.

### Premium shell and incident assignment

- Added an original favicon, collapsible/sidebar-searched navigation, route-active states, persistent dark/light theme, profile menu, and notification entry in the command shell.
- Added live assignment controls to Incident Manager and a tenant-scoped assignment API with audit history.
- Added migration `0014` for incident assignee and team ownership using a cross-dialect batch migration.
- Both Docker stacks reached migration `0014 (head)` with migration parity. Full isolated backend suite: **50 passed**.

### Threat intelligence completion slice

- Added migration `0015` and persisted IP, domain, URL, and hash indicators with classification, confidence, provenance, expiration, notes, and status.
- Added tenant-scoped indicator create/list/inspect/update/delete APIs, deduplication, audit, and evidence matching against security events, assets, and incidents.
- Replaced the generic threat workspace with a dedicated indicator and match-inspector frontend.
- Both Docker stacks reached migration `0015 (head)` with migration parity.
- Full isolated backend suite: **51 passed**. Frontend lint, TypeScript, and production build passed.

### E-commerce Analytics

- Added tenant-paged commerce transaction search by kind, account, currency, external ID, and order reference.
- Added transaction detail with linked refund findings, evidence references, and tenant-scoped security events.
- Added authorized JSON/CSV commerce exports and role/audit checks.
- Added a dedicated `/platform/ecommerce` workspace with filters, recorded totals, fraud findings, transaction inspection, and CSV export.
- No schema migration was required; both stacks remain deployed at PostgreSQL `0015 (head)`.
- Full isolated backend suite: **52 passed**. Frontend lint, TypeScript, and production build passed.

### Centralized Reports Center

- Added migration `0016` and persistent tenant report metadata/snapshots with source references and SHA-256 integrity hashes.
- Added report generation for forensics, Nexus, security, threat, assets, incidents, fraud, e-commerce, business intelligence, workflow, Digital Twin, and Copilot sources.
- Added report search, category/source filters, pagination, preview, versioning, tenant isolation, and authorized JSON/CSV exports.
- Added the `/platform/reports` workspace with category/source navigation and an integrity-aware preview inspector.
- Both Docker stacks reached PostgreSQL/SQLite-compatible migration `0016 (head)` with parity.
- Full isolated backend suite: **53 passed**. Frontend lint, TypeScript, and production build passed.

### Developer Portal, Observability, and Help Center

- Added migration `0017` and hashed, tenant-scoped, scoped, expiring, revocable API credentials with one-time secret issuance and usage counters.
- Added Developer API Portal endpoint catalog, scope selection, credential management, revocation, and actual route examples.
- Added tenant-admin Observability status using live database, Redis, worker heartbeat, queue, execution, ingestion, and report measurements.
- Added a searchable categorized Help Center based on implemented functionality and known limitations.
- PostgreSQL reached `0017 (head)` with migration parity and both stacks remained healthy.
- Complete isolated backend suite: **55 passed**. Frontend lint, TypeScript, and production build passed.

### Persistent notifications

- Added migration `0018` and account/tenant notification persistence with category, deep-link, dedupe key, unread/read state, and filtering.
- Added unread-count, mark-read, and mark-all-read APIs.
- Connected incident assignment, asset assignment, and report completion to persisted notification emission.
- Added a Notification Center UI and live shell unread indicator.
- PostgreSQL reached `0018 (head)` with migration parity. Complete isolated backend suite: **56 passed**.
