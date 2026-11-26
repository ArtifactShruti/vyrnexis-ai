# Verification and test guide

Backend tests must use isolated temporary databases. From the repository root:

```powershell
$env:PYTHONPATH = 'apps/api'
$env:DATABASE_URL = 'sqlite:///./.dev-logs/vyrnexis-test-bootstrap.db'
python -m pytest -q
```

The pytest fixture redirects API initialization and each test to temporary SQLite files. The project database is not a test target. Coverage includes authentication/session lifecycle, tenant and role restrictions, audit events, asset persistence/filtering/tenant checks, evidence upload/list/download and digest checks, graph traversal/bookmarks, incident transitions/history, and agent execution/history isolation. Evidence files are written to a per-test temporary storage root.

Frontend checks from `apps/web`:

```powershell
npm.cmd run lint
npm.cmd exec tsc -- --noEmit
npm.cmd run build
```

If a production server currently uses `.next`, use a separate output directory for build verification:

```powershell
$env:NEXT_DIST_DIR = '.next-verify'
npm.cmd run build
Remove-Item Env:NEXT_DIST_DIR
```

End-to-end browser checks require an owner seeded into `.dev-logs/vyrnexis-demo.db` and a password entered locally at the masked prompt. Never use chat to transfer the password. Verify sign-in, dashboard, incident create/search/severity/persistence, graph traversal and controls, agent execution/history, logout, anonymous denial, cross-tenant denial, and role restrictions. Automated API tests do not prove browser authentication.

Docker Compose maps host port 8001 to the API container's port 8000; it does not bind host port 8000. Start or rebuild with `docker compose up -d --build`; Compose reads a persistent local `JWT_SECRET` from ignored `.env`. The stack mounts only the isolated demo database and evidence directory. On 2026-11-25, `/login` and API `/health` returned 200, anonymous agent/evidence routes returned 401, and both containers remained running.

Authenticated browser checks were completed on 2026-11-25: owner sign-in and API-backed dashboard, incident creation surviving refresh, text and severity filters, graph neighbor expansion, deterministic SENTINEL execution/history, evidence inventory, asset creation surviving refresh with search/status filters, sign-out, and redirect from a protected route to sign-in. Backend tests cover role/cross-tenant authorization; an additional-role browser session and token-expiry UX are not verified.

Security Operations has isolated API coverage for event ingestion, filters, status changes, audit records, role checks, and tenant isolation. The rebuilt Docker stack passed its API health check and returned 401 for anonymous event requests through both the API and the web proxy. The new page still needs a signed-in browser check.

## PostgreSQL and detection integration

Start the dedicated local stack with `./scripts/start-postgres.ps1`, then run `python scripts/smoke_postgres.py` from the repository root. The smoke check creates a synthetic organization, pauses its stack's worker, queues five observations, and restarts that stack's PostgreSQL and Redis services. It checks Alembic head, recovery, Redis persistence, two generated alerts, and single-incident confirmation. The SQLite stack and original database are outside the test.

Run `python scripts/smoke_intake.py` against the same PostgreSQL demo stack after building Phase 5. It registers isolated synthetic organizations, submits a batch, checks partial failure and replay, waits for worker processing, links refunds to authentication, verifies tenant isolation and single-incident confirmation, and reads the finding through the authenticated web API.

Run `python scripts/smoke_forensics.py` with both local demo stacks running. It creates isolated synthetic organizations, checks Alembic head and schema parity, races two case edits and two custody requests, and validates byte export. It briefly stops the PostgreSQL demo worker, expires a synthetic lease, and restarts the worker to check retries, all seven findings, the VERITAS examination event, and human review. It checks PDF and JSON exports, EXIF extraction on both stacks, original image byte preservation, and the authenticated web proxy. The isolated test suite also checks a real slow child process under the task supervisor's deadline.

## Pending signed-in visual acceptance

Browser permission remains restricted. Capture non-sensitive screenshots under `artifacts/screenshots` only if browser access is granted.

- At 1920×1080, 1440×900, and 1280×800, check that source inventory, batch results, and webhook controls fit and remain readable. Upload JSON and CSV with one bad row and confirm the counts and row detail match.
- At 768×1024 and 390×844, check panel reflow, keyboard focus, search, file selection, and long identifiers. Confirm that controls fit without horizontal page overflow.
- In Fraud Intelligence, review the synthetic finding, compare the factors with the chronological source timeline, export the report, and confirm that repeat confirmation links to the same incident.
- Follow the incident into the graph. Try entity/time filters, bookmark restoration, and the connecting path view. Use the Evidence Vault to verify the linked file and inspect the audit activity.
- Check loading, empty states, validation errors, session expiration, browser console, and failed requests at each size.

## Phase 8 checks

Run `python scripts/smoke_ai_workspace.py` with both local stacks running. It verifies additive schema parity, authorized keyword indexing, private document isolation, persistent Copilot answers and exports, the authenticated web proxy, and a worker replay of a synthetic timed-out task. The integration test uses record-search mode. Run `python scripts/smoke_intake.py` to verify correlation and a persisted hypothetical comparison.

For signed-in browser acceptance, use the five sizes listed above and the isolated owner account. Check the following workflows.

1. Open **AI settings** and change a token or timeout value. Save and refresh. Confirm a non-admin cannot read the settings and that no keys or provider base URLs appear in the response. Test an actual connection only with an explicitly authorized configured model.
2. Open **Knowledge base**, index a synthetic policy, look up a known term, and inspect its cited version and passage. Upload a new version, change visibility, and verify access with a separate same-tenant account. Check the removed citation after the document is deleted.
3. Open **Copilot**, create an incident- or case-scoped conversation, and ask a specific record question. Open cited sources, refresh, search the conversation title, and export JSON. With an authorized provider, check consent, then test generation and stop. Check keyboard focus and the question shortcut.
4. Open a completed Nexus task and inspect its finding, attempts, and interpretation section. With an authorized provider, request and review an interpretation. For an isolated failed run, replay a task, compare it with the original, and check both histories.
5. In **Fraud Intelligence**, select a synthetic finding and evaluate each available counterfactual. Compare scores and factors, refresh to review the saved scenario, then confirm the source finding and events still match.
6. At tablet and phone sizes, verify column reflow, long citation and source labels, focus states, and form controls. Check the console and the Network panel for unexpected errors.

### Phase 6 manual walkthrough

1. At 1920×1080, 1440×900, and 1280×800, sign in as the isolated owner and open Forensic cases. Create a case, assign your account and a team, filter by status and by assignment, then refresh and confirm persistence.
2. Open Evidence Vault and upload a small synthetic text file. Copy its evidence ID into the case registration form. Select it to inspect filename, size, both digests, current custodian, and ledger. Verify the file and export with a reason. Confirm that the new events appear and the file bytes match.
3. Open the case notes, add an observation with an evidence reference, and save a revision. Confirm both revisions appear. Move the case through investigating and review, add a review note, close the case, and reopen as an admin.
4. Open Investigation Nexus from the case. Submit a run, inspect dependency stages and task status, select TRACE and VERITAS to see cited evidence, then record a human review. Confirm the review survives refresh. Create a case report and download its PDF and JSON.
5. Follow a related incident into the graph. Verify zoom, node selection, filter behavior, and return navigation. At 768×1024 and 390×844, repeat case selection, custody inspection, and run review. Check keyboard tab order, visible focus, page overflow, long IDs, and loading/error states.
6. Check the existing dark theme, and record light theme as unavailable if no toggle is present. Inspect the console and Network panel during the flow for unexpected errors and failed requests. Test a stale edit and an unauthorized session separately to verify their expected error handling.
7. Upload a synthetic JPEG with a known orientation and capture time. Inspect **Image metadata** in Evidence Vault and the case. Compare the values with the fixture and verify that the original export has the same bytes. Check the display with a file that has no EXIF fields.

## Phase 9 checks

Run the backend suite from the repository root with an isolated `DATABASE_URL` as shown above. Run lint, a production build, and `npm exec tsc -- --noEmit` from `apps/web`. The dedicated tests cover workflow graph validation, optimistic draft revisions, authorization, scheduled and event triggering, approval and replay, simulation cycles and isolation, currency and reporting periods, embedding job authorization, retrieval filters, and the four native provider stream protocols.

With both dedicated local stacks healthy, execute `python scripts/smoke_phase9.py` from the repository root. It creates fresh synthetic tenants, keeps the original SQLite data untouched, and checks version publication, approval, worker restart recovery, tenant-event execution, topology isolation, currency-separated reporting, exports, cross-origin rejection, and keyword fallback. Run worker-control scripts one at a time.

For the linked demonstration, run `python scripts/smoke_flagship.py` on the dedicated PostgreSQL stack. It creates a labeled synthetic organization and follows its submitted authentication and refund records through detection, the confirmed incident, a forensic case and its evidence, seven completed Nexus tasks, cited Copilot record search, a counterfactual, workflow approval, a Digital Twin simulation, report generation, and a BI update after a new payment. The script prints the persisted record identifiers.

### Signed-in walkthrough

Repeat with viewports of 1920×1080, 1440×900, 1280×800, 768×1024, and 390×844. Use the isolated owner account and repeat approval, exports, and document access with a reviewer and a least-privilege user. Check keyboard navigation, visible focus, scroll containment, mobile controls, loading and empty states, and access-denied messages.

1. In Workflow Studio, create the incident review template, drag or keyboard-select nodes, link the condition branches, undo and redo, save, dry run, and publish. Run against a synthetic incident and approve it. Refresh the page and inspect the original and replay history.
2. In Digital Twin, record a dependency between synthetic assets. Compare outage and isolation outcomes, filter the graph by impact layer, keyboard-focus a node, inspect its source path, and export the saved comparison. Reopen the topology and confirm its recorded dependencies are intact.
3. In Business Intelligence, load synthetic USD and EUR payment/refund rows, pick dates, switch currencies, inspect the prior-period values, and verify the exported rows match the selected report.
4. In Knowledge Base, verify keyword search and check the configured embedding status. With an authorized local embedding model, index a synthetic document, verify passage results, then expire it and rerun the search.
5. In Copilot, use deterministic cited mode. With a separately authorized model and synthetic context, observe a provisional answer, verify final citations and JSON export, interrupt a request, and verify the saved conversation state.
