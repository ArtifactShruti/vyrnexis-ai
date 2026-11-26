# Next Tasks

Updated: 2026-11-26

## Immediate next milestone

Use The Phase 9 walkthrough in `docs/TESTING.md` for signed-in owner, reviewer, and least-privilege acceptance after browser authorization. Hybrid retrieval is now wired into Copilot citation selection with tenant and permission revalidation, source deduplication, keyword fallback, version filtering, and retrieval audit entries. Live provider validation needs an operator-authorized account or local model. Use mocks for routine tests.

All 32 page rows now have an implementation state, with no unimplemented pages and no in-progress labels. PostgreSQL 0018 is deployed locally. Remaining engineering priority is integrations/data-source completion, billing/subscription entitlements, MFA/auth hardening, signed-in visual acceptance, live AI/provider verification, hosted CI, and independent security review.

1. Extend the incident domain with assignment and incident/evidence links. Status transitions, timestamps, event history, audit, browser creation/persistence/filter tests, and tenant tests are implemented.
2. Expand the isolated demo dataset beyond its verified linked authentication/device/refund/incident/evidence scenario toward the documented reproducible dataset targets, using persisted records only.
3. Extend the asset inventory slice with assignment, asset edit/status history, discovery/import, and links to intelligence entities and incidents. Extend case evidence with retention and independently anchored custody checks.

## Product coverage

4. Add analyst assignment, source schema mapping, asynchronous batch scheduling, retry and dead-letter handling, and retention controls. Extend fraud intelligence with richer order/customer records, trend charts, and saved investigation views.
5. Build user/role administration, audit-log viewing, organization settings, notification preferences, and a functional global search/command palette. Add keyboard focus behavior and verify authorization-sensitive navigation.
6. Add a light theme, collapsible sidebar, organization switcher, notification center, sort/pagination/export for large tables, and accessible responsive navigation; validate at 1920x1080, 1440x900, 1280x800, 768x1024, and 390x844.
7. Expand graph tests and browser coverage for traversal, relationship selection, filters, bookmarks, timeline synchronization, export, and narrow-screen operation.

## Agents and automation

8. Extend the leased pipeline with process memory quotas, immediate cancellation, per-agent model configuration, and an approval gate for any future mutating action.
9. Verify a local embedding model with synthetic documents. Measure retrieval quality and add an operator-managed model capability and price catalog. Extend Digital Twin and BI only where source records support the additional measures.
10. Extend Workflow Studio with draft autosave, a minimap, a source-scoped webhook trigger, and configurable step retry policy. Any future operational write needs a separately validated approval gate.

## Platform and release readiness

11. Expand the verified Alembic and PostgreSQL/Redis stack with backup and restore tests, separated database roles, and retention policies. The worker runs detection, Nexus, workflow scheduling and execution, and opt-in local embedding jobs.
12. Add evidence object-storage design, retention, backup/restore checks, structured logs, health probes, dependency scanning, CI, and OpenTelemetry where appropriate.
13. Implement remaining pages in the 32-page acceptance matrix from `IMPLEMENTATION_STATUS.md`; do not add empty routes.
14. Add rate limiting, MFA, recovery, session management, invitations, CSP/security headers, and obtain an independent security review before any production exposure.
15. Verify the new Security Operations page in a signed-in browser, including ingestion, triage, refresh, and filter behavior. Docker API health and loopback bindings are verified, and automated API tests cover event access and review rules.
