# VYRNEXIS AI Implementation Status

Last updated: 2026-11-26

## Delivered

- The command center charts received security events, created alerts, and opened incidents over 7 or 30 UTC days. Selecting a day shows the underlying tenant counts. PostgreSQL and SQLite display their actual database engine.
- Next.js / TypeScript frontend and FastAPI / SQLAlchemy backend with SQLite local development.
- Argon2id passwords; short-lived signed access tokens; seven-day server-tracked refresh sessions; single-use refresh rotation; replay denial; session revocation; active-user checks; required production JWT secret.
- Protected dashboard, incident, intelligence, evidence, workflow, graph, and bookmark routes. Tenant scope comes from the authenticated user. Supported write routes enforce roles, and relationship/evidence/bookmark object references are checked within the same organization.
- Evidence Vault with role-checked uploads, tenant-scoped metadata and downloads, atomic writes outside the web root, and SHA-256/SHA-512 verification. Files registered to forensic cases have an application-level custody ledger. Immutable object storage and malware scanning remain open.
- Audit entries for registration, session lifecycle, and supported domain writes.
- Same-origin Next.js auth BFF with HttpOnly, SameSite=Strict token cookies; protected dashboard, intelligence graph, bookmark, and incident proxies; role-filtered dashboard navigation.
- Responsive command center backed by persisted API records, with incident filtering and explicitly unavailable posture scoring.
- Interactive intelligence investigation workspace: search, relationship filtering, zoom/pan, minimap, layouts/grouping, node and edge inspectors, timeline selection, bookmarks, fullscreen, and JSON export. Its data and bookmarks come from tenant-scoped API routes.
- Incident Manager with authenticated tenant-scoped listing, search, severity filtering, persisted counts, role-checked incident creation, validated status transitions, and an audited event timeline API.
- Asset inventory vertical slice with tenant-scoped persistence, role-checked/audited creation, name/type/identifier search, lifecycle filters, and responsive inventory UI. Vulnerability management, discovery/connectors, assignment, and asset change history remain incomplete.
- Security Operations ingests and deduplicates submitted authentication events, evaluates configurable failed-sign-in and unfamiliar-device rules, and persists rule runs, alerts, and analyst feedback. The three-panel workspace shows rule settings, alert severity, the review queue, and linked source events. External feeds, saved layouts, and bulk review remain open.
- Analyst confirmation creates at most one incident per alert and retains the reviewed event set. The incident and its reported account/device relationships can be opened directly in the graph. Incident status appears on the linked alert.
- The isolated PostgreSQL stack runs PostgreSQL, Redis, the API, the frontend, Alembic, and a background detection worker. The default SQLite stack remains available and evaluates rules inline. Both stacks use localhost bindings and separate data.
- Phase 5 adds JSON and CSV batch intake for security, payment/refund, and asset observations. It includes bounded requests, row validation reports, provenance, source-level idempotency, expiring webhook keys, and a functional Data Sources workspace.
- Fraud Intelligence stores refund findings with explicit weighted factors, a chronological source timeline, currency totals, evidence references, and a JSON report. Confirmation creates one incident per finding with links to the related graph. Analyst dismissal records feedback.
- The graph supports entity and UTC date filters, saved filter restoration, and connecting paths within the current view. The Evidence Vault verifies both stored digests and shows a signature hint and audit activity. MERCURY reads persisted refund findings and VERITAS rehashes up to four scoped evidence files.
- Seven executable deterministic local analysis agents with role-gated execution, tenant-scoped persisted inputs/outputs, incident scoping, audit history, evidence references, explicit limitations, and a functional execution-history UI. Provider/model inference remains unavailable until configured.
- Phase 6 adds assigned forensic cases, controlled transitions and reopening, linked records, revisioned notes, hashed custody events, and versioned PDF/JSON case reports through the forensic workspace.
- Investigation Nexus stores runs, task dependencies, leases, retry attempts, findings, and human review decisions. The PostgreSQL worker processes all seven analyzers and the SQLite stack supports inline execution. The dashboard reports live counts from the authorized API.
- JPEG and standard TIFF header inspection records allowed image dimensions, orientation, and embedded capture time in the vault, case inspector, and new reports. The inspector has process, input, and time bounds. PostgreSQL runs each Nexus task under a supervised execution deadline.
- AI Settings stores tenant model policy and usage. OpenAI-compatible, Anthropic, Gemini, and Ollama adapters share bounded transport and structured output validation. Adapter tests use mocks.
- Knowledge Base indexes authorized TXT, Markdown, CSV, JSON, PDF, and DOCX. It stores document versions, visibility, expiry, and passage provenance. Copilot stores account-owned conversations with incident or forensic case context and clickable citations.
- Nexus supports selective execution with prerequisite closure, replay lineage for failed and timed-out tasks, and separately reviewed model interpretations of completed findings when hybrid mode is authorized.
- Fraud Intelligence stores hypothetical scenario comparisons independently of the original findings, source evidence, and incidents.
- Branded sign-in and organization registration pages with accessible labels and error announcements.
- Isolated synthetic seed at `.dev-logs/vyrnexis-demo.db`. The existing `vyrnexis.db` is preserved. Demo-user creation prompts for a password and stores only its Argon2id hash.
- Architecture, security notes, threat model, local run instructions, and bounded test script.

- Workflow Studio has a visual editor, immutable publication, seven executable templates, manual and dry-run execution, scheduled and tenant-event triggers in PostgreSQL, human approvals, history, cancellation, and replay.
- Digital Twin renders explicitly recorded dependencies and saves outage or isolation simulations with reproducible snapshots, paths, mitigation comparisons, and JSON exports.
- Business Intelligence reports payments, refunds, net recorded amounts, and refund rates by original currency, with period comparisons, account and review breakdowns, and CSV/JSON export.
- Knowledge Base supports opt-in local embeddings with bounded hybrid retrieval and keyword fallback. Copilot supports native provider response streams with provisional text and citation validation before saving an answer.

## Verification performed

- PostgreSQL recovery completed using the existing `.env.postgres` and named volumes. Both stacks are rebuilt; PostgreSQL reached Alembic `0012 (head)` with migration parity, API and worker health passed, Redis recovery smoke passed, and anonymous organization/admin API requests returned `401`. Live landing routes returned HTTP 200.
- Organization onboarding/settings and role/audit workspaces passed **18 focused API and migration tests**. Migration 0012 adds organization profile, timezone, currency, industry, branding, settings, and onboarding persistence while preserving existing organizations.
- The complete isolated backend suite passed **49 tests**. Frontend lint, TypeScript, and production build passed. The PostgreSQL/Redis worker recovery smoke passed again at revision `0012 (head)`. The original `vyrnexis.db` checksum remains `65B421B1D4C3D41AC831C3DB2DFECBA3D4F7BDB66347EBE90AAA4A28B3EA826A`.
- Asset assignment, lifecycle, history, and vulnerability work passed focused API/migration tests and both stacks reached migration `0013 (head)` with `alembic check` parity. The complete isolated backend suite passed **49 tests**.
- Premium shell, sidebar search/collapse, theme selector, profile menu, favicon, and incident assignment work passed frontend lint/type/build and 19 focused API/migration tests. PostgreSQL reached `0014 (head)` with parity. The complete isolated backend suite passed **50 tests**.
- Threat indicator persistence, matching, deduplication, and reclassification passed 20 focused API/migration tests. PostgreSQL reached `0015 (head)` with parity. The complete isolated backend suite passed **51 tests**.
- E-commerce transaction search, pagination, detail, cross-tenant isolation, fraud linkage, and CSV/JSON export passed 22 focused commerce/API tests. No new database migration was required; PostgreSQL remains at `0015 (head)` with parity. The complete isolated backend suite passed **52 tests**.
- Reports Center registry, versioning, tenant isolation, preview, integrity, JSON/CSV export, and migration 0016 passed 21 focused report/migration tests. PostgreSQL reached `0016 (head)` with parity. The complete isolated backend suite passed **53 tests**.
- Developer API credentials, scoped read enforcement, revocation, Observability, and Help Center passed 23 focused platform/API/migration tests. PostgreSQL reached `0017 (head)` with parity. The complete isolated backend suite passed **55 tests**.
- Persistent notifications passed account/tenant isolation, dedupe, unread, mark-read, and migration 0018 coverage. PostgreSQL reached `0018 (head)` with parity. The complete isolated backend suite passed **56 tests**.
- Phase 10 missing-page implementation: isolated API coverage passed **16 tests** for the test module, including tenant-scoped admin user creation and role-restricted admin APIs. The production frontend build passed, and the seven previously unimplemented pages now have source implementations backed by persisted or explicit-unavailable data. Signed-in visual acceptance remains pending.
- Phase 10 retrieval continuation: the isolated AI and semantic suites passed **10 tests**. Copilot now consumes tenant-scoped keyword and optional hybrid ranking, deduplicates source keys, records retrieval audit entries, and revalidates current document chunks and permissions when resolving historical turns. Revoked, deleted, and changed-version document citations are excluded.
- Phase 9 passed **47 isolated backend tests**, frontend lint, TypeScript, and a production build. Coverage includes authorization, graph validation and replay, worker scheduling, simulation integrity, reporting totals, embedding visibility and deletion, and all four native stream protocols with mocked transports.
- Both local stacks were rebuilt and returned HTTP 200 for the five Phase 9 workspace routes. Live smokes exercised approval and source-record isolation on both stacks, plus PostgreSQL migration `0011`, worker recovery, tenant-event triggering, authenticated web proxy access, and cross-origin rejection. Forensics, AI workspace, and intake regressions passed. The original SQLite checksum matches its pre-change value.
- The linked PostgreSQL synthetic demonstration passed from intake to both detections, a confirmed refund incident, assigned case, EXIF and custody, seven Nexus tasks, evidence citations, a counterfactual, workflow approval, Digital Twin simulation, PDF and JSON reports, and a Business Intelligence update from the same tenant's submitted payment.
- Live generation and embedding providers remain unconfigured. Keyword fallback was verified on both stacks. Signed-in visual and assistive-technology checks are still pending.

- Phase 8 isolated suite passed **34 tests** with the existing Starlette/AnyIO deprecation warning. Focused checks cover adapter protocols, spending and consent gates, private document and conversation isolation, citation revocation, document extraction, cancellation, hybrid interpretation, replay lineage, and hypothetical factor changes. Frontend lint, TypeScript, and production build passed.
- Both local stacks were rebuilt. PostgreSQL reached `0008` and Alembic reported schema parity. Live checks covered indexed retrieval, cited Copilot export, tenant isolation, an authenticated proxy request, targeted replay with original attempt preservation, and persisted hypothetical comparisons. Provider protocol verification used mocks.

- Phase 6 continuation: **25 isolated backend tests passed**. New checks cover JPEG and TIFF headers, malformed and out-of-bounds metadata, inspection timeouts, sensitive tag exclusion, original digests and bytes, tenant isolation, case report snapshots, and worker process timeout with retry. Frontend lint, TypeScript, and the production build passed.
- Both local stacks were rebuilt with EXIF support, and PostgreSQL applied `0005`. The smoke test confirmed metadata and original exports on both stacks and through the authenticated web proxy. Signed-in visual inspection remains pending.

- Phase 6 isolated suite: **20 passed** with the existing Starlette/AnyIO deprecation warning. New coverage includes role-checked assignment and custody transfer, note revision history, tamper detection, authorized PDF/JSON export, case and run isolation, worker lease recovery, idempotency, cancellation, and human review. Frontend lint, TypeScript, and production build passed.
- Phase 6 runtime: both localhost stacks were rebuilt. PostgreSQL reached `0004` and Alembic reported schema parity. Integration checks exercised concurrent writes, custody export and VERITAS examination, worker restart and retry, seven persisted findings, human review, PDF/JSON exports, the authenticated web proxy, and SQLite inline execution. The Phase 5 intake smoke test also passed after the Phase 6 changes.
- The isolated demo seed is repeatable and creates one forensic training case with two custody entries for the synthetic file when the demo owner is present. The preserved SQLite database matched the original SHA-256 checksum. Signed-in visual verification of Phase 6 remains pending.

- Phase 5 isolated suite: **16 passed** with one pre-existing Starlette/AnyIO deprecation warning. New coverage includes row validation, batch replay and deduplication, scoped and revoked keys, per-source rate limiting, currency totals, correlation, idempotent confirmation, evidence tampering, and cross-tenant graph denial. Frontend lint, TypeScript, and the production build passed.
- Phase 5 runtime: the PostgreSQL stack reached Alembic `0003` with no pending schema changes. The integration check verified partial batch acceptance, replay, Redis worker processing, refund matching, cross-tenant denial, incident/graph provenance, and retrieval through the authenticated web proxy. Both localhost stacks served the new pages and rejected anonymous findings requests. The original SQLite SHA-256 checksum matched its pre-change value.

- Phase 4 isolated backend suite: **13 passed**, including detection, source deduplication, alert review, repeat incident confirmation, graph links, tenant isolation, and migration preservation. Lint, the TypeScript check, and the production build passed.
- Live PostgreSQL and Redis smoke test: Alembic reached `0002` with no pending schema changes. An API session, five queued detection jobs, and a Redis test marker survived service restarts. The restarted worker produced two alerts and exactly one incident after repeat confirmation.
- Signed-in visual verification of the Phase 4 changes remains pending. The previously declined browser permission was respected.

- Backend: latest isolated pytest suite completed with **10 passed, 1 warning**. The security event test covers ingestion, timestamp normalization, filters, reviewed status persistence, duplicate review requests, cross-tenant access, viewer restrictions, and audit entries. Existing auth, asset, incident, graph, evidence, and agent tests also passed. The warning is Starlette's AnyIO `BlockingPortal` deprecation.
- Test-runner diagnosis: the initial restricted run stalled while Starlette `TestClient` created a local socket pair. The same bounded suite returned results when run with local socket access. Fixtures first redirect import-time DB creation to a temporary SQLite file, then use a fresh per-test SQLite DB; the production database is not used.
- Frontend lint: `npm.cmd run lint` passed after the dashboard JSX repair and authentication-page changes.
- TypeScript: `npm.cmd exec tsc -- --noEmit` passed.
- Production build: `npm.cmd run build` passed after stopping the project-owned dev servers that shared the `.next` output directory.
- Frontend after agent control center and incident status controls: lint, TypeScript check, and an isolated production build passed. Build output used `.next-verify` while the default output directory was unavailable.
- Asset frontend: lint (`eslint src`), TypeScript (`npm exec tsc -- --noEmit`), and production build with Next.js 15.5.29 passed. The frontend dependency install reported zero npm vulnerabilities; Docker rebuilt the API/web images with these sources.
- Security Operations frontend: lint, production build, and TypeScript passed. Docker rebuilt both images, and the API health check reached healthy. Both host ports are bound to loopback. Anonymous event requests returned 401 at both the API and web proxy. Authenticated browser verification of the new page is pending because browser access was declined.
- Browser: production sign-in page at `http://127.0.0.1:3000/login` visibly renders the branded dark theme and form.
- Browser/API: visiting `/platform/incidents` without a session redirects to `/login`; anonymous `GET /api/incidents` returns `401 Sign-in required`.
- Docker Compose: API and web containers are running; the web login returns 200 and API `/health` returns 200. Anonymous requests to `/api/v1/agents` and `/api/v1/evidence` return 401. Compose uses `.dev-logs/vyrnexis-demo.db` and `.dev-logs/evidence`; the existing `vyrnexis.db` is not mounted. A random local key is kept in ignored `.env` for stable restarts. Port 8000 is used only inside the API container; host port 8001 maps to it.
- Frontend dependency audit: Next.js and eslint-config-next are pinned to 15.5.29, PostCSS override is 8.5.23, Sharp is 0.35.5, and `npm audit` reports zero vulnerabilities.
- Authenticated browser: owner signed in and the live dashboard loaded the synthetic cross-domain scenario (6 entities, 5 recorded relationships, and incident/evidence records). Incident creation persisted across refresh; search and severity filtering worked. Graph neighbor expansion loaded persisted relationships. SENTINEL execution was saved with record references and its deterministic/provider-unconfigured limitations. Evidence inventory rendered. Sign-out returned to sign-in, and a protected route redirected to sign-in. Asset creation persisted across refresh; name search and the active-status filter worked. Cross-tenant and role restrictions are covered by backend tests; multi-role browser testing and token-expiry UX remain unverified.

## Page acceptance matrix

Current coverage counts: 1 implemented and verified, 31 implemented but partially verified, 0 in progress, 0 unimplemented, totaling 32 pages.

The master specification names 32 pages. The state column reflects tested functionality and remaining acceptance work.


| # | Page | State | Functional coverage |
|---:|---|---|---|
| 1 | Public landing page | Implemented but partially verified | Branded `/landing` route with sign-in and organization registration actions; visual acceptance pending. |
| 2 | Authentication | Implemented and verified | API session and role tests, owner sign-in, and sign-out checks. |
| 3 | Organization onboarding | Implemented but partially verified | Tenant configuration, timezone, currency, industry, persisted onboarding checklist, and audit-backed saves are implemented; full invitation and team workflow remains open. |
| 4 | Enterprise dashboard | Implemented but partially verified | API-backed baseline passed owner browser checks. The 7/30-day UTC activity chart and database label have API and build coverage. Signed-in chart acceptance and saved views remain open. |
| 5 | Intelligence command center | Implemented but partially verified | Dashboard and authenticated graph workspace are available. |
| 6 | AI agent management | Implemented but partially verified | Seven deterministic agents, persisted runs, replay, and optional reviewed model interpretations. Live providers and per-agent configuration remain open. |
| 7 | Security operations center | Implemented but partially verified | Detection, analyst queue, source inspection, rule settings, and incident linking have API coverage. External connectors remain open. |
| 8 | Threat intelligence | Implemented but partially verified | Persisted IP/domain/URL/hash indicators, analyst classifications, confidence and provenance, expiration, notes, deduplication, tenant matching against security events/assets/incidents, and a dedicated workspace are implemented; imports/graph export remain open. |
| 9 | Incident management | Implemented but partially verified | Listing, creation, transitions, source links, tenant assignment, team ownership, assignment history, and member assignment controls are implemented; workload and notification views remain open. |
| 10 | Asset management | Implemented but partially verified | Tenant asset persistence, search, lifecycle filters, assignment, team ownership, change history, vulnerability records, and remediation status are implemented; discovery/import and relationship visualization remain open. |
| 11 | Digital forensics laboratory | Implemented but partially verified | Case assignment, notes, custody, EXIF inspection, and versioned reports. Saved views and visual acceptance remain open. |
| 12 | Evidence vault | Implemented but partially verified | Protected storage, digest verification, image metadata, and case custody export. Immutable storage remains open. |
| 13 | Investigation workspace | Implemented but partially verified | Linked graph, forensic cases, selective Nexus replay and review, and commerce counterfactuals. Signed-in visual acceptance remains open. |
| 14 | E-commerce analytics | Implemented but partially verified | Dedicated tenant commerce workspace with search, kind/account/currency filters, paginated transactions, transaction detail, fraud/evidence context, recorded payment/refund totals, CSV/JSON export, and cross-tenant tests; merchant/customer profiles and trend charts remain open. |
| 15 | Fraud intelligence | Implemented but partially verified | Refund and authentication correlation, source timeline, exports, analyst confirmation, and hypothetical scenarios. Trend charts remain open. |
| 16 | Business intelligence | Implemented but partially verified | Recorded payment and refund analytics, period comparison, currency filters, and CSV/JSON export passed API checks. Signed-in visual acceptance and additional measures remain open. |
| 17 | Digital twin simulator | Implemented but partially verified | Dependency inspection and isolated outage/isolation simulations with saved mitigation comparisons passed API checks. Signed-in visual acceptance remains open. |
| 18 | Workflow automation builder | Implemented but partially verified | Visual editor, publication, approvals, indexed history, replay, and PostgreSQL triggers passed API or worker checks. Webhook triggers and signed-in visual acceptance remain open. |
| 19 | AI copilot | Implemented but partially verified | Account-scoped conversations, cited keyword context, JSON export, and native streaming tested with mocked providers. Live provider and signed-in visual acceptance remain open. |
| 20 | Data source management | Implemented but partially verified | Sources, bounded CSV/JSON intake, scoped keys, history, and row reports. Mapping and scheduled retry remain open. |
| 21 | Integration marketplace | Implemented but partially verified | Live tenant data-source inventory and persisted integration status; browser acceptance pending. |
| 22 | Reports center | Implemented but partially verified | Persisted report registry, tenant-owned snapshots, source-module/version metadata, integrity hashes, search/filter/pagination, preview, JSON/CSV export, audit, and cross-tenant tests are implemented; PDF, review workflows, and background generation remain open. |
| 23 | Notification center | Implemented but partially verified | Persistent account/tenant notifications, dedupe keys, categories, unread counts, mark-read/read-all, assignment/report domain emission, deep links, and cross-account isolation tests are implemented; preference/external delivery remains open. |
| 24 | User management | Implemented but partially verified | Owner/admin tenant user listing, creation, role updates, activation, and session revocation; browser acceptance pending. |
| 25 | Role and permission management | Implemented but partially verified | Server role checks, role inventory, effective-permission descriptions, owner/user protection, and tenant role assignment APIs are implemented; custom concurrent-admin workflows remain open. |
| 26 | Audit logs | Implemented but partially verified | Tenant audit API and immutable audit viewer are implemented with search; date/action pagination and export remain open. |
| 27 | Subscription and billing | Implemented but partially verified | Workspace explicitly reports that no subscription provider is configured and shows real AI settings only; no fabricated billing data. |
| 28 | Organization settings | Implemented but partially verified | Organization profile, timezone, currency, industry, branding/settings JSON, onboarding state, and audited configuration updates are implemented; advanced security and retention policies remain open. |
| 29 | Developer API portal | Implemented but partially verified | Actual OpenAPI-backed endpoint catalog, scoped hashed API credentials, one-time secret issuance, expiration, revocation, usage counters, tenant isolation, and premium UI are implemented; live usage-history and webhook history remain open. |
| 30 | Super administrator dashboard | Implemented but partially verified | Organization-scoped platform status for owners/admins; no cross-tenant access; browser acceptance pending. |
| 31 | System health and observability | Implemented but partially verified | Live database, Redis, worker, queue, agent/workflow/Nexus/report, ingestion measurements and a dedicated UI are implemented; historical latency and resource telemetry remain open. |
| 32 | Documentation and help center | Implemented but partially verified | Searchable categorized help center based on implemented modules and known limitations is available; contextual help and expanded repository article coverage remain open. |

## Security and platform limitations

- Security controls have automated local test coverage but have not received an independent review. Do not expose this build as a production service.
- General authentication throttling, MFA, password recovery, invitations, SSO/OIDC, multi-organization membership, CSP, and session management UI remain open.
- SQLite retains additive `create_all` startup. Alembic manages the separate PostgreSQL schema. Data import from the existing SQLite database and production migration rehearsal remain open.
- Evidence bytes are stored locally. Custody hashes detect inconsistent application records. Independent integrity anchoring, immutable storage, and malware scanning remain open.
- Nexus uses a dependency catalog with optional task selection and bounded worker leases. PostgreSQL tasks have hard process deadlines. Live provider and local embedding-service verification, retrieval quality evaluation, hosted CI execution, OpenTelemetry, backup restore drills, and deployment validation remain open.
- Current frontend navigation still points many unfinished module names at a generic workspace. Do not treat those routes as implemented pages.

## Phase 9 source changes

| Area | Source files |
| --- | --- |
| Workflow Studio | `apps/api/app/workflow_engine.py`, `apps/api/app/workflow_studio.py`, `apps/web/src/components/WorkflowWorkspace.tsx` |
| Digital Twin and Business Intelligence | `apps/api/app/digital_twin.py`, `apps/api/app/business_intelligence.py`, `apps/web/src/components/DigitalTwinWorkspace.tsx`, `apps/web/src/components/BusinessIntelligenceWorkspace.tsx` |
| Retrieval and Copilot | `apps/api/app/semantic.py`, `apps/api/app/knowledge.py`, `apps/api/app/provider_stream.py`, `apps/api/app/copilot.py`, `apps/web/src/components/KnowledgeWorkspace.tsx`, `apps/web/src/components/CopilotWorkspace.tsx` |
| Runtime and routing | `apps/api/app/main.py`, `apps/api/app/models.py`, `apps/api/app/detection_worker.py`, `apps/web/src/app/api/workspace/[...operation]/route.ts`, `apps/web/src/app/platform/[module]/page.tsx`, `apps/web/src/app/page.tsx`, `apps/web/src/app/globals.css`, both Compose files |
| Migrations | `apps/api/migrations/versions/0009_workflow_studio.py`, `0010_twin_simulations.py`, `0011_local_knowledge_embeddings.py` |
| Verification | `tests/test_workflow_studio.py`, `tests/test_twin_business.py`, `tests/test_semantic.py`, `tests/test_provider_stream.py`, `tests/test_migrations.py`, `scripts/smoke_phase9.py`, `scripts/smoke_flagship.py`, `scripts/smoke_intake.py`, `scripts/smoke_ai_workspace.py`, `scripts/test.ps1`, `.github/workflows/verify.yml` |

## Current local URLs

- PostgreSQL frontend: `http://localhost:3001`
- PostgreSQL API docs: `http://127.0.0.1:8002/docs`

- Frontend: `http://127.0.0.1:3000` (production build)
- Sign in: `http://127.0.0.1:3000/login`
- API health: `http://127.0.0.1:8001/health`
- API docs: `http://127.0.0.1:8001/docs`

The SQLite demo uses `demo.admin@vyrnexis-demo.org` and the password chosen at the local prompt. Use the instructions in [README.md](README.md) to seed a fresh isolated demo database.
