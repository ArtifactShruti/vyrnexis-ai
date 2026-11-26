# Security Notes

## Implemented controls

- Argon2id password hashing through `argon2-cffi`.
- HS256 signed access and refresh tokens. Production mode requires an operator-provided secret with at least 32 characters; use a managed secret store and a randomly generated value.
- Fifteen-minute access tokens and seven-day refresh sessions. Refresh JTIs are stored as SHA-256 hashes, rotated atomically, and rejected after replay. Logout revokes the server-side session.
- Active user and session state are rechecked for every protected API request. Tenant scope comes from the user record, not from client input.
- Role checks protect create operations for incidents, intelligence records, evidence, and workflows. Relationship endpoints verify both entities belong to the user's organization. Evidence case links are checked against the same organization.
- Asset listing is tenant-scoped and validates an optional organization filter; writes require an allowed role and successful creation is audited. Cross-tenant reads/writes and viewer denial are covered by isolated tests.
- Security event ingestion and review require a write role. The API scopes event reads and updates to the signed-in organization and audits both actions.
- Detection rules and alert actions enforce organization and role checks. Alerts require analyst confirmation to create an incident. Confirmation is idempotent and commits the incident, source links, graph links, and audit entry together.
- The alternate Compose stack generates separate database, Redis, and signing credentials in ignored `.env.postgres`. Data services and the worker use a private network. Only the web and API ports bind to localhost. Redis wake messages contain no telemetry or credentials.
- Batch intake enforces source ownership, source-specific write roles, payload and row limits, and a per-source batch rate limit. Webhook keys expire and can be revoked. Only the digest of each high-entropy key is stored. Keys grant submission to one source and cannot authenticate to other routes.
- Commerce accepts reported account/device labels, references, and integer amounts. It has no raw card fields or payment execution. Confirmation and dismissal require analyst authorization. Scores represent configured rule weights.
- Evidence verification rehashes bounded stored bytes. Signature hints come from file headers. Exports serve the same bytes that passed both digest checks and force attachment handling. Registered files use tenant-scoped custody events and can be exported only through the case workflow.
- Owners and organization admins assign or reopen cases. Forensic writers manage notes and custody, with transfer and archive restricted to the current custodian or an admin. Stale versions and sequence numbers fail, and the upload reference, case, and custodian must all belong to the tenant.
- An investigation task checks the requesting account's active tenant membership and role before analysis and again before committing a result. Lease tokens prevent late or cancelled task output from being published. Case and Nexus exports use the authenticated same-origin proxy with no-store responses.
- The image metadata process receives at most 512 KiB, times out after two seconds, and caps concurrent inspections per API process and directory entries per file. Linux adds CPU and address space limits. It reads only header data and stores allowlisted fields. Source bytes, pixels, EXIF device identifiers, and GPS fields are excluded from the derived record.
- The PostgreSQL worker enforces a subprocess deadline before the database lease expires. The supervisor kills and reaps the expired process and records a timed-out attempt if its lease still matches.
- The AI gateway receives credentials only via server configuration. Client requests cannot specify provider endpoints. Redirects are disabled, and external connections require HTTPS. The API applies an operator opt-in, tenant policy, serialized usage reservation, request limits, and per-request acknowledgement before sending sources.
- Knowledge ownership, visibility, and expiry are checked before retrieval and when reusing citations. Copilot conversations are account-owned inside the tenant. Deletion removes indexed rows or conversation history from the application database. Deployment backup retention remains an operator responsibility.
- Knowledge file parsing uses a bounded child process. Uploads and provider output render as text. Models have no application mutation tools or arbitrary commands. Citation validation checks the selected source keys.
- Investigation replay requires a forensic writer and a terminal source run with a failed or timed-out task. The new run keeps separate attempts. Counterfactuals check tenant ownership of both the finding and any excluded source event, and write only a separate scenario snapshot and audit event.
- Browser tokens are held in HTTP-only, `SameSite=Strict` cookies by the same-origin Next.js API routes.
- Evidence uploads are limited to 25 MiB, stored outside the web root under a server-generated tenant/object path, hashed with SHA-256 and SHA-512, and never executed. Downloads are tenant-scoped and recheck both digests before serving.
- Authentication/session creation, rotation, revocation, and supported domain mutations write audit entries.
- Pytest uses isolated temporary SQLite databases; tests include anonymous denial, role denial, cross-tenant denial, refresh rotation, revocation, and graph bookmark/traversal isolation.

- Workflow execution uses an allowlisted node catalog, server-derived tenant access, immutable published revisions, idempotent requests, and audited decisions. The worker enforces bounded steps and rechecks authorization before execution. Operational source access stays read-only.
- Digital Twin checks entity ownership and records isolation assumptions as snapshots. Business Intelligence and its exports use authorized tenant queries and omit raw payment card data.
- Local embedding jobs require deployment configuration and explicit document indexing consent. Search enforces tenant, current version, visibility, and expiry before ranking. Copilot shows provisional text until its final output and citation identifiers pass validation.

## Required operational controls

- Keep the development server bound to loopback. Do not expose a development API to an untrusted network.
- Configure `ENVIRONMENT=production`, `JWT_SECRET`, `DATABASE_URL`, CORS origins, HTTPS termination, backup, and monitoring before deployment.
- Review logs and audit retention for the deployment's data handling requirements.
- The SQLite demonstration database contains synthetic data only. `scripts/seed_demo.py --create-demo-user` prompts for a local password and stores only its Argon2id hash.

## Known gaps

Rate limiting, MFA, password reset, account recovery, OIDC/SSO, API keys, session management UI, organization invitations, multi-organization membership, security headers/CSP, separated PostgreSQL application and migration roles, immutable object storage, malware scanning/isolation, and independent security review remain open. Evidence files need protected backups and a stable `VYRNEXIS_EVIDENCE_DIR`. Production readiness and compliance certification are outside the verified local scope.

Custody chains and report hashes are application-level integrity checks. Anyone with unrestricted database write access could rewrite rows and regenerate digests. Independent integrity anchors, retention locks, provenance attestation, and task memory quotas remain pending. Derived image metadata may contain inaccurate claims supplied by the original file.
