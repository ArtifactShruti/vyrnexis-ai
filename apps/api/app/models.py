import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def uuid_value() -> str:
    return str(uuid.uuid4())


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    industry: Mapped[str] = mapped_column(String(100), default="")
    branding_json: Mapped[str] = mapped_column(Text, default="{}")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    onboarding_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(50), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    organization: Mapped["Organization"] = relationship(back_populates="users")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    refresh_jti_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    __table_args__ = (Index("ix_api_credentials_org_created", "organization_id", "created_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    scopes_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class IntelligenceEntity(Base):
    __tablename__ = "intelligence_entities"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    external_id: Mapped[str] = mapped_column(String(300), index=True)
    display_name: Mapped[str] = mapped_column(String(300))
    properties: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class IntelligenceRelationship(Base):
    __tablename__ = "intelligence_relationships"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("intelligence_entities.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("intelligence_entities.id"))
    relationship_type: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float)
    source_reference: Mapped[str] = mapped_column(String(500), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class GraphBookmark(Base):
    __tablename__ = "graph_bookmarks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ids: Mapped[str] = mapped_column(Text, default="[]")
    filters: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="open")
    description: Mapped[str] = mapped_column(Text, default="")
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    team: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), default="status_changed")
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(80), nullable=False)
    identifier: Mapped[str] = mapped_column(String(200), default="")
    criticality: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AssetAssignment(Base):
    __tablename__ = "asset_assignments"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    team: Mapped[str] = mapped_column(String(120), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AssetHistory(Base):
    __tablename__ = "asset_history"
    __table_args__ = (Index("ix_asset_history_asset_created", "asset_id", "created_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class AssetVulnerability(Base):
    __tablename__ = "asset_vulnerabilities"
    __table_args__ = (Index("ix_asset_vulnerabilities_asset_status", "asset_id", "status"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    cve: Mapped[str] = mapped_column(String(40), default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="open")
    remediation: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class ThreatIndicator(Base):
    __tablename__ = "threat_indicators"
    __table_args__ = (
        UniqueConstraint("organization_id", "indicator_type", "value", name="uq_threat_indicator"),
        Index("ix_threat_indicators_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    indicator_type: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(300))
    classification: Mapped[str] = mapped_column(String(30), default="unknown")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    provenance: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    source_reference: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class DetectionInput(Base):
    __tablename__ = "detection_inputs"
    __table_args__ = (
        UniqueConstraint("organization_id", "source", "external_id", name="uq_detection_input_source_event"),
        Index("ix_detection_input_account_time", "organization_id", "account", "occurred_at"),
        Index("ix_detection_input_queue", "status", "queued_at"),
    )
    event_id: Mapped[str] = mapped_column(ForeignKey("security_events.id"), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    source: Mapped[str] = mapped_column(String(120))
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    account: Mapped[str | None] = mapped_column(String(200), nullable=True)
    device: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    queued_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class DetectionRule(Base):
    __tablename__ = "detection_rules"
    __table_args__ = (UniqueConstraint("organization_id", "kind", name="uq_detection_rule_kind"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    window_minutes: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)


class DetectionAlert(Base):
    __tablename__ = "detection_alerts"
    __table_args__ = (UniqueConstraint("organization_id", "group_key", name="uq_detection_alert_group"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("detection_rules.id"))
    group_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(240))
    explanation: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="open")
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class DetectionAlertEvent(Base):
    __tablename__ = "detection_alert_events"
    alert_id: Mapped[str] = mapped_column(ForeignKey("detection_alerts.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("security_events.id"), primary_key=True)


class DetectionRun(Base):
    __tablename__ = "detection_runs"
    __table_args__ = (UniqueConstraint("event_id", "rule_id", name="uq_detection_run_event_rule"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("detection_rules.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("security_events.id"))
    alert_id: Mapped[str | None] = mapped_column(ForeignKey("detection_alerts.id"), nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_data_source_name"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class IngestionKey(Base):
    __tablename__ = "ingestion_keys"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    secret_digest: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint("source_id", "request_key", name="uq_ingestion_batch_key"),
        Index("ix_ingestion_batches_source_time", "source_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    request_key: Mapped[str] = mapped_column(String(120))
    payload_digest: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class IngestionReceipt(Base):
    __tablename__ = "ingestion_receipts"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_ingestion_record_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    payload_digest: Mapped[str] = mapped_column(String(64))
    record_id: Mapped[str] = mapped_column(String)


class CommerceRecord(Base):
    __tablename__ = "commerce_records"
    __table_args__ = (Index("ix_commerce_org_account_currency_time", "organization_id", "account", "currency", "occurred_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    account: Mapped[str] = mapped_column(String(200))
    device: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(Integer)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)


class CorrelationSettings(Base):
    __tablename__ = "correlation_settings"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    window_minutes: Mapped[int] = mapped_column(Integer)
    refund_threshold: Mapped[int] = mapped_column(Integer)
    failure_threshold: Mapped[int] = mapped_column(Integer)


class CommerceFinding(Base):
    __tablename__ = "commerce_findings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    refund_id: Mapped[str] = mapped_column(ForeignKey("commerce_records.id"), unique=True)
    score: Mapped[int] = mapped_column(Integer)
    report: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    investigation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    sha512: Mapped[str] = mapped_column(String(128))
    mime_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    immutable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class EvidenceFileMetadata(Base):
    __tablename__ = "evidence_file_metadata"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EvidenceImageMetadata(Base):
    __tablename__ = "evidence_image_metadata"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(24))
    fields_json: Mapped[str] = mapped_column(Text)
    inspected_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class ForensicCase(Base):
    __tablename__ = "forensic_cases"
    __table_args__ = (Index("ix_forensic_case_org_status_time", "organization_id", "status", "updated_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    investigator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    team: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    closure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class ForensicCaseLink(Base):
    __tablename__ = "forensic_case_links"
    case_id: Mapped[str] = mapped_column(ForeignKey("forensic_cases.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    object_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class ForensicNote(Base):
    __tablename__ = "forensic_notes"
    __table_args__ = (Index("ix_forensic_notes_case_time", "case_id", "created_at"),)
    note_id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("forensic_cases.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    references_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class CustodyEnrollment(Base):
    __tablename__ = "custody_enrollments"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("forensic_cases.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    classification: Mapped[str] = mapped_column(String(32))
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    custodian_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    head_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class CustodyEvent(Base):
    __tablename__ = "custody_events"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("custody_enrollments.evidence_id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("forensic_cases.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(24))
    previous_custodian_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    new_custodian_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integrity_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class ForensicReport(Base):
    __tablename__ = "forensic_reports"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_forensic_report_version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    case_id: Mapped[str] = mapped_column(ForeignKey("forensic_cases.id"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[str] = mapped_column(Text)
    integrity_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class ReportRecord(Base):
    __tablename__ = "report_records"
    __table_args__ = (
        Index("ix_report_records_org_created", "organization_id", "created_at"),
        Index("ix_report_records_org_category", "organization_id", "category"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    source_module: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    review_status: Mapped[str] = mapped_column(String(20), default="draft")
    snapshot_json: Mapped[str] = mapped_column(Text)
    integrity_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (UniqueConstraint("organization_id", "request_key", name="uq_investigation_request"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    case_id: Mapped[str | None] = mapped_column(ForeignKey("forensic_cases.id"), nullable=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    request_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class InvestigationTask(Base):
    __tablename__ = "investigation_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "agent", name="uq_nexus_task_agent"),
        Index("ix_nexus_task_queue", "status", "available_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"))
    agent: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="waiting")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)


class InvestigationDependency(Base):
    __tablename__ = "investigation_dependencies"
    task_id: Mapped[str] = mapped_column(ForeignKey("investigation_tasks.id"), primary_key=True)
    prerequisite_id: Mapped[str] = mapped_column(ForeignKey("investigation_tasks.id"), primary_key=True)


class InvestigationAttempt(Base):
    __tablename__ = "investigation_attempts"
    task_id: Mapped[str] = mapped_column(ForeignKey("investigation_tasks.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    definition: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(32), index=True)
    task_type: Mapped[str] = mapped_column(String(80))
    input_data: Mapped[str] = mapped_column(Text, default="{}")
    output_data: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String(200))
    resource: Mapped[str] = mapped_column(String(300))
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_owner_read_created", "owner_id", "read_at", "created_at"),
        Index("ix_notifications_org_created", "organization_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    resource: Mapped[str] = mapped_column(String(300), default="")
    href: Mapped[str] = mapped_column(String(500), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class AiSettings(Base):
    __tablename__ = "ai_settings"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    settings_json: Mapped[str] = mapped_column(Text)


class AiInvocation(Base):
    __tablename__ = "ai_invocations"
    __table_args__ = (Index("ix_ai_invocations_org_created", "organization_id", "created_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(24))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="running")
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    charged_micros: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_knowledge_documents_org_updated", "organization_id", "updated_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160))
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (UniqueConstraint("document_id", "digest"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(160))
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "version"], ["knowledge_versions.document_id", "knowledge_versions.number"],
                             ondelete="CASCADE"),
        UniqueConstraint("document_id", "version", "ordinal"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    document_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"
    __table_args__ = (Index("ix_copilot_org_owner_updated", "organization_id", "owner_id", "updated_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    case_id: Mapped[str | None] = mapped_column(ForeignKey("forensic_cases.id"), nullable=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class CopilotTurn(Base):
    __tablename__ = "copilot_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "request_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("copilot_conversations.id", ondelete="CASCADE"))
    request_key: Mapped[str] = mapped_column(String(80))
    question: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    model_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class AgentInterpretation(Base):
    __tablename__ = "agent_interpretations"
    __table_args__ = (UniqueConstraint("task_id", "request_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    task_id: Mapped[str] = mapped_column(ForeignKey("investigation_tasks.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(80))
    invocation_id: Mapped[str | None] = mapped_column(ForeignKey("ai_invocations.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    review_status: Mapped[str] = mapped_column(String(24), default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class InvestigationReplay(Base):
    __tablename__ = "investigation_replays"
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), primary_key=True)
    source_run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    target_agents_json: Mapped[str] = mapped_column(Text)


class CounterfactualScenario(Base):
    __tablename__ = "counterfactual_scenarios"
    __table_args__ = (Index("ix_counterfactual_org_finding", "organization_id", "finding_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    finding_id: Mapped[str] = mapped_column(ForeignKey("commerce_findings.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class WorkflowStudio(Base):
    __tablename__ = "workflow_studio"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), primary_key=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    draft_json: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    lifecycle: Mapped[str] = mapped_column(String(16), default="draft")
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    definition_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (UniqueConstraint("workflow_id", "request_key"),
                      Index("ix_workflow_exec_org_created", "organization_id", "created_at"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_executions.id"), nullable=True)
    request_key: Mapped[str] = mapped_column(String(120))
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    definition_json: Mapped[str] = mapped_column(Text)
    facts_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    deadline_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    execution_id: Mapped[str] = mapped_column(ForeignKey("workflow_executions.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)


class WorkflowApproval(Base):
    __tablename__ = "workflow_approvals"
    __table_args__ = (ForeignKeyConstraint(["execution_id", "node_id"],
                                           ["workflow_steps.execution_id", "workflow_steps.node_id"]),)
    execution_id: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class TwinSimulation(Base):
    __tablename__ = "twin_simulations"
    __table_args__ = (UniqueConstraint("organization_id", "request_key"),
                      Index("ix_twin_simulations_org_created", "organization_id", "created_at"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_value)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(80))
    input_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    topology_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class KnowledgeEmbeddingJob(Base):
    __tablename__ = "knowledge_embedding_jobs"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "version"], ["knowledge_versions.document_id", "knowledge_versions.number"],
                             ondelete="CASCADE"),
        Index("ix_embedding_jobs_queue", "profile", "status", "available_at"),
    )
    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(160), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"
    chunk_id: Mapped[str] = mapped_column(ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), primary_key=True)
    profile: Mapped[str] = mapped_column(String(160), primary_key=True)
    vector_json: Mapped[str] = mapped_column(Text)
