# Product roadmap

The implemented dashboard uses recorded tenant events, alerts, and incidents. Review the [acceptance matrix](../IMPLEMENTATION_STATUS.md) for current verification and module coverage.

| Priority | Planned work | Acceptance |
| --- | --- | --- |
| Next | Dashboard filters, saved views, and view exports | An analyst can save a scoped UTC date range and restore it on re-entry. Export totals match the visible filters and tenant permissions. |
| Next | Investigation and evidence dashboards | Charts show case aging, approval backlog, and custody activity from recorded timestamps. Missing source data has an explicit empty state. |
| Next | Data-source operations | Provide schema mapping, job retry controls, and ingestion health history. Operators can inspect rejected rows and replay with idempotency. |
| Planned | Workflow and Digital Twin usability | Add draft autosave, an overview for large workflow graphs, and clearer dependency-impact paths. Verify keyboard editing and tablet layouts before release. |
| Planned | Release verification | Run role-based signed-in visual checks, hosted CI, authorized provider tests, backup restoration, and an independent security review. |
