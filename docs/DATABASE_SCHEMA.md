# Database schema

PostgreSQL uses Alembic revisions `0001` (baseline), `0002` (authentication detection), `0003` (intake and commerce), `0004` (forensics and Nexus), and `0005` (image metadata). The local SQLite demo uses the same SQLAlchemy models and adds missing tables on startup. The original SQLite database is outside the demo and test stacks.

| Table | Purpose and boundaries |
| --- | --- |
| `data_sources` | An organization owns each source. Names are unique within an organization. Source kind fixes the allowed batch record types. |
| `ingestion_keys` | Keys belong to one source. Only token digests, labels, expiry, and revocation timestamps are stored. |
| `ingestion_batches` | One report per source and request key. The content digest distinguishes a retry from a conflicting submission. The stored row results omit raw payloads. |
| `ingestion_receipts` | One accepted record per source and external record ID. Each receipt retains its normalized digest and the accepted record reference. |
| `commerce_records` | Tenant-owned payment and refund observations, with reported account/device, currency, integer minor units, and optional authorized evidence. The composite account/time index supports refund evaluation. |
| `correlation_settings` | The tenant's window and thresholds. Evaluations snapshot the applied settings in their reports. |
| `commerce_findings` | At most one finding per refund. It retains factor weights, source record IDs, limitations, and human disposition. A conditional update allows a single incident confirmation. |

Security observations use `security_events` and `detection_inputs`. In PostgreSQL, queued work stays in `detection_inputs`; Redis holds only wake signals. Case creation and graph provenance are stored in the existing incident, event, and graph tables. Evidence verification adds an entry to `audit_logs` without altering the evidence file or its original hash metadata.

| Phase 6 tables | Purpose and boundaries |
| --- | --- |
| `forensic_cases`, `forensic_case_links` | Case ownership, assignment, status, optimistic version, and authorized references. Case links are unique by case, type, and object. |
| `forensic_notes` | Composite note and revision key preserves an append-only history with author, category, and references. |
| `evidence_file_metadata` | Optional filename, byte count, and recognized signature. Older uploads without metadata remain readable. |
| `evidence_image_metadata` | Derived status, allowlisted header fields, and inspection timestamp. Keyed by original evidence ID. Verification can populate missing metadata or retry an unavailable inspection. |
| `custody_enrollments`, `custody_events` | One ledger per evidence ID. A unique sequence preserves ordering. The case transaction advances the ledger head with its new event. |
| `forensic_reports` | Unique case/version snapshots and a SHA-256 digest. PDF rendering uses the stored snapshot. |
| `investigation_runs`, `investigation_tasks` | One run per tenant/request key and one task per agent per run. Tasks carry availability, lease, result, and error state. |
| `investigation_dependencies`, `investigation_attempts` | Dependency edges and numbered execution attempts. Successful results also write to the existing agent execution history. |

Revision `0006` adds `ai_settings` and `ai_invocations` for tenant policy and accounted provider activity. Neither table stores credentials or request prompts. `knowledge_documents`, `knowledge_versions`, and `knowledge_chunks` retain tenant ownership, visibility, expiry, content digests, and indexed text provenance. `copilot_conversations` and `copilot_turns` persist account-owned questions, authorized context, source keys, results, and idempotent request keys.

Revision `0007` adds `agent_interpretations` for model output, invocation metadata, and interpretation review. `investigation_replays` records the original run and requested task selection. Revision `0008` adds `counterfactual_scenarios` for tenant-owned snapshots of actual and hypothetical evaluations.

| Phase 9 migration | Data and constraints |
| --- | --- |
| `0009_workflow_studio` | `workflow_studio` holds drafts, optimistic revisions, and trigger cursors. `workflow_versions` stores immutable publications. `workflow_executions`, `workflow_steps`, and `workflow_approvals` store idempotent runs, step transitions, and human decisions. |
| `0010_twin_simulations` | `twin_simulations` stores tenant-owned topology, assumptions, base and alternate impact, and a snapshot digest. Existing intelligence entities and relationships supply topology. |
| `0011_local_knowledge_embeddings` | `knowledge_embedding_jobs` and `knowledge_embeddings` record indexed document versions and provider profiles. Vectors are scoped to their source document version and chunk. No PostgreSQL vector extension is required. |

Business Intelligence reads existing commerce records and findings. Copilot streaming uses the existing conversation, turn, and invocation tables for finalized results and usage.
