from datetime import date, datetime, timedelta, timezone
import csv
from io import StringIO
import hashlib
import hmac
import json
import logging
import os
import secrets
from time import perf_counter
import uuid
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field, StringConstraints, model_validator
from redis import RedisError
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .database import Base, engine, get_db
from .models import (
    AgentExecution, ApiCredential, Asset, AuditLog, AuthSession, CommerceFinding, CommerceRecord, CorrelationSettings,
    CopilotConversation, CopilotTurn, CustodyEnrollment, DataSource, DetectionAlert, DetectionAlertEvent, DetectionInput, DetectionRule, DetectionRun, Notification, TwinSimulation, WorkflowExecution,
    AssetAssignment, AssetHistory, AssetVulnerability, Evidence, EvidenceFileMetadata, EvidenceImageMetadata, ForensicCase, GraphBookmark, Incident, IncidentEvent, IngestionBatch, IngestionKey, IntelligenceEntity, ReportRecord, ThreatIndicator,
    IntelligenceRelationship, InvestigationRun, InvestigationTask, Organization, SecurityEvent, User, Workflow, utc_now_naive, uuid_value,
)
from .agents import AGENT_DEFINITIONS
from .ai_gateway import build_gateway_router
from .business_intelligence import build_business_router, summarize as commerce_summary
from .commerce import CorrelationPolicy, commerce_record, evaluate_refund, finding_record, get_policy, utc
from .copilot import build_copilot_router
from .counterfactual import build_counterfactual_router
from .digital_twin import build_twin_router
from .detection import HEARTBEAT_KEY, RULE_TITLES, evaluate_detections, notify_worker, redis_client
from .evidence_exif import image_metadata_record, inspect_verified_image, save_image_metadata
from .image_metadata import JPEG_HEADER, TIFF_HEADERS, inspect_image
from .ingestion import KeySettings, SourceSettings, batch_record, digest, parse_batch, store_batch
from .knowledge import build_knowledge_router
from .forensics import READERS as FORENSIC_READERS, build_forensic_router
from .nexus import build_nexus_router, full_record as nexus_full_record
from .nexus_hybrid import build_hybrid_router
from .workflow_studio import build_workflow_router
from .semantic import build_semantic_router
from .sqlite_demo import upgrade_demo_columns

logger = logging.getLogger("vyrnexis.auth")
schema_mode = os.getenv("VYRNEXIS_SCHEMA_MODE", "create_all")
if schema_mode == "sqlite_demo":
    upgrade_demo_columns(engine)
if schema_mode in {"create_all", "sqlite_demo"}:
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="VYRNEXIS AI API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

passwords = PasswordHasher()
SECRET = os.getenv("JWT_SECRET")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if SECRET and SECRET.startswith("replace-with-"):
    SECRET = None
if not SECRET or len(SECRET) < 32:
    if ENVIRONMENT == "production":
        raise RuntimeError("A JWT_SECRET with at least 32 characters must be configured in production")
    SECRET = secrets.token_urlsafe(48)
    logger.warning("JWT_SECRET is unset; using an ephemeral development-only signing key")
JWT_ALGORITHM = "HS256"
ACCESS_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=7)
bearer = HTTPBearer(auto_error=False)

ORG_ADMIN_ROLES = {"owner", "organization_admin"}
ENTITY_WRITER_ROLES = ORG_ADMIN_ROLES | {"security_analyst", "forensic_investigator"}
INCIDENT_WRITER_ROLES = ORG_ADMIN_ROLES | {"security_analyst", "forensic_investigator"}
ASSET_WRITER_ROLES = ORG_ADMIN_ROLES | {"security_analyst"}
RULE_WRITER_ROLES = ORG_ADMIN_ROLES | {"security_analyst"}
INGESTION_ROLES = ORG_ADMIN_ROLES | {"security_analyst", "business_analyst"}
COMMERCE_REVIEW_ROLES = ORG_ADMIN_ROLES | {"security_analyst", "business_analyst"}
DETECTION_MODE = os.getenv("VYRNEXIS_DETECTION_MODE", "inline")
RuleKind = Literal["failed_signins", "unfamiliar_device"]
EventSeverity = Literal["low", "medium", "high", "critical"]
NormalizedLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
INCIDENT_TRANSITIONS = {
    "open": {"investigating", "review", "closed"},
    "investigating": {"review", "contained", "closed"},
    "review": {"investigating", "closed"},
    "contained": {"investigating", "closed"},
    "closed": set(),
}
EVIDENCE_WRITER_ROLES = ORG_ADMIN_ROLES | {"forensic_investigator"}
WORKFLOW_WRITER_ROLES = ORG_ADMIN_ROLES | {"automation_engineer"}


class RegisterRequest(BaseModel):
    organization_name: str
    organization_slug: str
    full_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserCreateRequest(BaseModel):
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=12, max_length=200)]
    role: Literal["viewer", "member", "security_analyst", "forensic_investigator", "business_analyst",
                  "automation_engineer", "organization_admin"]


class UserUpdateRequest(BaseModel):
    role: Literal["viewer", "member", "security_analyst", "forensic_investigator", "business_analyst",
                  "automation_engineer", "organization_admin"] | None = None
    is_active: bool | None = None


class OrganizationSettingsRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    timezone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    currency: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=3)]
    industry: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""
    branding: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)
    onboarding: dict = Field(default_factory=dict)


class EntityRequest(BaseModel):
    organization_id: str
    entity_type: str
    external_id: str
    display_name: str
    properties: dict = Field(default_factory=dict)


class RelationshipRequest(BaseModel):
    organization_id: str
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float
    source_reference: str = ""


class IncidentRequest(BaseModel):
    organization_id: str
    title: str
    severity: str = "medium"
    description: str = ""


class IncidentStatusRequest(BaseModel):
    status: str = Field(min_length=3, max_length=30)
    note: str = Field(default="", max_length=2000)


class IncidentAssignmentRequest(BaseModel):
    assignee_id: str | None = Field(default=None, max_length=120)
    team: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class ThreatIndicatorRequest(BaseModel):
    indicator_type: Literal["ip", "domain", "url", "hash"]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]
    classification: Literal["unknown", "benign", "suspicious", "malicious"] = "unknown"
    confidence: int = Field(0, ge=0, le=100)
    provenance: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    notes: Annotated[str, StringConstraints(max_length=4000)] = ""
    expires_at: datetime | None = None


class ReportCreateRequest(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    category: Literal["forensic", "investigation", "security", "threat", "fraud", "commerce", "business",
                      "workflow", "digital_twin", "copilot", "asset", "incident"]
    source_module: Literal["forensics", "nexus", "security", "threat_intelligence", "fraud",
                           "ecommerce", "business_intelligence", "workflow", "digital_twin", "copilot",
                           "assets", "incidents"]
    source_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None


class ApiCredentialCreateRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    scopes: list[Literal["api.read", "dashboard.read", "reports.read", "commerce.read", "incidents.read",
                         "assets.read", "forensics.read", "health.read"]]
    expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self):
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Scopes must be unique")
        if not self.scopes:
            raise ValueError("Select at least one API scope")
        if self.expires_at.replace(tzinfo=None) <= utc_now_naive():
            raise ValueError("Expiration must be in the future")
        if self.expires_at.replace(tzinfo=None) > utc_now_naive() + timedelta(days=365):
            raise ValueError("Expiration cannot exceed 365 days")
        return self


class AssetRequest(BaseModel):
    organization_id: str
    name: str = Field(min_length=2, max_length=200)
    asset_type: str = Field(min_length=2, max_length=80)
    identifier: str = Field(default="", max_length=200)
    criticality: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    status: str = Field(default="active", pattern="^(active|maintenance|retired)$")


class AssetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    asset_type: str | None = Field(default=None, min_length=2, max_length=80)
    identifier: str | None = Field(default=None, max_length=200)
    criticality: Literal["low", "medium", "high", "critical"] | None = None
    status: Literal["active", "maintenance", "retired"] | None = None


class AssetAssignmentRequest(BaseModel):
    assignee_id: str | None = Field(default=None, max_length=120)
    team: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class AssetVulnerabilityRequest(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    cve: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    status: Literal["open", "in_progress", "mitigated", "accepted", "closed"] = "open"
    remediation: Annotated[str, StringConstraints(max_length=4000)] = ""


class AssetVulnerabilityUpdateRequest(BaseModel):
    status: Literal["open", "in_progress", "mitigated", "accepted", "closed"]


class SecurityEventRequest(BaseModel):
    organization_id: str
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    event_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=240)]
    description: str = Field(default="", max_length=4000)
    source_reference: str = Field(default="", max_length=240)
    occurred_at: datetime | None = None
    external_id: NormalizedLabel | None = None
    account: NormalizedLabel | None = None
    device: NormalizedLabel | None = None
    outcome: Literal["success", "failure"] | None = None

    @model_validator(mode="after")
    def validate_authentication_fields(self):
        if self.outcome and (
            not self.account or self.event_type.lower() not in {"authentication", "login", "sign_in"}
        ):
            raise ValueError("An authentication outcome requires an account and an authentication, login, or sign_in event.")
        return self


class DetectionRuleSettings(BaseModel):
    enabled: bool = True
    severity: EventSeverity = "high"
    window_minutes: int = Field(default=15, ge=1, le=1440)
    threshold: int = Field(default=3, ge=2, le=100)


class AlertFeedback(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class SecurityEventReview(BaseModel):
    status: Literal["reviewed", "dismissed"]


class WorkflowRequest(BaseModel):
    organization_id: str
    name: str
    definition: dict = Field(default_factory=dict)
    enabled: bool = False


class GraphBookmarkRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    filters: dict = Field(default_factory=dict)


class AgentTaskRequest(BaseModel):
    agent: str = Field(min_length=3, max_length=32)
    task_type: str = Field(default="analyze_organization", min_length=3, max_length=80)
    incident_id: str | None = None


def audit(db: Session, organization_id: str, actor_id: str | None, action: str, resource: str, details: dict):
    db.add(AuditLog(
        organization_id=organization_id,
        actor_id=actor_id,
        action=action,
        resource=resource,
        details=json.dumps(details),
    ))


def _hash_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()


def _encode_access(user: User, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": user.id,
        "organization_id": user.organization_id,
        "sid": session_id,
        "typ": "access",
        "iat": now,
        "exp": now + ACCESS_TTL,
    }, SECRET, algorithm=JWT_ALGORITHM)


def _encode_refresh(user: User, session: AuthSession, jti: str) -> str:
    return jwt.encode({
        "sub": user.id,
        "organization_id": user.organization_id,
        "sid": session.id,
        "jti": jti,
        "typ": "refresh",
        "iat": datetime.now(timezone.utc),
        "exp": session.expires_at.replace(tzinfo=timezone.utc),
    }, SECRET, algorithm=JWT_ALGORITHM)


def _new_session(db: Session, user: User) -> dict:
    session = AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        organization_id=user.organization_id,
        refresh_jti_hash="",
        expires_at=utc_now_naive() + SESSION_TTL,
    )
    jti = secrets.token_urlsafe(32)
    session.refresh_jti_hash = _hash_jti(jti)
    db.add(session)
    db.flush()
    audit(db, user.organization_id, user.id, "auth.session.create", f"session:{session.id}", {})
    return {
        "access_token": _encode_access(user, session.id),
        "refresh_token": _encode_refresh(user, session, jti),
        "token_type": "bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
    }


def _invalid_auth() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise _invalid_auth() from exc


def _valid_refresh_session(token: str, db: Session) -> tuple[dict, AuthSession, User]:
    claims = _decode(token)
    if claims.get("typ") != "refresh" or not claims.get("jti"):
        raise _invalid_auth()
    session = db.get(AuthSession, claims.get("sid"))
    user = db.get(User, claims.get("sub"))
    now = utc_now_naive()
    if (
        not session or not user or not user.is_active or session.revoked_at is not None
        or session.expires_at <= now or session.user_id != user.id
        or session.organization_id != user.organization_id
        or claims.get("organization_id") != user.organization_id
        or session.refresh_jti_hash != _hash_jti(claims["jti"])
    ):
        raise _invalid_auth()
    return claims, session, user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise _invalid_auth()
    if credentials.credentials.startswith("vyrn_"):
        if request.method != "GET":
            raise HTTPException(403, "API credentials cannot perform mutating actions")
        credential = db.scalar(select(ApiCredential).where(
            ApiCredential.secret_hash == hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest(),
        ))
        now = utc_now_naive()
        if (credential is None or credential.revoked_at is not None or credential.expires_at <= now):
            raise _invalid_auth()
        user = db.get(User, credential.owner_id)
        if not user or not user.is_active or user.organization_id != credential.organization_id:
            raise _invalid_auth()
        scopes = set(json.loads(credential.scopes_json))
        path = request.url.path
        required = "api.read"
        for prefix, scope in (
            ("/api/v1/dashboard", "dashboard.read"),
            ("/api/v1/reports", "reports.read"),
            ("/api/v1/commerce", "commerce.read"),
            ("/api/v1/incidents", "incidents.read"),
            ("/api/v1/assets", "assets.read"),
            ("/api/v1/forensic-cases", "forensics.read"),
            ("/api/v1/health", "health.read"),
        ):
            if path.startswith(prefix):
                required = scope
                break
        if required not in scopes and "api.read" not in scopes:
            raise HTTPException(403, "API credential lacks the required read scope")
        credential.usage_count += 1
        credential.last_used_at = now
        db.commit()
        request.state.api_credential = credential.id
        return user
    claims = _decode(credentials.credentials)
    if claims.get("typ") != "access":
        raise _invalid_auth()
    session = db.get(AuthSession, claims.get("sid"))
    user = db.get(User, claims.get("sub"))
    now = utc_now_naive()
    if (
        not session or not user or not user.is_active or session.revoked_at is not None
        or session.expires_at <= now or session.user_id != user.id
        or session.organization_id != user.organization_id
        or claims.get("organization_id") != user.organization_id
    ):
        raise _invalid_auth()
    return user


def require_roles(*roles: str):
    def role_dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if getattr(request.state, "api_credential", None):
            raise HTTPException(status_code=403, detail="API credentials cannot perform administrator actions")
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your role cannot perform this action")
        return user
    return role_dependency


def _authorized_organization(user: User, requested_id: str | None = None) -> str:
    if requested_id and requested_id != user.organization_id:
        # Do not disclose whether another tenant exists.
        raise HTTPException(status_code=404, detail="Organization not found")
    return user.organization_id


def _user_payload(user: User) -> dict:
    organization = {"id": user.organization_id, "name": user.organization.name}
    return {
        "user": {"id": user.id, "name": user.full_name, "email": user.email, "role": user.role},
        "organization": organization,
    }


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/observability/status")
def observability_status(db: Session = Depends(get_db),
                        user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    started = perf_counter()
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"
    api_latency_ms = round((perf_counter() - started) * 1000, 3)
    redis_status = "unavailable"
    worker_status = "unavailable"
    try:
        redis = redis_client()
        redis_status = "connected" if redis.ping() else "unavailable"
        worker_status = "healthy" if redis.exists(HEARTBEAT_KEY) else "no_recent_heartbeat"
    except Exception:
        redis_status = "unavailable"
    dialect = db.bind.dialect.name
    queued_detection = db.scalar(select(func.count()).select_from(DetectionInput).where(
        DetectionInput.organization_id == user.organization_id,
        DetectionInput.status.in_(("queued", "running")),
    )) or 0
    agent_statuses = dict(db.execute(select(AgentExecution.status, func.count()).where(
        AgentExecution.organization_id == user.organization_id,
    ).group_by(AgentExecution.status)).all())
    workflow_statuses = dict(db.execute(select(WorkflowExecution.status, func.count()).where(
        WorkflowExecution.organization_id == user.organization_id,
    ).group_by(WorkflowExecution.status)).all())
    ingestion_failures = db.scalar(select(func.count()).select_from(IngestionBatch).join(
        DataSource, DataSource.id == IngestionBatch.source_id,
    ).where(DataSource.organization_id == user.organization_id, IngestionBatch.rejected > 0)) or 0
    report_statuses = dict(db.execute(select(ReportRecord.status, func.count()).where(
        ReportRecord.organization_id == user.organization_id,
    ).group_by(ReportRecord.status)).all())
    nexus_statuses = dict(db.execute(select(InvestigationRun.status, func.count()).where(
        InvestigationRun.organization_id == user.organization_id,
    ).group_by(InvestigationRun.status)).all())
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "api": {"status": "healthy", "database_probe_latency_ms": api_latency_ms},
        "database": {"status": db_status, "dialect": dialect},
        "redis": {"status": redis_status},
        "worker": {"status": worker_status},
        "queues": {"detection_jobs": queued_detection},
        "executions": {
            "agents": agent_statuses,
            "workflows": workflow_statuses,
            "investigations": nexus_statuses,
            "reports": report_statuses,
        },
        "ingestion": {"batches_with_rejections": ingestion_failures},
        "limitations": [
            "Latency is a one-request database probe, not a measured uptime or throughput percentage.",
            "Redis and worker values are current probe results, not stored historical measurements.",
        ],
    }


@app.post("/api/v1/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if len(payload.password) < 12:
        raise HTTPException(400, "Password must contain at least 12 characters")
    if db.query(Organization).filter(Organization.slug == payload.organization_slug).first():
        raise HTTPException(409, "Organization slug already exists")
    email = str(payload.email).lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email address is already registered")
    org = Organization(name=payload.organization_name.strip(), slug=payload.organization_slug.strip().lower())
    db.add(org)
    db.flush()
    user = User(
        organization_id=org.id,
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=passwords.hash(payload.password),
        role="owner",
    )
    db.add(user)
    db.flush()
    token_pair = _new_session(db, user)
    audit(db, org.id, user.id, "organization.register", f"organization:{org.id}", {"slug": org.slug})
    db.commit()
    return {**token_pair, **_user_payload(user)}


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == str(payload.email).lower()).first()
    if not user:
        raise HTTPException(401, "Invalid email or password")
    try:
        passwords.verify(user.password_hash, payload.password)
    except VerifyMismatchError:
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(401, "Invalid email or password")
    token_pair = _new_session(db, user)
    audit(db, user.organization_id, user.id, "auth.login", f"user:{user.id}", {})
    db.commit()
    return {**token_pair, **_user_payload(user)}


@app.post("/api/v1/auth/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    claims, session, user = _valid_refresh_session(payload.refresh_token, db)
    old_hash = session.refresh_jti_hash
    new_jti = secrets.token_urlsafe(32)
    changed = db.query(AuthSession).filter(
        AuthSession.id == session.id,
        AuthSession.refresh_jti_hash == old_hash,
        AuthSession.revoked_at.is_(None),
    ).update({AuthSession.refresh_jti_hash: _hash_jti(new_jti)}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise _invalid_auth()
    audit(db, user.organization_id, user.id, "auth.session.rotate", f"session:{session.id}", {})
    result = {
        "access_token": _encode_access(user, session.id),
        "refresh_token": _encode_refresh(user, session, new_jti),
        "token_type": "bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        **_user_payload(user),
    }
    db.commit()
    return result


@app.post("/api/v1/auth/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    _, session, user = _valid_refresh_session(payload.refresh_token, db)
    session.revoked_at = utc_now_naive()
    audit(db, user.organization_id, user.id, "auth.session.revoke", f"session:{session.id}", {})
    db.commit()
    return {"revoked": True}


@app.get("/api/v1/auth/me")
def current_user(user: User = Depends(get_current_user)):
    return _user_payload(user)


def dashboard_activity(db: Session, organization_id: str):
    today = utc_now_naive().date()
    first = today - timedelta(days=29)
    start = datetime.combine(first, datetime.min.time())
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    days = {(first + timedelta(days=offset)).isoformat(): {
        "events": 0, "alerts": 0, "incidents": 0,
    } for offset in range(30)}
    for key, model, timestamp in (
        ("events", SecurityEvent, SecurityEvent.received_at),
        ("alerts", DetectionAlert, DetectionAlert.created_at),
        ("incidents", Incident, Incident.created_at),
    ):
        day = func.date(timestamp)
        counts = db.execute(select(day, func.count()).where(
            model.organization_id == organization_id, timestamp >= start, timestamp < end,
        ).group_by(day))
        for recorded, count in counts:
            days[str(recorded)][key] = count
    return [{"date": recorded, **counts} for recorded, counts in days.items()]


@app.get("/api/v1/dashboard")
def dashboard(
    organization_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    org = db.get(Organization, authorized_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    open_incidents = db.query(Incident).filter(Incident.organization_id == authorized_id, Incident.status != "closed")
    entities = db.query(IntelligenceEntity).filter(IntelligenceEntity.organization_id == authorized_id).count()
    relationships = db.query(IntelligenceRelationship).filter(IntelligenceRelationship.organization_id == authorized_id).count()
    recent_entities = db.query(IntelligenceEntity).filter(
        IntelligenceEntity.organization_id == authorized_id
    ).order_by(IntelligenceEntity.created_at.desc()).limit(6).all()
    recent_relationships = db.query(IntelligenceRelationship).filter(
        IntelligenceRelationship.organization_id == authorized_id
    ).order_by(IntelligenceRelationship.occurred_at.desc()).limit(8).all()
    referenced_entities = {entity_id for relation in recent_relationships for entity_id in (relation.source_id, relation.target_id)}
    entity_names = dict(db.execute(select(IntelligenceEntity.id, IntelligenceEntity.display_name).where(
        IntelligenceEntity.organization_id == authorized_id, IntelligenceEntity.id.in_(referenced_entities),
    )).all())
    investigations = None
    if user.role in FORENSIC_READERS:
        case_counts = db.execute(select(func.count(), func.count().filter(
            ForensicCase.investigator_id == user.id,
        )).where(ForensicCase.organization_id == authorized_id, ForensicCase.status != "closed")).one()
        task_counts = dict(db.execute(select(InvestigationTask.status, func.count()).join(
            InvestigationRun, InvestigationRun.id == InvestigationTask.run_id,
        ).where(InvestigationRun.organization_id == authorized_id).group_by(InvestigationTask.status)).all())
        investigations = {
            "open_cases": case_counts[0], "assigned_cases": case_counts[1],
            "active_tasks": sum(task_counts.get(status, 0) for status in ("waiting", "queued", "running")),
            "completed_tasks": task_counts.get("completed", 0),
            "failed_tasks": task_counts.get("failed", 0) + task_counts.get("timed_out", 0),
            "pending_reviews": db.scalar(select(func.count()).select_from(InvestigationRun).where(
                InvestigationRun.organization_id == authorized_id, InvestigationRun.status == "awaiting_approval",
            )),
        }
    return {
        "organization": {"id": org.id, "name": org.name},
        "health_score": None,
        "investigations": investigations,
        "active_incidents": open_incidents.count(),
        "activity": dashboard_activity(db, authorized_id),
        "database": db.get_bind().dialect.name,
        "intelligence_entities": entities,
        "intelligence_relationships": relationships,
        "recent_entities": [
            {"id": item.id, "entity_type": item.entity_type, "display_name": item.display_name}
            for item in recent_entities
        ],
        "recent_relationships": [
            {
                "id": item.id,
                "source_id": item.source_id,
                "target_id": item.target_id,
                "source": entity_names.get(item.source_id, "Unknown entity"),
                "target": entity_names.get(item.target_id, "Unknown entity"),
                "relationship_type": item.relationship_type,
                "confidence": item.confidence,
            }
            for item in recent_relationships
        ],
        "cybersecurity_posture": None,
        "recent_incidents": [
            {"id": item.id, "title": item.title, "severity": item.severity, "status": item.status,
             "created_at": item.created_at.replace(tzinfo=timezone.utc).isoformat()}
            for item in open_incidents.order_by(Incident.created_at.desc(), Incident.id).limit(10)
        ],
    }


@app.get("/api/v1/admin/users")
def list_organization_users(db: Session = Depends(get_db), user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    rows = db.scalars(select(User).where(
        User.organization_id == user.organization_id,
    ).order_by(User.created_at.desc(), User.id).limit(200)).all()
    return [{
        "id": row.id, "name": row.full_name, "email": row.email, "role": row.role,
        "is_active": row.is_active, "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
    } for row in rows]


@app.post("/api/v1/admin/users", status_code=201)
def create_organization_user(payload: UserCreateRequest, db: Session = Depends(get_db),
                             actor: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Email address is already registered")
    count = db.scalar(select(func.count()).select_from(User).where(User.organization_id == actor.organization_id))
    if count >= 500:
        raise HTTPException(429, "This organization reached its user capacity")
    row = User(organization_id=actor.organization_id, email=email, full_name=payload.full_name,
               password_hash=passwords.hash(payload.password), role=payload.role)
    db.add(row)
    db.flush()
    audit(db, actor.organization_id, actor.id, "organization.user.created", f"user:{row.id}",
          {"role": row.role})
    db.commit()
    return {"id": row.id, "name": row.full_name, "email": row.email, "role": row.role,
            "is_active": row.is_active, "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()}


@app.put("/api/v1/admin/users/{user_id}")
def update_organization_user(user_id: str, payload: UserUpdateRequest, db: Session = Depends(get_db),
                             actor: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    row = db.scalar(select(User).where(User.id == user_id, User.organization_id == actor.organization_id))
    if row is None:
        raise HTTPException(404, "User is unavailable")
    if row.id == actor.id and payload.is_active is False:
        raise HTTPException(409, "You cannot deactivate your own account")
    if row.role == "owner" and payload.is_active is False:
        raise HTTPException(409, "The organization owner cannot be deactivated")
    if row.role == "owner" and payload.role and payload.role != "owner":
        raise HTTPException(409, "The organization owner role cannot be changed through this endpoint")
    if payload.role is not None:
        row.role = payload.role
    if payload.is_active is not None:
        row.is_active = payload.is_active
        if not row.is_active:
            db.execute(update(AuthSession).where(AuthSession.user_id == row.id, AuthSession.revoked_at.is_(None)).values(
                revoked_at=utc_now_naive()))
    audit(db, actor.organization_id, actor.id, "organization.user.updated", f"user:{row.id}",
          {"role": row.role, "is_active": row.is_active})
    db.commit()
    return {"id": row.id, "name": row.full_name, "email": row.email, "role": row.role,
            "is_active": row.is_active}


@app.get("/api/v1/admin/organization")
def organization_configuration(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    org = db.get(Organization, user.organization_id)
    if org is None:
        raise HTTPException(404, "Organization is unavailable")
    return {
        "id": org.id, "name": org.name, "slug": org.slug, "timezone": org.timezone,
        "currency": org.currency, "industry": org.industry,
        "branding": json.loads(org.branding_json), "settings": json.loads(org.settings_json),
        "onboarding": json.loads(org.onboarding_json),
    }


@app.put("/api/v1/admin/organization")
def update_organization_configuration(payload: OrganizationSettingsRequest, db: Session = Depends(get_db),
                                     actor: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    org = db.get(Organization, actor.organization_id)
    if org is None:
        raise HTTPException(404, "Organization is unavailable")
    org.name = payload.name
    org.timezone = payload.timezone
    org.currency = payload.currency.upper()
    org.industry = payload.industry
    org.branding_json = json.dumps(payload.branding)
    org.settings_json = json.dumps(payload.settings)
    org.onboarding_json = json.dumps(payload.onboarding)
    audit(db, actor.organization_id, actor.id, "organization.configuration.updated",
          f"organization:{org.id}", {"timezone": org.timezone, "currency": org.currency,
                                     "industry": org.industry, "onboarding": payload.onboarding})
    db.commit()
    return organization_configuration(db=db, user=actor)


@app.get("/api/v1/admin/role-matrix")
def organization_role_matrix(user: User = Depends(get_current_user)):
    return {
        "roles": [
            {"name": "owner", "scope": "organization", "description": "Full organization administration; protected from deactivation."},
            {"name": "organization_admin", "scope": "organization", "description": "Administration of organization users and configuration."},
            {"name": "security_analyst", "scope": "tenant", "description": "Security operations, detections, incidents, assets, and findings."},
            {"name": "forensic_investigator", "scope": "tenant", "description": "Cases, evidence custody, reports, and forensic investigation."},
            {"name": "business_analyst", "scope": "tenant", "description": "Commerce intelligence and business analytics."},
            {"name": "automation_engineer", "scope": "tenant", "description": "Workflow definitions and execution."},
            {"name": "viewer", "scope": "tenant", "description": "Read-only access to permitted organization workspaces."},
        ],
        "effective_permissions": {
            "owner": "all tenant operations",
            "organization_admin": "tenant administration and permitted domain operations",
            "security_analyst": "security and incident operations",
            "forensic_investigator": "forensic and evidence operations",
            "business_analyst": "commerce and business operations",
            "automation_engineer": "workflow operations",
            "viewer": "authorized read access",
        },
    }


def api_credential_record(row: ApiCredential) -> dict:
    return {
        "id": row.id, "name": row.name, "prefix": row.prefix,
        "scopes": json.loads(row.scopes_json),
        "expires_at": row.expires_at.replace(tzinfo=timezone.utc).isoformat(),
        "revoked_at": row.revoked_at.replace(tzinfo=timezone.utc).isoformat() if row.revoked_at else None,
        "last_used_at": row.last_used_at.replace(tzinfo=timezone.utc).isoformat() if row.last_used_at else None,
        "usage_count": row.usage_count,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
    }


@app.get("/api/v1/developer/credentials")
def list_api_credentials(db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    rows = db.scalars(select(ApiCredential).where(
        ApiCredential.organization_id == user.organization_id,
    ).order_by(ApiCredential.created_at.desc()).limit(200)).all()
    return [api_credential_record(row) for row in rows]


@app.post("/api/v1/developer/credentials", status_code=201)
def create_api_credential(payload: ApiCredentialCreateRequest, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    count = db.scalar(select(func.count()).select_from(ApiCredential).where(
        ApiCredential.organization_id == user.organization_id,
        or_(ApiCredential.revoked_at.is_(None), ApiCredential.revoked_at > utc_now_naive()),
    ))
    if count >= 20:
        raise HTTPException(429, "This organization reached its API credential limit")
    secret = "vyrn_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    row = ApiCredential(
        organization_id=user.organization_id, owner_id=user.id, name=payload.name,
        secret_hash=digest, prefix=secret[:12], scopes_json=json.dumps(payload.scopes),
        expires_at=payload.expires_at.replace(tzinfo=None),
    )
    db.add(row)
    db.flush()
    audit(db, user.organization_id, user.id, "developer.credential.created", f"api_credential:{row.id}",
          {"name": row.name, "prefix": row.prefix, "scopes": payload.scopes})
    db.commit()
    db.refresh(row)
    return api_credential_record(row) | {"secret": secret, "notice": "Store this secret now. It cannot be shown again."}


@app.post("/api/v1/developer/credentials/{credential_id}/revoke")
def revoke_api_credential(credential_id: str, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    row = db.scalar(select(ApiCredential).where(
        ApiCredential.id == credential_id, ApiCredential.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "API credential is unavailable")
    if row.revoked_at is None:
        row.revoked_at = utc_now_naive()
        audit(db, user.organization_id, user.id, "developer.credential.revoked",
              f"api_credential:{row.id}", {"prefix": row.prefix})
        db.commit()
    return api_credential_record(row)


def notification_record(row: Notification) -> dict:
    return {
        "id": row.id, "category": row.category, "title": row.title,
        "resource": row.resource, "href": row.href,
        "details": json.loads(row.details_json),
        "read": row.read_at is not None,
        "read_at": row.read_at.replace(tzinfo=timezone.utc).isoformat() if row.read_at else None,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def emit_notification(db: Session, user: User, *, category: str, title: str, resource: str,
                      href: str, dedupe_key: str, details: dict):
    existing = db.scalar(select(Notification.id).where(
        Notification.organization_id == user.organization_id,
        Notification.owner_id == user.id,
        Notification.dedupe_key == dedupe_key,
    ))
    if existing:
        return
    db.add(Notification(
        organization_id=user.organization_id, owner_id=user.id, category=category,
        title=title, resource=resource, href=href, details_json=json.dumps(details),
        dedupe_key=dedupe_key,
    ))


@app.get("/api/v1/notifications")
def list_notifications(category: str | None = Query(default=None, max_length=40),
                       unread: bool | None = None,
                       limit: int = Query(default=100, ge=1, le=500),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Notification).where(
        Notification.organization_id == user.organization_id,
        Notification.owner_id == user.id,
    )
    if category:
        stmt = stmt.where(Notification.category == category)
    if unread is True:
        stmt = stmt.where(Notification.read_at.is_(None))
    elif unread is False:
        stmt = stmt.where(Notification.read_at.is_not(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id).limit(limit)).all()
    return [notification_record(row) for row in rows]


@app.get("/api/v1/notifications/unread-count")
def unread_notification_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.organization_id == user.organization_id,
        Notification.owner_id == user.id,
        Notification.read_at.is_(None),
    ))
    return {"count": count or 0}


@app.post("/api/v1/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    row = db.scalar(select(Notification).where(
        Notification.id == notification_id,
        Notification.organization_id == user.organization_id,
        Notification.owner_id == user.id,
    ))
    if row is None:
        raise HTTPException(404, "Notification is unavailable")
    if row.read_at is None:
        row.read_at = utc_now_naive()
        db.commit()
    return notification_record(row)


@app.post("/api/v1/notifications/read-all")
def mark_notifications_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    now = utc_now_naive()
    count = db.execute(update(Notification).where(
        Notification.organization_id == user.organization_id,
        Notification.owner_id == user.id,
        Notification.read_at.is_(None),
    ).values(read_at=now)).rowcount
    db.commit()
    return {"marked_read": count}


@app.get("/api/v1/admin/audit")
def organization_audit(db: Session = Depends(get_db), user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    rows = db.scalars(select(AuditLog).where(
        AuditLog.organization_id == user.organization_id,
    ).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(200)).all()
    return [{"id": row.id, "action": row.action, "resource": row.resource,
             "details": json.loads(row.details), "created_at": utc(row.created_at)} for row in rows]


@app.get("/api/v1/admin/notifications")
def organization_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    actions = ("incident.status", "incident.created", "evidence.upload", "workflow.approval",
               "workflow.completed", "knowledge.document.versioned", "organization.user.updated")
    rows = db.scalars(select(AuditLog).where(
        AuditLog.organization_id == user.organization_id,
        or_(AuditLog.action.in_(actions), AuditLog.action.like("workflow.%")),
    ).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(50)).all()
    return [{"id": row.id, "title": row.action.replace(".", " ").title(),
             "resource": row.resource, "details": json.loads(row.details),
             "created_at": utc(row.created_at)} for row in rows]


@app.get("/api/v1/admin/threat-intelligence")
def tenant_threat_intelligence(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entities = db.scalars(select(IntelligenceEntity).where(
        IntelligenceEntity.organization_id == user.organization_id,
    ).order_by(IntelligenceEntity.created_at.desc()).limit(100)).all()
    relationships = db.scalars(select(IntelligenceRelationship).where(
        IntelligenceRelationship.organization_id == user.organization_id,
    ).order_by(IntelligenceRelationship.occurred_at.desc()).limit(100)).all()
    alerts = db.scalars(select(DetectionAlert).where(
        DetectionAlert.organization_id == user.organization_id,
    ).order_by(DetectionAlert.created_at.desc()).limit(100)).all()
    indicators = db.scalars(select(ThreatIndicator).where(
        ThreatIndicator.organization_id == user.organization_id,
    ).order_by(ThreatIndicator.updated_at.desc()).limit(100)).all()
    return {
        "entities": [{"id": row.id, "type": row.entity_type, "name": row.display_name,
                      "external_id": row.external_id, "created_at": utc(row.created_at)} for row in entities],
        "relationships": [{"id": row.id, "source_id": row.source_id, "target_id": row.target_id,
                           "type": row.relationship_type, "confidence": row.confidence,
                           "source_reference": row.source_reference} for row in relationships],
        "alerts": [{"id": row.id, "rule": row.rule_kind, "severity": row.severity,
                    "status": row.status, "created_at": utc(row.created_at)} for row in alerts],
        "indicators": [threat_indicator_record(row) for row in indicators],
    }


@app.get("/api/v1/admin/integrations")
def tenant_integrations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sources = db.scalars(select(DataSource).where(
        DataSource.organization_id == user.organization_id,
    ).order_by(DataSource.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "name": row.name, "kind": row.kind, "active": row.active,
             "created_at": utc(row.created_at)} for row in sources]


@app.get("/api/v1/admin/platform")
def tenant_platform_status(db: Session = Depends(get_db), user: User = Depends(require_roles(*ORG_ADMIN_ROLES))):
    org = db.get(Organization, user.organization_id)
    return {
        "scope": "organization",
        "organization": {"id": org.id, "name": org.name, "slug": org.slug},
        "users": db.scalar(select(func.count()).select_from(User).where(User.organization_id == org.id)),
        "active_users": db.scalar(select(func.count()).select_from(User).where(
            User.organization_id == org.id, User.is_active.is_(True))),
        "audit_records": db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.organization_id == org.id)),
        "data_sources": db.scalar(select(func.count()).select_from(DataSource).where(DataSource.organization_id == org.id)),
        "health": "connected",
        "cross_tenant_access": "not_available",
    }


@app.post("/api/v1/intelligence/entities")
def create_entity(
    payload: EntityRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENTITY_WRITER_ROLES)),
):
    organization_id = _authorized_organization(user, payload.organization_id)
    entity = IntelligenceEntity(
        organization_id=organization_id,
        entity_type=payload.entity_type,
        external_id=payload.external_id,
        display_name=payload.display_name,
        properties=json.dumps(payload.properties),
    )
    db.add(entity)
    db.flush()
    audit(db, organization_id, user.id, "intelligence.entity.create", f"entity:{entity.id}", {"type": payload.entity_type})
    db.commit()
    db.refresh(entity)
    return {"id": entity.id, "entity_type": entity.entity_type, "display_name": entity.display_name}


@app.get("/api/v1/intelligence/entities")
def list_entities(
    organization_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    entities = db.query(IntelligenceEntity).filter(IntelligenceEntity.organization_id == authorized_id).all()
    return [{"id": item.id, "entity_type": item.entity_type, "external_id": item.external_id, "display_name": item.display_name} for item in entities]


@app.get("/api/v1/intelligence/graph")
def intelligence_graph(
    focus_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    organization_id = user.organization_id
    if focus_id:
        focus = db.query(IntelligenceEntity).filter(
            IntelligenceEntity.id == focus_id,
            IntelligenceEntity.organization_id == organization_id,
        ).first()
        if not focus:
            raise HTTPException(404, "Entity not found")
        relationships = db.query(IntelligenceRelationship).filter(
            IntelligenceRelationship.organization_id == organization_id,
            (IntelligenceRelationship.source_id == focus_id) | (IntelligenceRelationship.target_id == focus_id),
        ).order_by(IntelligenceRelationship.occurred_at.desc()).limit(500).all()
        entity_ids = {focus_id}
        for relationship in relationships:
            entity_ids.add(relationship.source_id)
            entity_ids.add(relationship.target_id)
        entities = db.query(IntelligenceEntity).filter(
            IntelligenceEntity.organization_id == organization_id,
            IntelligenceEntity.id.in_(entity_ids),
        ).all()
        truncated = False
    else:
        entity_query = db.query(IntelligenceEntity).filter(
            IntelligenceEntity.organization_id == organization_id
        ).order_by(IntelligenceEntity.created_at.desc())
        entities = entity_query.limit(501).all()
        truncated = len(entities) > 500
        entities = entities[:500]
        entity_ids = {item.id for item in entities}
        relationships = db.query(IntelligenceRelationship).filter(
            IntelligenceRelationship.organization_id == organization_id,
            IntelligenceRelationship.source_id.in_(entity_ids or [""]),
            IntelligenceRelationship.target_id.in_(entity_ids or [""]),
        ).order_by(IntelligenceRelationship.occurred_at.desc()).limit(1001).all()
        truncated = truncated or len(relationships) > 1000
        relationships = relationships[:1000]

    names = {item.id: item.display_name for item in entities}
    entity_data = []
    for item in entities:
        try:
            properties = json.loads(item.properties or "{}")
        except (json.JSONDecodeError, TypeError):
            properties = {}
        entity_data.append({
            "id": item.id,
            "entity_type": item.entity_type,
            "external_id": item.external_id,
            "display_name": item.display_name,
            "properties": properties,
            "created_at": item.created_at.isoformat() + "Z",
        })

    relationship_data = [{
        "id": item.id,
        "source_id": item.source_id,
        "target_id": item.target_id,
        "source": names.get(item.source_id, "Unknown entity"),
        "target": names.get(item.target_id, "Unknown entity"),
        "relationship_type": item.relationship_type,
        "confidence": item.confidence,
        "source_reference": item.source_reference,
        "occurred_at": item.occurred_at.isoformat() + "Z",
    } for item in relationships]

    timeline = [{
        "id": f"relationship:{item.id}",
        "event_type": "relationship",
        "timestamp": item.occurred_at.isoformat() + "Z",
        "label": f"{names.get(item.source_id, 'Entity')} {item.relationship_type} {names.get(item.target_id, 'entity')}",
        "reference": item.source_reference,
        "entity_id": item.source_id if item.source_id in entity_ids else item.target_id,
    } for item in relationships]
    incidents = db.query(Incident).filter(
        Incident.organization_id == organization_id
    ).order_by(Incident.created_at.desc()).limit(100).all()
    timeline.extend({
        "id": f"incident:{item.id}",
        "event_type": "incident",
        "timestamp": item.created_at.isoformat() + "Z",
        "label": item.title,
        "reference": item.id,
        "entity_id": None,
    } for item in incidents)
    evidence_items = db.query(Evidence).filter(
        Evidence.organization_id == organization_id
    ).order_by(Evidence.created_at.desc()).limit(100).all()
    timeline.extend({
        "id": f"evidence:{item.id}",
        "event_type": "evidence",
        "timestamp": item.created_at.isoformat() + "Z",
        "label": item.name,
        "reference": item.sha256,
        "entity_id": None,
    } for item in evidence_items)
    timeline.sort(key=lambda event: event["timestamp"], reverse=True)
    return {
        "organization_id": organization_id,
        "focus_id": focus_id,
        "truncated": truncated,
        "entities": entity_data,
        "relationships": relationship_data,
        "timeline": timeline[:200],
    }


@app.get("/api/v1/intelligence/graph/bookmarks")
def list_graph_bookmarks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(GraphBookmark).filter(
        GraphBookmark.organization_id == user.organization_id,
        GraphBookmark.user_id == user.id,
    ).order_by(GraphBookmark.created_at.desc()).all()
    return [{
        "id": row.id,
        "name": row.name,
        "entity_ids": json.loads(row.entity_ids),
        "filters": json.loads(row.filters),
        "created_at": row.created_at.isoformat() + "Z",
    } for row in rows]


@app.post("/api/v1/intelligence/graph/bookmarks")
def create_graph_bookmark(
    payload: GraphBookmarkRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.entity_ids:
        found = {row[0] for row in db.query(IntelligenceEntity.id).filter(
            IntelligenceEntity.organization_id == user.organization_id,
            IntelligenceEntity.id.in_(payload.entity_ids),
        ).all()}
        if found != set(payload.entity_ids):
            raise HTTPException(404, "Bookmarked entity not found")
    bookmark = GraphBookmark(
        organization_id=user.organization_id,
        user_id=user.id,
        name=payload.name.strip(),
        entity_ids=json.dumps(payload.entity_ids),
        filters=json.dumps(payload.filters),
    )
    db.add(bookmark)
    db.flush()
    audit(db, user.organization_id, user.id, "intelligence.bookmark.create", f"bookmark:{bookmark.id}", {"name": bookmark.name})
    db.commit()
    return {"id": bookmark.id, "name": bookmark.name, "entity_ids": payload.entity_ids, "filters": payload.filters}


@app.post("/api/v1/intelligence/relationships")
def create_relationship(
    payload: RelationshipRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENTITY_WRITER_ROLES)),
):
    organization_id = _authorized_organization(user, payload.organization_id)
    if not 0 <= payload.confidence <= 1:
        raise HTTPException(400, "Confidence must be between 0 and 1")
    entity_ids = {row[0] for row in db.query(IntelligenceEntity.id).filter(
        IntelligenceEntity.organization_id == organization_id,
        IntelligenceEntity.id.in_([payload.source_id, payload.target_id]),
    ).all()}
    if payload.source_id not in entity_ids or payload.target_id not in entity_ids:
        raise HTTPException(404, "Related entity not found")
    relationship = IntelligenceRelationship(
        organization_id=organization_id,
        source_id=payload.source_id,
        target_id=payload.target_id,
        relationship_type=payload.relationship_type,
        confidence=payload.confidence,
        source_reference=payload.source_reference,
    )
    db.add(relationship)
    db.flush()
    audit(db, organization_id, user.id, "intelligence.relationship.create", f"relationship:{relationship.id}", {"type": payload.relationship_type})
    db.commit()
    db.refresh(relationship)
    return {"id": relationship.id, "relationship_type": relationship.relationship_type, "confidence": relationship.confidence}


@app.post("/api/v1/incidents")
def create_incident(
    payload: IncidentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES)),
):
    organization_id = _authorized_organization(user, payload.organization_id)
    incident = Incident(
        organization_id=organization_id,
        title=payload.title,
        severity=payload.severity,
        description=payload.description,
    )
    db.add(incident)
    db.flush()
    db.add(IncidentEvent(
        organization_id=organization_id,
        incident_id=incident.id,
        actor_id=user.id,
        event_type="created",
        from_status="",
        to_status=incident.status,
        note="Incident created",
    ))
    audit(db, organization_id, user.id, "incident.create", f"incident:{incident.id}", {"severity": payload.severity})
    db.commit()
    db.refresh(incident)
    return {"id": incident.id, "title": incident.title, "severity": incident.severity, "status": incident.status}


@app.get("/api/v1/incidents")
def list_incidents(
    organization_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    incidents = db.query(Incident).filter(Incident.organization_id == authorized_id).all()
    result = []
    for item in incidents:
        assignee = db.get(User, item.assignee_id) if item.assignee_id else None
        result.append({"id": item.id, "title": item.title, "severity": item.severity, "status": item.status,
                       "assignee_id": item.assignee_id, "assignee_name": assignee.full_name if assignee else None,
                       "team": item.team})
    return result


@app.patch("/api/v1/incidents/{incident_id}/status")
def transition_incident(
    incident_id: str,
    payload: IncidentStatusRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES)),
):
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.organization_id == user.organization_id,
    ).first()
    if incident is None:
        raise HTTPException(404, "Incident not found")
    target = payload.status.strip().lower()
    if target not in INCIDENT_TRANSITIONS:
        raise HTTPException(422, "Unsupported incident status")
    if target not in INCIDENT_TRANSITIONS.get(incident.status.lower(), set()):
        raise HTTPException(409, f"Cannot transition incident from {incident.status} to {target}")
    previous = incident.status
    incident.status = target
    event = IncidentEvent(
        organization_id=user.organization_id,
        incident_id=incident.id,
        actor_id=user.id,
        from_status=previous,
        to_status=target,
        event_type="status_changed",
        note=payload.note,
    )
    db.add(event)
    db.flush()
    audit(db, user.organization_id, user.id, "incident.status_transition", f"incident:{incident.id}", {
        "from": previous, "to": target, "event_id": event.id,
    })
    db.commit()
    return {"id": incident.id, "title": incident.title, "severity": incident.severity,
            "status": incident.status, "event_id": event.id, "created_at": event.created_at.isoformat()}


@app.put("/api/v1/incidents/{incident_id}/assignment")
def assign_incident(incident_id: str, payload: IncidentAssignmentRequest, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES))):
    incident = db.scalar(select(Incident).where(Incident.id == incident_id,
                                                Incident.organization_id == user.organization_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    if payload.assignee_id:
        assignee = db.scalar(select(User).where(User.id == payload.assignee_id,
                                                User.organization_id == user.organization_id,
                                                User.is_active.is_(True)))
        if assignee is None:
            raise HTTPException(404, "Assignee is unavailable")
    previous = {"assignee_id": incident.assignee_id, "team": incident.team}
    incident.assignee_id = payload.assignee_id
    incident.team = payload.team
    event = IncidentEvent(
        organization_id=user.organization_id, incident_id=incident.id, actor_id=user.id,
        event_type="assignment_changed", from_status=incident.status, to_status=incident.status,
        note=f"Assignment changed from {previous} to {{'assignee_id': {payload.assignee_id}, 'team': '{payload.team}'}}",
    )
    db.add(event)
    audit(db, user.organization_id, user.id, "incident.assignment_changed", f"incident:{incident.id}",
          {"from": previous, "to": {"assignee_id": payload.assignee_id, "team": payload.team}})
    if assignee:
        emit_notification(
            db, assignee, category="incident_assignment",
            title=f"Incident assigned: {incident.title}",
            resource=f"incident:{incident.id}",
            href=f"/platform/incidents?id={incident.id}",
            dedupe_key=f"incident-assignment:{incident.id}:{assignee.id}",
            details={"severity": incident.severity, "status": incident.status, "team": payload.team},
        )
    db.commit()
    assignee = db.get(User, incident.assignee_id) if incident.assignee_id else None
    return {"id": incident.id, "title": incident.title, "severity": incident.severity, "status": incident.status,
            "assignee_id": incident.assignee_id, "assignee_name": assignee.full_name if assignee else None,
            "team": incident.team}


@app.get("/api/v1/incidents/{incident_id}/history")
def incident_history(
    incident_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = db.query(Incident.id).filter(
        Incident.id == incident_id,
        Incident.organization_id == user.organization_id,
    ).first()
    if incident is None:
        raise HTTPException(404, "Incident not found")
    events = db.query(IncidentEvent).filter(
        IncidentEvent.incident_id == incident_id,
        IncidentEvent.organization_id == user.organization_id,
    ).order_by(IncidentEvent.created_at.asc()).all()
    return [{"id": event.id, "event_type": event.event_type,
             "from_status": event.from_status, "to_status": event.to_status,
             "note": event.note, "actor_id": event.actor_id,
             "created_at": event.created_at.isoformat()} for event in events]


@app.get("/api/v1/assets")
def list_assets(
    organization_id: str | None = None,
    search: str = Query(default="", max_length=200),
    status: str | None = Query(default=None, pattern="^(active|maintenance|retired)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    query = db.query(Asset).filter(Asset.organization_id == authorized_id)
    if search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter((Asset.name.ilike(pattern)) | (Asset.identifier.ilike(pattern)) | (Asset.asset_type.ilike(pattern)))
    if status:
        query = query.filter(Asset.status == status)
    assets = query.order_by(Asset.updated_at.desc(), Asset.name.asc()).limit(500).all()
    return [{"id": item.id, "name": item.name, "asset_type": item.asset_type,
             "identifier": item.identifier, "criticality": item.criticality,
             "status": item.status, "created_at": item.created_at.isoformat(),
             "updated_at": item.updated_at.isoformat()} for item in assets]


@app.post("/api/v1/assets")
def create_asset(
    payload: AssetRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSET_WRITER_ROLES)),
):
    organization_id = _authorized_organization(user, payload.organization_id)
    asset = Asset(
        organization_id=organization_id,
        name=payload.name.strip(),
        asset_type=payload.asset_type.strip(),
        identifier=payload.identifier.strip(),
        criticality=payload.criticality,
        status=payload.status,
    )
    db.add(asset)
    db.flush()
    audit(db, organization_id, user.id, "asset.create", f"asset:{asset.id}", {
        "asset_type": asset.asset_type, "criticality": asset.criticality,
    })
    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "name": asset.name, "asset_type": asset.asset_type,
            "identifier": asset.identifier, "criticality": asset.criticality,
            "status": asset.status, "created_at": asset.created_at.isoformat(),
            "updated_at": asset.updated_at.isoformat()}


def owned_asset(db: Session, asset_id: str, user: User) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.organization_id == user.organization_id))
    if asset is None:
        raise HTTPException(404, "Asset is unavailable")
    return asset


@app.get("/api/v1/assets/{asset_id}")
def inspect_asset(asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = owned_asset(db, asset_id, user)
    assignment = db.get(AssetAssignment, asset.id)
    assignee = db.get(User, assignment.assignee_id) if assignment and assignment.assignee_id else None
    vulnerabilities = db.scalars(select(AssetVulnerability).where(
        AssetVulnerability.asset_id == asset.id,
        AssetVulnerability.organization_id == user.organization_id,
    ).order_by(AssetVulnerability.updated_at.desc(), AssetVulnerability.id).limit(100)).all()
    history = db.scalars(select(AssetHistory).where(
        AssetHistory.asset_id == asset.id,
        AssetHistory.organization_id == user.organization_id,
    ).order_by(AssetHistory.created_at.desc(), AssetHistory.id).limit(100)).all()
    return {
        "id": asset.id, "name": asset.name, "asset_type": asset.asset_type,
        "identifier": asset.identifier, "criticality": asset.criticality, "status": asset.status,
        "created_at": asset.created_at.isoformat(), "updated_at": asset.updated_at.isoformat(),
        "assignment": {
            "assignee_id": assignment.assignee_id if assignment else None,
            "assignee_name": assignee.full_name if assignee else None,
            "team": assignment.team if assignment else "",
            "updated_at": assignment.updated_at.isoformat() if assignment else None,
        },
        "vulnerabilities": [{
            "id": row.id, "title": row.title, "cve": row.cve, "severity": row.severity,
            "status": row.status, "remediation": row.remediation, "details": json.loads(row.details_json),
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        } for row in vulnerabilities],
        "history": [{
            "id": row.id, "actor_id": row.actor_id, "action": row.action,
            "before": json.loads(row.before_json), "after": json.loads(row.after_json),
            "created_at": row.created_at.isoformat(),
        } for row in history],
    }


@app.put("/api/v1/assets/{asset_id}")
def update_asset(asset_id: str, payload: AssetUpdateRequest, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ASSET_WRITER_ROLES))):
    asset = owned_asset(db, asset_id, user)
    before = {"name": asset.name, "asset_type": asset.asset_type, "identifier": asset.identifier,
             "criticality": asset.criticality, "status": asset.status}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, field, value if field != "identifier" or value is not None else "")
    asset.updated_at = utc_now_naive()
    after = {"name": asset.name, "asset_type": asset.asset_type, "identifier": asset.identifier,
            "criticality": asset.criticality, "status": asset.status}
    db.add(AssetHistory(organization_id=user.organization_id, asset_id=asset.id, actor_id=user.id,
                       action="asset.updated", before_json=json.dumps(before), after_json=json.dumps(after)))
    audit(db, user.organization_id, user.id, "asset.updated", f"asset:{asset.id}", after)
    db.commit()
    db.refresh(asset)
    return inspect_asset(asset.id, db, user)


@app.put("/api/v1/assets/{asset_id}/assignment")
def assign_asset(asset_id: str, payload: AssetAssignmentRequest, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ASSET_WRITER_ROLES))):
    asset = owned_asset(db, asset_id, user)
    if payload.assignee_id:
        assignee = db.scalar(select(User).where(User.id == payload.assignee_id,
                                               User.organization_id == user.organization_id,
                                               User.is_active.is_(True)))
        if assignee is None:
            raise HTTPException(404, "Assignee is unavailable")
    assignment = db.get(AssetAssignment, asset.id)
    before = {"assignee_id": assignment.assignee_id if assignment else None, "team": assignment.team if assignment else ""}
    if assignment is None:
        assignment = AssetAssignment(asset_id=asset.id, organization_id=user.organization_id)
        db.add(assignment)
    assignment.assignee_id = payload.assignee_id
    assignment.team = payload.team
    assignment.updated_at = utc_now_naive()
    after = {"assignee_id": payload.assignee_id, "team": payload.team}
    db.add(AssetHistory(organization_id=user.organization_id, asset_id=asset.id, actor_id=user.id,
                       action="asset.assigned", before_json=json.dumps(before), after_json=json.dumps(after)))
    audit(db, user.organization_id, user.id, "asset.assigned", f"asset:{asset.id}", after)
    if payload.assignee_id:
        assignee = db.get(User, payload.assignee_id)
        if assignee:
            emit_notification(
                db, assignee, category="asset_assignment",
                title=f"Asset assigned: {asset.name}",
                resource=f"asset:{asset.id}", href="/platform/assets",
                dedupe_key=f"asset-assignment:{asset.id}:{assignee.id}",
                details={"team": payload.team, "asset_type": asset.asset_type, "criticality": asset.criticality},
            )
    db.commit()
    return inspect_asset(asset.id, db, user)


@app.post("/api/v1/assets/{asset_id}/vulnerabilities", status_code=201)
def add_asset_vulnerability(asset_id: str, payload: AssetVulnerabilityRequest, db: Session = Depends(get_db),
                           user: User = Depends(require_roles(*ASSET_WRITER_ROLES))):
    asset = owned_asset(db, asset_id, user)
    vulnerability = AssetVulnerability(
        organization_id=user.organization_id, asset_id=asset.id, title=payload.title,
        cve=payload.cve.upper(), severity=payload.severity, status=payload.status,
        remediation=payload.remediation,
    )
    db.add(vulnerability)
    db.flush()
    db.add(AssetHistory(organization_id=user.organization_id, asset_id=asset.id, actor_id=user.id,
                       action="vulnerability.recorded", before_json="{}",
                       after_json=json.dumps({"id": vulnerability.id, "severity": vulnerability.severity,
                                              "status": vulnerability.status})))
    audit(db, user.organization_id, user.id, "asset.vulnerability.recorded", f"asset:{asset.id}",
          {"vulnerability_id": vulnerability.id, "severity": vulnerability.severity})
    db.commit()
    db.refresh(vulnerability)
    return {"id": vulnerability.id, "title": vulnerability.title, "cve": vulnerability.cve,
            "severity": vulnerability.severity, "status": vulnerability.status,
            "remediation": vulnerability.remediation}


THREAT_WRITER_ROLES = ORG_ADMIN_ROLES | {"security_analyst"}


def threat_indicator_record(row: ThreatIndicator) -> dict:
    return {
        "id": row.id, "indicator_type": row.indicator_type, "value": row.value,
        "classification": row.classification, "confidence": row.confidence,
        "provenance": row.provenance, "notes": row.notes, "status": row.status,
        "expires_at": row.expires_at.replace(tzinfo=timezone.utc).isoformat() if row.expires_at else None,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


@app.get("/api/v1/threat-indicators")
def list_threat_indicators(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(ThreatIndicator).where(
        ThreatIndicator.organization_id == user.organization_id,
    ).order_by(ThreatIndicator.updated_at.desc(), ThreatIndicator.value).limit(500)).all()
    return [threat_indicator_record(row) for row in rows]


@app.post("/api/v1/threat-indicators", status_code=201)
def create_threat_indicator(payload: ThreatIndicatorRequest, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*THREAT_WRITER_ROLES))):
    value = payload.value.strip().lower()
    existing = db.scalar(select(ThreatIndicator.id).where(
        ThreatIndicator.organization_id == user.organization_id,
        ThreatIndicator.indicator_type == payload.indicator_type,
        ThreatIndicator.value == value,
    ))
    if existing:
        raise HTTPException(409, "This indicator is already recorded")
    row = ThreatIndicator(
        organization_id=user.organization_id, indicator_type=payload.indicator_type,
        value=value, classification=payload.classification, confidence=payload.confidence,
        provenance=payload.provenance, notes=payload.notes,
        expires_at=payload.expires_at.replace(tzinfo=None) if payload.expires_at else None,
    )
    db.add(row)
    db.flush()
    audit(db, user.organization_id, user.id, "threat.indicator.created", f"threat-indicator:{row.id}",
          {"indicator_type": row.indicator_type, "classification": row.classification,
           "confidence": row.confidence})
    db.commit()
    db.refresh(row)
    return threat_indicator_record(row)


@app.get("/api/v1/threat-indicators/{indicator_id}")
def inspect_threat_indicator(indicator_id: str, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    row = db.scalar(select(ThreatIndicator).where(
        ThreatIndicator.id == indicator_id, ThreatIndicator.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Threat indicator is unavailable")
    value = row.value.casefold()
    events = db.scalars(select(SecurityEvent).where(
        SecurityEvent.organization_id == user.organization_id,
        or_(SecurityEvent.title.ilike(f"%{value}%"),
            SecurityEvent.description.ilike(f"%{value}%"),
            SecurityEvent.source_reference.ilike(f"%{value}%")),
    ).order_by(SecurityEvent.occurred_at.desc()).limit(100)).all()
    assets = db.scalars(select(Asset).where(
        Asset.organization_id == user.organization_id,
        or_(Asset.name.ilike(f"%{value}%"), Asset.identifier.ilike(f"%{value}%")),
    ).order_by(Asset.updated_at.desc()).limit(100)).all()
    incidents = db.scalars(select(Incident).where(
        Incident.organization_id == user.organization_id,
        or_(Incident.title.ilike(f"%{value}%"), Incident.description.ilike(f"%{value}%")),
    ).order_by(Incident.created_at.desc()).limit(100)).all()
    return threat_indicator_record(row) | {
        "matches": {
            "security_events": [{"id": item.id, "title": item.title, "source_reference": item.source_reference,
                                 "occurred_at": item.occurred_at.replace(tzinfo=timezone.utc).isoformat()} for item in events],
            "assets": [{"id": item.id, "name": item.name, "identifier": item.identifier} for item in assets],
            "incidents": [{"id": item.id, "title": item.title, "status": item.status} for item in incidents],
        }
    }


@app.patch("/api/v1/threat-indicators/{indicator_id}")
def update_threat_indicator(indicator_id: str, payload: ThreatIndicatorRequest,
                            db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*THREAT_WRITER_ROLES))):
    row = db.scalar(select(ThreatIndicator).where(
        ThreatIndicator.id == indicator_id, ThreatIndicator.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Threat indicator is unavailable")
    row.indicator_type = payload.indicator_type
    row.value = payload.value.strip().lower()
    row.classification = payload.classification
    row.confidence = payload.confidence
    row.provenance = payload.provenance
    row.notes = payload.notes
    row.expires_at = payload.expires_at.replace(tzinfo=None) if payload.expires_at else None
    row.status = "expired" if row.expires_at and row.expires_at <= utc_now_naive() else "active"
    row.updated_at = utc_now_naive()
    audit(db, user.organization_id, user.id, "threat.indicator.updated", f"threat-indicator:{row.id}",
          {"classification": row.classification, "confidence": row.confidence, "status": row.status})
    db.commit()
    db.refresh(row)
    return threat_indicator_record(row)


@app.delete("/api/v1/threat-indicators/{indicator_id}", status_code=204)
def delete_threat_indicator(indicator_id: str, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*THREAT_WRITER_ROLES))):
    row = db.scalar(select(ThreatIndicator).where(
        ThreatIndicator.id == indicator_id, ThreatIndicator.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Threat indicator is unavailable")
    db.execute(delete(ThreatIndicator).where(ThreatIndicator.id == row.id))
    audit(db, user.organization_id, user.id, "threat.indicator.deleted", f"threat-indicator:{indicator_id}", {})
    db.commit()


REPORT_WRITERS = ("owner", "organization_admin", "security_analyst", "forensic_investigator",
                  "business_analyst", "automation_engineer")


def report_record(row: ReportRecord) -> dict:
    owner = None
    return {
        "id": row.id, "title": row.title, "category": row.category,
        "source_module": row.source_module, "source_id": row.source_id,
        "source_refs": json.loads(row.source_refs_json), "version": row.version,
        "status": row.status, "review_status": row.review_status,
        "integrity_hash": row.integrity_hash, "owner_id": row.owner_id,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def report_snapshot(db: Session, user: User, value: ReportCreateRequest) -> tuple[dict, list]:
    refs = []
    org = user.organization_id
    if value.source_module == "forensics":
        report = db.get(ForensicReport, value.source_id) if value.source_id else None
        if report is None or report.organization_id != org:
            raise HTTPException(404, "Forensic source report is unavailable")
        snapshot = json.loads(report.snapshot_json)
        refs = [{"kind": "forensic_report", "id": report.id}, {"kind": "case", "id": report.case_id}]
    elif value.source_module == "nexus":
        run = db.get(InvestigationRun, value.source_id) if value.source_id else None
        if run is None or run.organization_id != org:
            raise HTTPException(404, "Nexus source run is unavailable")
        snapshot = nexus_full_record(db, run)
        refs = [{"kind": "investigation_run", "id": run.id}]
    elif value.source_module == "security":
        rows = db.scalars(select(SecurityEvent).where(SecurityEvent.organization_id == org)
                          .order_by(SecurityEvent.occurred_at.desc()).limit(500)).all()
        snapshot = {"events": [security_event_record(row) for row in rows], "count": len(rows)}
        refs = [{"kind": "security_event", "id": row.id} for row in rows[:100]]
    elif value.source_module == "threat_intelligence":
        rows = db.scalars(select(ThreatIndicator).where(ThreatIndicator.organization_id == org)
                          .order_by(ThreatIndicator.updated_at.desc()).limit(500)).all()
        snapshot = {"indicators": [threat_indicator_record(row) for row in rows], "count": len(rows)}
        refs = [{"kind": "threat_indicator", "id": row.id} for row in rows]
    elif value.source_module == "assets":
        rows = db.scalars(select(Asset).where(Asset.organization_id == org)
                          .order_by(Asset.updated_at.desc()).limit(500)).all()
        snapshot = {"assets": [{"id": row.id, "name": row.name, "asset_type": row.asset_type,
                                "identifier": row.identifier, "criticality": row.criticality,
                                "status": row.status} for row in rows], "count": len(rows)}
        refs = [{"kind": "asset", "id": row.id} for row in rows]
    elif value.source_module == "incidents":
        rows = db.scalars(select(Incident).where(Incident.organization_id == org)
                          .order_by(Incident.created_at.desc()).limit(500)).all()
        snapshot = {"incidents": [{"id": row.id, "title": row.title, "severity": row.severity,
                                   "status": row.status, "team": row.team} for row in rows], "count": len(rows)}
        refs = [{"kind": "incident", "id": row.id} for row in rows]
    elif value.source_module == "fraud":
        rows = db.execute(select(CommerceFinding, CommerceRecord).join(
            CommerceRecord, CommerceRecord.id == CommerceFinding.refund_id,
        ).where(CommerceFinding.organization_id == org)
            .order_by(CommerceFinding.created_at.desc()).limit(500)).all()
        snapshot = {"findings": [finding_record(finding) | {"refund": commerce_record(record)}
                                 for finding, record in rows], "count": len(rows)}
        refs = [{"kind": "commerce_finding", "id": finding.id} for finding, _ in rows]
    elif value.source_module == "ecommerce":
        rows = db.scalars(select(CommerceRecord).where(CommerceRecord.organization_id == org)
                          .order_by(CommerceRecord.occurred_at.desc()).limit(500)).all()
        snapshot = {"transactions": [commerce_record(row) for row in rows], "count": len(rows)}
        refs = [{"kind": "commerce_record", "id": row.id} for row in rows]
    elif value.source_module == "business_intelligence":
        end = datetime.now(timezone.utc).date()
        snapshot = commerce_summary(db, org, end - timedelta(days=29), end, None)
        refs = [{"kind": "business_period", "id": f"{snapshot['period']['start']}:{snapshot['period']['end']}"}]
    elif value.source_module == "workflow":
        rows = db.scalars(select(Workflow).where(Workflow.organization_id == org)
                          .order_by(Workflow.created_at.desc()).limit(500)).all()
        snapshot = {"workflows": [{"id": row.id, "name": row.name, "enabled": row.enabled,
                                   "definition": json.loads(row.definition)} for row in rows], "count": len(rows)}
        refs = [{"kind": "workflow", "id": row.id} for row in rows]
    elif value.source_module == "digital_twin":
        rows = db.scalars(select(TwinSimulation).where(TwinSimulation.organization_id == org)
                          .order_by(TwinSimulation.created_at.desc()).limit(500)).all()
        snapshot = {"simulations": [{"id": row.id,
                                     "input": json.loads(row.input_json),
                                     "result": json.loads(row.result_json),
                                     "topology_digest": row.topology_digest,
                                     "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()}
                                    for row in rows], "count": len(rows)}
        refs = [{"kind": "digital_twin_simulation", "id": row.id} for row in rows]
    elif value.source_module == "copilot":
        conversation = db.get(CopilotConversation, value.source_id) if value.source_id else None
        if conversation is None or conversation.organization_id != org or conversation.owner_id != user.id:
            raise HTTPException(404, "Copilot source conversation is unavailable")
        turns = db.scalars(select(CopilotTurn).where(CopilotTurn.conversation_id == conversation.id)
                           .order_by(CopilotTurn.created_at).limit(100)).all()
        snapshot = {"conversation": {"id": conversation.id, "title": conversation.title},
                    "turns": [{"question": row.question, "answer": row.answer,
                               "status": row.status, "sources": json.loads(row.sources_json)}
                              for row in turns]}
        refs = [{"kind": "copilot_conversation", "id": conversation.id},
                *({"kind": "copilot_turn", "id": row.id} for row in turns)]
    else:
        raise HTTPException(422, "Unsupported report source")
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
        raise HTTPException(413, "Report snapshot exceeds the bounded size")
    return snapshot, refs


@app.get("/api/v1/reports")
def list_reports(category: str | None = Query(default=None, max_length=40),
                 source_module: str | None = Query(default=None, max_length=40),
                 search: str | None = Query(default=None, max_length=200),
                 limit: int = Query(default=100, ge=1, le=500),
                 offset: int = Query(default=0, ge=0),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(ReportRecord).where(ReportRecord.organization_id == user.organization_id)
    if category:
        stmt = stmt.where(ReportRecord.category == category)
    if source_module:
        stmt = stmt.where(ReportRecord.source_module == source_module)
    if search:
        stmt = stmt.where(ReportRecord.title.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ReportRecord.updated_at.desc(), ReportRecord.id)
                      .limit(limit).offset(offset)).all()
    return {"items": [report_record(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/v1/reports", status_code=201)
def create_report(value: ReportCreateRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*REPORT_WRITERS))):
    snapshot, refs = report_snapshot(db, user, value)
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    version = (db.scalar(select(func.max(ReportRecord.version)).where(
        ReportRecord.organization_id == user.organization_id,
        ReportRecord.source_module == value.source_module,
        ReportRecord.source_id == value.source_id,
        ReportRecord.title == value.title,
    )) or 0) + 1
    row = ReportRecord(organization_id=user.organization_id, owner_id=user.id,
                       title=value.title, category=value.category, source_module=value.source_module,
                       source_id=value.source_id, source_refs_json=json.dumps(refs),
                       version=version, snapshot_json=encoded,
                       integrity_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest())
    db.add(row)
    db.flush()
    audit(db, user.organization_id, user.id, "reports.created", f"report:{row.id}",
          {"title": row.title, "category": row.category, "source_module": row.source_module,
           "source_id": row.source_id, "version": row.version})
    emit_notification(
        db, user, category="report",
        title=f"Report completed: {row.title}",
        resource=f"report:{row.id}",
        href=f"/platform/reports",
        dedupe_key=f"report-created:{row.id}",
        details={"source_module": row.source_module, "version": row.version},
    )
    db.commit()
    db.refresh(row)
    return report_record(row)


@app.get("/api/v1/reports/{report_id}")
def inspect_report(report_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    row = db.scalar(select(ReportRecord).where(
        ReportRecord.id == report_id, ReportRecord.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Report is unavailable")
    snapshot = json.loads(row.snapshot_json)
    if row.category == "forensic" and row.source_module == "forensics":
        source = db.get(ForensicReport, row.source_id)
        if source is None or source.organization_id != user.organization_id:
            raise HTTPException(404, "Historical report source is no longer authorized")
    return report_record(row) | {"snapshot": snapshot}


@app.get("/api/v1/reports/{report_id}/export")
def export_report(report_id: str, format: Literal["json", "csv"] = Query("json"),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.scalar(select(ReportRecord).where(
        ReportRecord.id == report_id, ReportRecord.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Report is unavailable")
    if row.category == "forensic" and row.source_module == "forensics":
        source = db.get(ForensicReport, row.source_id)
        if source is None or source.organization_id != user.organization_id:
            raise HTTPException(404, "Historical report source is no longer authorized")
    snapshot = json.loads(row.snapshot_json)
    audit(db, user.organization_id, user.id, "reports.exported", f"report:{row.id}",
          {"format": format, "version": row.version})
    db.commit()
    if format == "json":
        body, mime = json.dumps(snapshot, ensure_ascii=False), "application/json"
    else:
        output = StringIO()
        writer = csv.DictWriter(output, ["field", "value"])
        writer.writeheader()
        for key, value in snapshot.items():
            writer.writerow({"field": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value})
        body, mime = output.getvalue(), "text/csv"
    return Response(body, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=report-{row.id}-v{row.version}.{format}",
        "Cache-Control": "private, no-store",
    })


@app.put("/api/v1/assets/{asset_id}/vulnerabilities/{vulnerability_id}")
def update_asset_vulnerability(asset_id: str, vulnerability_id: str, payload: AssetVulnerabilityUpdateRequest,
                              db: Session = Depends(get_db),
                              user: User = Depends(require_roles(*ASSET_WRITER_ROLES))):
    owned_asset(db, asset_id, user)
    vulnerability = db.scalar(select(AssetVulnerability).where(
        AssetVulnerability.id == vulnerability_id, AssetVulnerability.asset_id == asset_id,
        AssetVulnerability.organization_id == user.organization_id,
    ))
    if vulnerability is None:
        raise HTTPException(404, "Vulnerability is unavailable")
    before = vulnerability.status
    vulnerability.status = payload.status
    vulnerability.updated_at = utc_now_naive()
    db.add(AssetHistory(organization_id=user.organization_id, asset_id=asset_id, actor_id=user.id,
                       action="vulnerability.updated", before_json=json.dumps({"status": before}),
                       after_json=json.dumps({"status": payload.status})))
    audit(db, user.organization_id, user.id, "asset.vulnerability.updated", f"asset:{asset_id}",
          {"vulnerability_id": vulnerability.id, "status": payload.status})
    db.commit()
    db.refresh(vulnerability)
    return {"id": vulnerability.id, "title": vulnerability.title, "cve": vulnerability.cve,
            "severity": vulnerability.severity, "status": vulnerability.status,
            "remediation": vulnerability.remediation}


def security_event_record(event: SecurityEvent) -> dict:
    return {
        "id": event.id, "source": event.source, "event_type": event.event_type,
        "severity": event.severity, "title": event.title, "description": event.description,
        "source_reference": event.source_reference, "status": event.status,
        "occurred_at": event.occurred_at.replace(tzinfo=timezone.utc).isoformat(),
        "received_at": event.received_at.replace(tzinfo=timezone.utc).isoformat(),
    }


@app.get("/api/v1/security-events")
def list_security_events(
    organization_id: str | None = None,
    search: str = Query(default="", max_length=200),
    severity: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    status: str | None = Query(default=None, pattern="^(new|reviewed|dismissed)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    query = db.query(SecurityEvent).filter(SecurityEvent.organization_id == authorized_id)
    if search.strip():
        term = search.strip()
        query = query.filter(
            SecurityEvent.title.icontains(term, autoescape=True)
            | SecurityEvent.event_type.icontains(term, autoescape=True)
            | SecurityEvent.source_reference.icontains(term, autoescape=True)
        )
    if severity:
        query = query.filter(SecurityEvent.severity == severity)
    if status:
        query = query.filter(SecurityEvent.status == status)
    events = query.order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id).limit(limit).all()
    return [security_event_record(event) for event in events]


@app.post("/api/v1/security-events")
def ingest_security_event(
    payload: SecurityEventRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES)),
):
    organization_id = _authorized_organization(user, payload.organization_id)
    source = payload.source.strip().lower()
    if source.startswith("batch:"):
        raise HTTPException(422, "Managed source identifiers are reserved for batch ingestion")
    event_type = payload.event_type.strip().lower()
    account = payload.account.casefold() if payload.account else None
    device = payload.device.casefold() if payload.device else None
    if len(source) > 120 or len(event_type) > 120 or max(len(account or ""), len(device or "")) > 200:
        raise HTTPException(422, "A normalized identifier exceeds its maximum length")
    occurred_at = payload.occurred_at or utc_now_naive()
    if occurred_at.tzinfo is not None:
        occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    steps = {
        "source": source, "event_type": event_type, "account": account, "device": device,
        "occurred_at": occurred_at.isoformat() if payload.occurred_at else None,
    }
    fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json") | steps, sort_keys=True).encode()).hexdigest()

    def existing_record():
        prior = db.scalar(select(DetectionInput).where(
            DetectionInput.organization_id == organization_id, DetectionInput.source == source,
            DetectionInput.external_id == payload.external_id,
        ))
        if prior is None:
            return None
        if prior.payload_hash != fingerprint:
            raise HTTPException(409, "This source event ID is already associated with a different payload")
        return security_event_record(db.get(SecurityEvent, prior.event_id))

    if payload.external_id:
        existing = existing_record()
        if existing:
            return existing
    event = SecurityEvent(
        organization_id=organization_id,
        source=source,
        event_type=event_type,
        severity=payload.severity,
        title=payload.title.strip(),
        description=payload.description.strip(),
        source_reference=payload.source_reference.strip(),
        occurred_at=occurred_at,
    )
    db.add(event)
    db.flush()
    detection_input = DetectionInput(
        event_id=event.id, organization_id=organization_id, source=source,
        external_id=payload.external_id, payload_hash=fingerprint, account=account, device=device,
        outcome=payload.outcome, occurred_at=occurred_at,
    )
    try:
        db.add(detection_input)
        db.flush()
        audit(db, organization_id, user.id, "security_event.ingest", f"security_event:{event.id}", {
            "source": event.source, "event_type": event.event_type, "severity": event.severity,
        })
        if DETECTION_MODE != "worker":
            evaluate_detections(db, detection_input)
        db.commit()
    except IntegrityError:
        db.rollback()
        if payload.external_id:
            existing = existing_record()
            if existing:
                return existing
        raise
    if DETECTION_MODE == "worker":
        notify_worker()
    db.refresh(event)
    return security_event_record(event)


@app.patch("/api/v1/security-events/{event_id}/status")
def review_security_event(
    event_id: str,
    payload: SecurityEventReview,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES)),
):
    scoped = db.query(SecurityEvent).filter(
        SecurityEvent.id == event_id,
        SecurityEvent.organization_id == user.organization_id,
    )
    changed = scoped.filter(SecurityEvent.status == "new").update({"status": payload.status})
    event = scoped.first()
    if event is None:
        raise HTTPException(404, "Security event not found")
    if not changed and event.status != payload.status:
        raise HTTPException(409, "This security event has already been triaged")
    if changed:
        audit(db, user.organization_id, user.id, "security_event.review", f"security_event:{event_id}", {
            "from": "new", "to": payload.status,
        })
        db.commit()
    return security_event_record(event)


def detection_rule_record(rule: DetectionRule) -> dict:
    return {"id": rule.id, "kind": rule.kind, "title": RULE_TITLES[rule.kind], "enabled": rule.enabled,
            "severity": rule.severity, "window_minutes": rule.window_minutes, "threshold": rule.threshold}


@app.get("/api/v1/detection-rules")
def detection_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rules = db.scalars(select(DetectionRule).where(
        DetectionRule.organization_id == user.organization_id,
    ).order_by(DetectionRule.kind)).all()
    return [detection_rule_record(rule) for rule in rules]


@app.put("/api/v1/detection-rules/{kind}")
def save_detection_rule(
    kind: RuleKind,
    settings: DetectionRuleSettings,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*RULE_WRITER_ROLES)),
):
    selector = select(DetectionRule).where(
        DetectionRule.organization_id == user.organization_id, DetectionRule.kind == kind,
    )
    rule = db.scalar(selector)
    if rule is None:
        rule = DetectionRule(organization_id=user.organization_id, kind=kind)
        db.add(rule)
    for key, value in settings.model_dump().items():
        setattr(rule, key, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "The rule was created concurrently. Refresh and try again.") from exc
    audit(db, user.organization_id, user.id, "detection.rule.saved", f"detection_rule:{rule.id}", settings.model_dump())
    db.commit()
    return detection_rule_record(rule)


@app.get("/api/v1/detection-runs")
def detection_runs(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    rows = db.execute(select(DetectionRun, DetectionRule.kind).join(
        DetectionRule, (DetectionRule.id == DetectionRun.rule_id)
        & (DetectionRule.organization_id == DetectionRun.organization_id),
    ).where(DetectionRun.organization_id == user.organization_id)
        .order_by(DetectionRun.created_at.desc(), DetectionRun.id).limit(limit)).all()
    return [{"id": run.id, "kind": kind, "event_id": run.event_id, "alert_id": run.alert_id,
             "explanation": run.explanation, "created_at": run.created_at.replace(tzinfo=timezone.utc).isoformat()}
            for run, kind in rows]


@app.get("/api/v1/detection-status")
def detection_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    counts = dict(db.execute(select(DetectionInput.status, func.count()).where(
        DetectionInput.organization_id == user.organization_id,
    ).group_by(DetectionInput.status)).all())
    worker_available = None
    if DETECTION_MODE == "worker":
        client = redis_client()
        worker_available = False
        if client is not None:
            try:
                worker_available = bool(client.exists(HEARTBEAT_KEY))
            except RedisError:
                pass
            finally:
                client.close()
    return {"mode": DETECTION_MODE, "worker_available": worker_available,
            "queued": counts.get("queued", 0), "completed": counts.get("completed", 0), "failed": counts.get("failed", 0)}


def alert_record(alert: DetectionAlert, incident: Incident | None = None) -> dict:
    return {"id": alert.id, "title": alert.title, "severity": alert.severity, "status": alert.status,
            "explanation": alert.explanation, "rule_id": alert.rule_id, "incident_id": alert.incident_id,
            "incident_status": incident.status if incident else None,
            "graph_entity_id": correlation_node_id(incident.organization_id, "incident", incident.id) if incident else None,
            "created_at": alert.created_at.replace(tzinfo=timezone.utc).isoformat()}


@app.get("/api/v1/security-alerts")
def list_security_alerts(
    status: Literal["open", "confirmed", "false_positive"] | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    query = select(DetectionAlert, Incident).outerjoin(
        Incident, (Incident.id == DetectionAlert.incident_id)
        & (Incident.organization_id == DetectionAlert.organization_id),
    ).where(DetectionAlert.organization_id == user.organization_id)
    if status:
        query = query.where(DetectionAlert.status == status)
    rows = db.execute(query.order_by(DetectionAlert.created_at.desc(), DetectionAlert.id).limit(limit))
    return [alert_record(alert, incident) for alert, incident in rows]


def source_events(db: Session, alert: DetectionAlert):
    return db.execute(select(SecurityEvent, DetectionInput).join(
        DetectionAlertEvent, DetectionAlertEvent.event_id == SecurityEvent.id,
    ).join(DetectionInput, (DetectionInput.event_id == SecurityEvent.id)
           & (DetectionInput.organization_id == SecurityEvent.organization_id))
        .where(DetectionAlertEvent.alert_id == alert.id, SecurityEvent.organization_id == alert.organization_id)
        .order_by(SecurityEvent.occurred_at, SecurityEvent.id)).all()


def owned_alert(db: Session, alert_id: str, user: User) -> DetectionAlert:
    alert = db.scalar(select(DetectionAlert).where(
        DetectionAlert.id == alert_id, DetectionAlert.organization_id == user.organization_id,
    ))
    if alert is None:
        raise HTTPException(404, "Security alert not found")
    return alert


@app.get("/api/v1/security-alerts/{alert_id}/events")
def alert_events(alert_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alert = owned_alert(db, alert_id, user)
    return [security_event_record(event) | {"account": item.account, "device": item.device, "outcome": item.outcome}
            for event, item in source_events(db, alert)]


def claim_alert(db: Session, alert_id: str, organization_id: str, status: str) -> bool:
    result = db.execute(update(DetectionAlert).where(
        DetectionAlert.id == alert_id, DetectionAlert.organization_id == organization_id,
        DetectionAlert.status == "open",
    ).values(status=status))
    return result.rowcount == 1


@app.post("/api/v1/security-alerts/{alert_id}/false-positive")
def flag_false_positive(
    alert_id: str, feedback: AlertFeedback,
    db: Session = Depends(get_db), user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES)),
):
    if not claim_alert(db, alert_id, user.organization_id, "false_positive"):
        owned_alert(db, alert_id, user)
        raise HTTPException(409, "This security alert has already been resolved")
    alert = owned_alert(db, alert_id, user)
    audit(db, user.organization_id, user.id, "detection.alert.false_positive", f"security_alert:{alert.id}",
          {"note": feedback.note})
    db.commit()
    return alert_record(alert)


def correlation_node_id(organization_id: str, kind: str, reference: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([organization_id, kind, reference])))


def graph_node(db: Session, organization_id: str, kind: str, reference: str, title: str) -> IntelligenceEntity:
    node_id = correlation_node_id(organization_id, kind, reference)
    node = db.get(IntelligenceEntity, node_id)
    if node is None:
        node = IntelligenceEntity(id=node_id, organization_id=organization_id, entity_type=kind,
                                  external_id=reference, display_name=title,
                                  properties=json.dumps({"provenance": "analyst_confirmed_detection"}))
        db.add(node)
        db.flush()
    return node


@app.post("/api/v1/security-alerts/{alert_id}/incident")
def confirm_alert(
    alert_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*INCIDENT_WRITER_ROLES)),
):
    org_id = user.organization_id
    # Serialize confirmations in this organization so common account/device graph nodes are reused.
    db.scalar(select(Organization.id).where(Organization.id == org_id).with_for_update())
    claimed = claim_alert(db, alert_id, org_id, "confirmed")
    alert = owned_alert(db, alert_id, user)
    if not claimed:
        if alert.incident_id:
            return alert_record(alert, db.get(Incident, alert.incident_id))
        raise HTTPException(409, "This security alert has already been resolved")
    linked = source_events(db, alert)
    if not linked:
        raise HTTPException(409, "The alert has no source events")
    incident = Incident(organization_id=org_id, title=alert.title, severity=alert.severity,
                        description=f"{alert.explanation} This correlation requires investigation and does not establish causation.")
    db.add(incident)
    db.flush()
    alert.incident_id = incident.id
    db.add(IncidentEvent(organization_id=org_id, incident_id=incident.id, actor_id=user.id,
                         event_type="created", from_status="", to_status=incident.status,
                         note=f"Analyst confirmed detection alert {alert.id} with {len(linked)} source events."))
    incident_node = graph_node(db, org_id, "incident", incident.id, incident.title)
    for event, metadata in linked:
        event_node = graph_node(db, org_id, "security_event", event.id, event.title)
        links = [(incident_node.id, event_node.id, "supported_by")]
        for kind, label in (("account", metadata.account), ("device", metadata.device)):
            if label:
                entity = graph_node(db, org_id, kind, label, label)
                links.append((event_node.id, entity.id, "reported_" + kind))
        for source_id, target_id, relationship_type in links:
            relationship_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([source_id, target_id, relationship_type])))
            if db.get(IntelligenceRelationship, relationship_id) is None:
                db.add(IntelligenceRelationship(id=relationship_id, organization_id=org_id,
                                                source_id=source_id, target_id=target_id,
                                                relationship_type=relationship_type, confidence=1.0,
                                                source_reference=f"security_event:{event.id}",
                                                occurred_at=event.occurred_at))
    audit(db, org_id, user.id, "detection.alert.confirmed", f"incident:{incident.id}",
          {"alert_id": alert.id, "events": len(linked)})
    db.commit()
    return alert_record(alert, incident)


@app.get("/api/v1/incidents/{incident_id}/security-events")
def incident_security_events(
    incident_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    incident = db.scalar(select(Incident).where(
        Incident.id == incident_id, Incident.organization_id == user.organization_id,
    ))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    alert = db.scalar(select(DetectionAlert).where(
        DetectionAlert.incident_id == incident.id, DetectionAlert.organization_id == user.organization_id,
    ))
    if alert:
        return [security_event_record(event) for event, _ in source_events(db, alert)]
    finding = db.scalar(select(CommerceFinding).where(
        CommerceFinding.incident_id == incident.id, CommerceFinding.organization_id == user.organization_id,
    ))
    return commerce_sources(db, finding)["security_events"] if finding else []


def owned_source(db: Session, source_id: str, user: User) -> DataSource:
    source = db.scalar(select(DataSource).where(
        DataSource.id == source_id, DataSource.organization_id == user.organization_id,
    ))
    if source is None:
        raise HTTPException(404, "Data source not found")
    return source


def require_source_write(user: User, kind: str):
    if user.role in ORG_ADMIN_ROLES:
        return
    if user.role == "business_analyst" and kind == "commerce":
        return
    if user.role == "security_analyst" and kind in {"security", "assets"}:
        return
    raise HTTPException(403, "This role cannot write to this type of source")


def source_record(source: DataSource, last_accepted=None) -> dict:
    return {"id": source.id, "name": source.name, "kind": source.kind, "active": source.active,
            "mode": "submitted_batches", "last_accepted_at": utc(last_accepted) if last_accepted else None}


@app.get("/api/v1/data-sources")
def list_data_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(select(DataSource, func.max(IngestionBatch.created_at)).outerjoin(
        IngestionBatch, (IngestionBatch.source_id == DataSource.id) & (IngestionBatch.accepted > 0),
    ).where(DataSource.organization_id == user.organization_id)
        .group_by(DataSource.id).order_by(DataSource.name).limit(200)).all()
    return [source_record(source, latest) for source, latest in rows]


@app.post("/api/v1/data-sources", status_code=201)
def create_data_source(
    settings: SourceSettings, db: Session = Depends(get_db), user: User = Depends(require_roles(*INGESTION_ROLES)),
):
    require_source_write(user, settings.kind)
    source = DataSource(organization_id=user.organization_id, **settings.model_dump())
    db.add(source)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A data source already uses that name") from exc
    audit(db, user.organization_id, user.id, "ingestion.source.created", f"data_source:{source.id}", {"kind": source.kind})
    db.commit()
    return source_record(source)


@app.get("/api/v1/data-sources/{source_id}/batches")
def list_source_batches(
    source_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    source = owned_source(db, source_id, user)
    batches = db.scalars(select(IngestionBatch).where(IngestionBatch.source_id == source.id)
                         .order_by(IngestionBatch.created_at.desc(), IngestionBatch.id).limit(100)).all()
    return [batch_record(batch) for batch in batches]


@app.get("/api/v1/data-sources/{source_id}/batches/{batch_id}")
def read_source_batch(
    source_id: str, batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    source = owned_source(db, source_id, user)
    batch = db.scalar(select(IngestionBatch).where(IngestionBatch.id == batch_id, IngestionBatch.source_id == source.id))
    if batch is None:
        raise HTTPException(404, "Ingestion batch not found")
    return batch_record(batch, details=True)


def receive_batch(db, source, request_key, parsed, actor_id):
    rows, payload_digest = parsed
    batch, new = store_batch(db, source, rows, request_key, payload_digest,
                             actor_id=actor_id, run_inline=DETECTION_MODE != "worker")
    output = batch_record(batch, details=True)
    db.commit()
    if new and DETECTION_MODE == "worker" and source.kind == "security" and output["accepted"]:
        notify_worker()
    return output


BatchKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")]


@app.post("/api/v1/data-sources/{source_id}/batches")
def upload_source_batch(
    source_id: str, request_key: BatchKey,
    db: Session = Depends(get_db), user: User = Depends(require_roles(*INGESTION_ROLES)),
    parsed: tuple = Depends(parse_batch),
):
    source = owned_source(db, source_id, user)
    require_source_write(user, source.kind)
    return receive_batch(db, source, request_key, parsed, user.id)


def public_key_record(key: IngestionKey):
    return {"id": key.id, "label": key.label, "expires_at": utc(key.expires_at),
            "revoked_at": utc(key.revoked_at) if key.revoked_at else None}


@app.get("/api/v1/data-sources/{source_id}/keys")
def list_source_keys(
    source_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
):
    source = owned_source(db, source_id, user)
    keys = db.scalars(select(IngestionKey).where(IngestionKey.source_id == source.id)
                      .order_by(IngestionKey.expires_at.desc()).limit(100)).all()
    return [public_key_record(key) for key in keys]


@app.post("/api/v1/data-sources/{source_id}/keys", status_code=201)
def create_source_key(
    source_id: str, settings: KeySettings, response: Response,
    db: Session = Depends(get_db), user: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
):
    source = owned_source(db, source_id, user)
    token_id = uuid_value()
    token = f"{token_id}.{secrets.token_urlsafe(32)}"
    key = IngestionKey(id=token_id, source_id=source.id, secret_digest=digest(token.encode()),
                       label=settings.label, expires_at=utc_now_naive() + timedelta(days=settings.expires_in_days))
    db.add(key)
    audit(db, user.organization_id, user.id, "ingestion.key.created", f"data_source:{source.id}", {"key_id": key.id})
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return public_key_record(key) | {"key": token}


@app.post("/api/v1/data-sources/{source_id}/keys/{key_id}/revoke")
def revoke_source_key(
    source_id: str, key_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
):
    source = owned_source(db, source_id, user)
    key = db.scalar(select(IngestionKey).where(IngestionKey.source_id == source.id, IngestionKey.id == key_id)
                    .with_for_update())
    if key is None:
        raise HTTPException(404, "Ingestion key not found")
    if not key.revoked_at:
        key.revoked_at = utc_now_naive()
        audit(db, user.organization_id, user.id, "ingestion.key.revoked", f"data_source:{source.id}", {"key_id": key.id})
        db.commit()
    return public_key_record(key)


def scoped_webhook_source(
    source_id: str, token: Annotated[str | None, Header(alias="X-Ingestion-Key", max_length=150)] = None,
    db: Session = Depends(get_db),
) -> DataSource:
    token_id, separator, secret = (token or "").partition(".")
    key = db.get(IngestionKey, token_id) if separator and secret and len(token_id) == 36 else None
    if (key is None or key.source_id != source_id or key.revoked_at is not None
            or key.expires_at <= utc_now_naive() or not hmac.compare_digest(key.secret_digest, digest(token.encode()))):
        raise HTTPException(401, "Invalid ingestion key")
    source = db.get(DataSource, key.source_id)
    if source is None or not source.active:
        raise HTTPException(401, "Invalid ingestion key")
    return source


@app.post("/api/v1/ingestion/webhooks/{source_id}")
def receive_webhook(
    request_key: BatchKey, source: DataSource = Depends(scoped_webhook_source),
    db: Session = Depends(get_db), parsed: tuple = Depends(parse_batch),
):
    return receive_batch(db, source, request_key, parsed, None)


@app.get("/api/v1/commerce/records")
def list_commerce_records(
    kind: Literal["payment", "refund"] | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    stmt = select(CommerceRecord).where(CommerceRecord.organization_id == user.organization_id)
    if kind:
        stmt = stmt.where(CommerceRecord.kind == kind)
    return [commerce_record(row) for row in db.scalars(
        stmt.order_by(CommerceRecord.occurred_at.desc(), CommerceRecord.id).limit(100)
    )]


@app.get("/api/v1/commerce/transactions")
def list_commerce_transactions(
    kind: Literal["payment", "refund"] | None = None,
    account: str | None = Query(default=None, max_length=200),
    currency: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    search: str | None = Query(default=None, max_length=200),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    stmt = select(CommerceRecord).where(CommerceRecord.organization_id == user.organization_id)
    if kind:
        stmt = stmt.where(CommerceRecord.kind == kind)
    if account:
        stmt = stmt.where(CommerceRecord.account == account)
    if currency:
        stmt = stmt.where(CommerceRecord.currency == currency)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(or_(CommerceRecord.external_id.ilike(term),
                              CommerceRecord.account.ilike(term),
                              CommerceRecord.order_reference.ilike(term)))
    if start:
        stmt = stmt.where(CommerceRecord.occurred_at >= start.replace(tzinfo=None))
    if end:
        stmt = stmt.where(CommerceRecord.occurred_at <= end.replace(tzinfo=None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(CommerceRecord.occurred_at.desc(), CommerceRecord.id).limit(limit).offset(offset)).all()
    return {"items": [commerce_record(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.get("/api/v1/commerce/totals")
def commerce_totals(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(select(
        CommerceRecord.currency, CommerceRecord.kind, func.count(), func.sum(CommerceRecord.amount_minor),
    ).where(CommerceRecord.organization_id == user.organization_id)
        .group_by(CommerceRecord.currency, CommerceRecord.kind).order_by(CommerceRecord.currency, CommerceRecord.kind))
    return [{"currency": currency, "kind": kind, "count": count, "amount_minor": str(amount)}
            for currency, kind, count, amount in rows]


@app.get("/api/v1/commerce/records/{record_id}")
def inspect_commerce_record(record_id: str, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    row = db.scalar(select(CommerceRecord).where(
        CommerceRecord.id == record_id, CommerceRecord.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Commerce record is unavailable")
    finding = db.scalar(select(CommerceFinding).where(
        CommerceFinding.organization_id == user.organization_id,
        CommerceFinding.refund_id == row.id,
    ))
    evidence = db.get(Evidence, row.evidence_id) if row.evidence_id else None
    if evidence and evidence.organization_id != user.organization_id:
        evidence = None
    security_events = []
    if finding:
        report = finding_record(finding)
        event_ids = report.get("security_event_ids", [])
        if event_ids:
            events = db.scalars(select(SecurityEvent).where(
                SecurityEvent.organization_id == user.organization_id,
                SecurityEvent.id.in_(event_ids),
            ).order_by(SecurityEvent.occurred_at.desc())).all()
            security_events = [security_event_record(event) for event in events]
    return commerce_record(row) | {
        "finding": finding_record(finding) if finding else None,
        "evidence": {"id": evidence.id, "name": evidence.name, "sha256": evidence.sha256} if evidence else None,
        "security_events": security_events,
    }


@app.get("/api/v1/commerce/export")
def export_commerce_records(kind: Literal["payment", "refund"] | None = None,
                            currency: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
                            format: str = Query(default="json", pattern=r"^(json|csv)$"),
                            db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*COMMERCE_REVIEW_ROLES))):
    stmt = select(CommerceRecord).where(CommerceRecord.organization_id == user.organization_id)
    if kind:
        stmt = stmt.where(CommerceRecord.kind == kind)
    if currency:
        stmt = stmt.where(CommerceRecord.currency == currency)
    rows = db.scalars(stmt.order_by(CommerceRecord.occurred_at.desc(), CommerceRecord.id).limit(500)).all()
    records = [commerce_record(row) for row in rows]
    audit(db, user.organization_id, user.id, "commerce.records.exported", "commerce_records",
          {"format": format, "kind": kind, "currency": currency, "count": len(records)})
    db.commit()
    if format == "csv":
        output = StringIO()
        writer = csv.DictWriter(output, ("id", "external_id", "kind", "account", "device", "order_reference",
                                          "currency", "amount_minor", "evidence_id", "source_id", "occurred_at"))
        writer.writeheader()
        writer.writerows(records)
        body, mime = output.getvalue(), "text/csv"
    else:
        body, mime = json.dumps({"items": records, "count": len(records)}, ensure_ascii=False), "application/json"
    return Response(body, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=commerce-{utc_now_naive().strftime('%Y%m%d')}.{format}",
        "Cache-Control": "private, no-store",
    })


@app.get("/api/v1/commerce/policy")
def read_commerce_policy(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_policy(db, user.organization_id)


@app.put("/api/v1/commerce/policy")
def update_commerce_policy(
    settings: CorrelationPolicy, db: Session = Depends(get_db), user: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
):
    db.scalar(select(Organization.id).where(Organization.id == user.organization_id).with_for_update())
    row = db.get(CorrelationSettings, user.organization_id)
    if row is None:
        row = CorrelationSettings(organization_id=user.organization_id)
        db.add(row)
    for key, value in settings.model_dump().items():
        setattr(row, key, value)
    audit(db, user.organization_id, user.id, "commerce.policy.saved", "commerce_policy", settings.model_dump())
    db.commit()
    return settings


@app.post("/api/v1/commerce/refunds/{refund_id}/evaluate")
def evaluate_commerce_refund(
    refund_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*COMMERCE_REVIEW_ROLES)),
):
    refund = db.scalar(select(CommerceRecord).where(
        CommerceRecord.id == refund_id, CommerceRecord.organization_id == user.organization_id,
        CommerceRecord.kind == "refund",
    ).with_for_update())
    if refund is None:
        raise HTTPException(404, "Refund record not found")
    result = evaluate_refund(db, refund)
    audit(db, user.organization_id, user.id, "commerce.refund.evaluated", f"refund:{refund_id}",
          {"finding_id": result.id if result else None})
    db.commit()
    return finding_record(result) if result else None


@app.get("/api/v1/commerce/findings")
def list_commerce_findings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(select(CommerceFinding, CommerceRecord).join(
        CommerceRecord, (CommerceRecord.id == CommerceFinding.refund_id)
        & (CommerceRecord.organization_id == CommerceFinding.organization_id),
    ).where(CommerceFinding.organization_id == user.organization_id)
        .order_by(CommerceFinding.created_at.desc(), CommerceFinding.id).limit(100))
    return [finding_record(finding) | {"refund": commerce_record(refund), "graph_entity_id": (
        correlation_node_id(user.organization_id, "incident", finding.incident_id) if finding.incident_id else None
    )} for finding, refund in rows]


def owned_finding(db: Session, finding_id: str, user: User) -> CommerceFinding:
    finding = db.scalar(select(CommerceFinding).where(
        CommerceFinding.id == finding_id, CommerceFinding.organization_id == user.organization_id,
    ))
    if finding is None:
        raise HTTPException(404, "Finding not found")
    return finding


def commerce_sources(db: Session, finding: CommerceFinding) -> dict:
    report = finding_record(finding)
    org = finding.organization_id
    events = db.scalars(select(SecurityEvent).where(SecurityEvent.organization_id == org,
        SecurityEvent.id.in_(report["security_event_ids"])).order_by(SecurityEvent.occurred_at)).all()
    refunds = db.scalars(select(CommerceRecord).where(CommerceRecord.organization_id == org,
        CommerceRecord.id.in_(report["refund_ids"])).order_by(CommerceRecord.occurred_at)).all()
    evidence = db.scalars(select(Evidence).where(Evidence.organization_id == org,
        Evidence.id.in_(report["evidence_ids"])).order_by(Evidence.created_at)).all()
    return {"security_events": [security_event_record(event) for event in events],
            "refunds": [commerce_record(refund) for refund in refunds],
            "evidence": [{"id": item.id, "name": item.name, "sha256": item.sha256} for item in evidence]}


@app.get("/api/v1/commerce/findings/{finding_id}/sources")
def read_finding_sources(finding_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return commerce_sources(db, owned_finding(db, finding_id, user))


def claim_finding(db: Session, finding_id: str, org_id: str, status: str) -> bool:
    stmt = update(CommerceFinding).where(
        CommerceFinding.id == finding_id, CommerceFinding.organization_id == org_id, CommerceFinding.status == "open",
    )
    if status == "confirmed":
        stmt = stmt.where(CommerceFinding.score > 0)
    return db.execute(stmt.values(status=status)).rowcount == 1


@app.post("/api/v1/commerce/findings/{finding_id}/dismiss")
def dismiss_commerce_finding(
    finding_id: str, feedback: AlertFeedback,
    db: Session = Depends(get_db), user: User = Depends(require_roles(*COMMERCE_REVIEW_ROLES)),
):
    changed = claim_finding(db, finding_id, user.organization_id, "dismissed")
    finding = owned_finding(db, finding_id, user)
    if not changed:
        raise HTTPException(409, "Finding is already resolved")
    audit(db, user.organization_id, user.id, "commerce.finding.dismissed", f"commerce_finding:{finding_id}",
          {"note": feedback.note})
    db.commit()
    return finding_record(finding)


def link_commerce_graph(db: Session, incident: Incident, sources: dict) -> None:
    org = incident.organization_id
    root = graph_node(db, org, "incident", incident.id, incident.title)

    def edge(source, target, relation, reference, at):
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([source.id, target.id, relation])))
        if not db.get(IntelligenceRelationship, identifier):
            db.add(IntelligenceRelationship(
                id=identifier, organization_id=org, source_id=source.id, target_id=target.id,
                relationship_type=relation, confidence=1, source_reference=reference, occurred_at=at,
            ))
            db.flush()

    for refund in sources["refunds"]:
        node = graph_node(db, org, "refund", refund["id"], f"Refund {refund['external_id']}")
        reference = f"refund:{refund['id']}"
        at = datetime.fromisoformat(refund["occurred_at"]).replace(tzinfo=None)
        edge(root, node, "supported_by", reference, at)
        for kind, label in (("account", refund["account"]), ("device", refund["device"])):
            if label:
                edge(node, graph_node(db, org, kind, label, label), f"reported_{kind}", reference, at)
    for event in sources["security_events"]:
        node = graph_node(db, org, "security_event", event["id"], event["title"])
        at = datetime.fromisoformat(event["occurred_at"]).replace(tzinfo=None)
        reference = f"security_event:{event['id']}"
        edge(root, node, "supported_by", reference, at)
        metadata = db.get(DetectionInput, event["id"])
        if metadata and metadata.organization_id == org:
            for kind, label in (("account", metadata.account), ("device", metadata.device)):
                if label:
                    edge(node, graph_node(db, org, kind, label, label), f"reported_{kind}", reference, at)
    for item in sources["evidence"]:
        node = graph_node(db, org, "evidence", item["id"], item["name"])
        edge(root, node, "references_evidence", f"evidence:{item['id']}", incident.created_at)


@app.post("/api/v1/commerce/findings/{finding_id}/incident")
def confirm_commerce_finding(
    finding_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*COMMERCE_REVIEW_ROLES)),
):
    org = user.organization_id
    db.scalar(select(Organization.id).where(Organization.id == org).with_for_update())
    changed = claim_finding(db, finding_id, org, "confirmed")
    finding = owned_finding(db, finding_id, user)
    if not changed and not finding.incident_id:
        raise HTTPException(409, "Finding is resolved or does not currently have matching factors")
    if changed:
        sources = commerce_sources(db, finding)
        if not sources["refunds"]:
            raise HTTPException(409, "Finding has no available source refunds")
        report = finding_record(finding)
        incident = Incident(organization_id=org, title="Investigate recorded refund activity",
                            severity="high" if finding.score >= 65 else "medium",
                            description=" ".join(factor["detail"] for factor in report["factors"]) + " " + report["limitations"])
        db.add(incident)
        db.flush()
        finding.incident_id = incident.id
        db.add(IncidentEvent(organization_id=org, incident_id=incident.id, actor_id=user.id,
                             event_type="created", from_status="", to_status=incident.status,
                             note=f"Analyst confirmed commerce finding {finding.id}."))
        link_commerce_graph(db, incident, sources)
        audit(db, org, user.id, "commerce.finding.confirmed", f"incident:{incident.id}", {"finding_id": finding.id})
        db.commit()
    return finding_record(finding) | {"graph_entity_id": correlation_node_id(org, "incident", finding.incident_id)}


@app.post("/api/v1/evidence")
async def upload_evidence(
    organization_id: str,
    name: str = Query(min_length=1, max_length=300),
    investigation_id: str | None = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVIDENCE_WRITER_ROLES)),
):
    authorized_id = _authorized_organization(user, organization_id)
    if investigation_id and not db.query(Incident.id).filter(
        Incident.id == investigation_id,
        Incident.organization_id == authorized_id,
    ).first():
        raise HTTPException(404, "Investigation not found")
    content = await file.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "Evidence files must be 25 MB or smaller")
    inspection = await run_in_threadpool(inspect_image, content)
    evidence = Evidence(
        organization_id=authorized_id,
        investigation_id=investigation_id,
        name=name,
        sha256=hashlib.sha256(content).hexdigest(),
        sha512=hashlib.sha512(content).hexdigest(),
        mime_type=file.content_type if file.content_type and len(file.content_type) <= 200 else "application/octet-stream",
    )
    db.add(evidence)
    db.flush()
    original_filename = (file.filename or "unknown").replace("\\", "/").split("/")[-1]
    original_filename = "".join(character for character in original_filename if character.isprintable())[:300] or "unknown"
    db.add(EvidenceFileMetadata(evidence_id=evidence.id, original_filename=original_filename,
                                size_bytes=len(content), signature=evidence_signature(content)))
    root = Path(os.getenv("VYRNEXIS_EVIDENCE_DIR", ".dev-logs/evidence")).resolve()
    organization_key = hashlib.sha256(authorized_id.encode("utf-8")).hexdigest()
    directory = root / organization_key
    destination = directory / f"{evidence.id}.blob"
    temporary = directory / f".{evidence.id}.{secrets.token_hex(8)}.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if directory.resolve() != directory or not destination.is_relative_to(root):
            raise HTTPException(409, "Evidence storage path is unavailable")
        with temporary.open("xb") as output_file:
            output_file.write(content)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary, destination)
        image_metadata = save_image_metadata(db, evidence.id, inspection)
        audit(db, authorized_id, user.id, "evidence.upload", f"evidence:{evidence.id}", {
            "name": name, "sha256": evidence.sha256, "image_metadata_status": image_metadata["status"],
        })
        db.commit()
    except Exception:
        db.rollback()
        if directory.resolve() == directory:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
        raise
    db.refresh(evidence)
    return {"id": evidence.id, "name": evidence.name, "sha256": evidence.sha256, "sha512": evidence.sha512,
            "immutable": evidence.immutable, "stored": True, "image_metadata": image_metadata}


@app.get("/api/v1/evidence")
def list_evidence(
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    records = db.query(Evidence).filter(
        Evidence.organization_id == user.organization_id
    ).order_by(Evidence.created_at.desc()).limit(limit).all()
    enrollments = dict(db.query(CustodyEnrollment.evidence_id, CustodyEnrollment.case_id).filter(
        CustodyEnrollment.organization_id == user.organization_id,
        CustodyEnrollment.evidence_id.in_([item.id for item in records]),
    ).all()) if records else {}
    metadata = {
        row.evidence_id: image_metadata_record(row)
        for row in db.scalars(select(EvidenceImageMetadata).where(
            EvidenceImageMetadata.evidence_id.in_([item.id for item in records]),
        ))
    } if records and user.role in FORENSIC_READERS else {}
    return [{"id": item.id, "name": item.name, "sha256": item.sha256,
             "sha512": item.sha512, "mime_type": item.mime_type,
             "investigation_id": item.investigation_id,
             "custody_registered": item.id in enrollments,
             "forensic_case_id": enrollments.get(item.id) if user.role in FORENSIC_READERS else None,
             "image_metadata": metadata.get(item.id),
             "immutable": item.immutable, "created_at": item.created_at.isoformat()}
            for item in records]


def owned_evidence(db: Session, evidence_id: str, user: User) -> Evidence:
    evidence = db.query(Evidence).filter(
        Evidence.id == evidence_id,
        Evidence.organization_id == user.organization_id,
    ).first()
    if evidence is None:
        raise HTTPException(404, "Evidence not found")
    return evidence


EVIDENCE_LIMIT = 25 * 1024 * 1024
SIGNATURES = (
    (b"%PDF-", "PDF"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (JPEG_HEADER, "JPEG"),
    *((header, "TIFF") for header in TIFF_HEADERS),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"PK\x03\x04", "ZIP container"),
)


def evidence_signature(content: bytes) -> str | None:
    return next((kind for signature, kind in SIGNATURES if content.startswith(signature)), None)


def read_evidence_bytes(evidence: Evidence) -> bytes:
    if not evidence.id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in evidence.id):
        raise HTTPException(404, "Evidence bytes are unavailable")
    root = Path(os.getenv("VYRNEXIS_EVIDENCE_DIR", ".dev-logs/evidence")).resolve()
    organization_key = hashlib.sha256(evidence.organization_id.encode()).hexdigest()
    path = root / organization_key / f"{evidence.id}.blob"
    try:
        if path.resolve(strict=True) != path or not path.is_file():
            raise HTTPException(404, "Evidence bytes are unavailable")
        with path.open("rb") as stream:
            content = stream.read(EVIDENCE_LIMIT + 1)
    except OSError as exc:
        raise HTTPException(404, "Evidence bytes are unavailable") from exc
    if len(content) > EVIDENCE_LIMIT:
        raise HTTPException(409, "Evidence exceeds the stored-file size limit")
    return content


def evidence_integrity(evidence: Evidence, content: bytes) -> bool:
    return (hmac.compare_digest(hashlib.sha256(content).hexdigest(), evidence.sha256)
            and hmac.compare_digest(hashlib.sha512(content).hexdigest(), evidence.sha512))


@app.post("/api/v1/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVIDENCE_WRITER_ROLES, "security_analyst")),
):
    evidence = owned_evidence(db, evidence_id, user)
    if db.get(CustodyEnrollment, evidence.id):
        raise HTTPException(409, "Verify enrolled evidence inside its forensic case")
    try:
        content = read_evidence_bytes(evidence)
    except HTTPException as exc:
        audit(db, user.organization_id, user.id, "evidence.verify", f"evidence:{evidence.id}",
              {"result": "unavailable"})
        db.commit()
        raise exc
    valid = evidence_integrity(evidence, content)
    signature = evidence_signature(content)
    metadata = inspect_verified_image(db, evidence.id, content) if valid else None
    audit(db, user.organization_id, user.id, "evidence.verify", f"evidence:{evidence.id}",
          {"result": "match" if valid else "mismatch", "size_bytes": len(content), "signature": signature})
    db.commit()
    return {"id": evidence.id, "integrity": "match" if valid else "mismatch", "signature": signature,
            "size_bytes": len(content), "sha256": evidence.sha256, "sha512": evidence.sha512,
            "image_metadata": metadata}


@app.get("/api/v1/evidence/{evidence_id}/activity")
def evidence_activity(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    evidence = owned_evidence(db, evidence_id, user)
    rows = db.scalars(select(AuditLog).where(
        AuditLog.organization_id == user.organization_id, AuditLog.resource == f"evidence:{evidence.id}",
        AuditLog.action.in_(("evidence.upload", "evidence.verify")),
    ).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(100)).all()
    return [{"action": row.action, "time": utc(row.created_at), "result": json.loads(row.details).get("result")}
            for row in rows]


@app.get("/api/v1/evidence/{evidence_id}/download")
def download_evidence(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    evidence = owned_evidence(db, evidence_id, user)
    if db.get(CustodyEnrollment, evidence.id):
        raise HTTPException(409, "Export enrolled evidence inside its forensic case")
    content = read_evidence_bytes(evidence)
    if not evidence_integrity(evidence, content):
        raise HTTPException(409, "Evidence integrity check failed")
    filename = quote(evidence.name, safe="")
    return Response(content, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })


app.include_router(build_forensic_router(require_roles, audit, read_evidence_bytes, evidence_integrity))
app.include_router(build_nexus_router(require_roles, read_evidence_bytes, evidence_integrity))
app.include_router(build_hybrid_router(require_roles))
app.include_router(build_gateway_router(require_roles, get_current_user, audit))
app.include_router(build_knowledge_router(get_current_user, require_roles, audit))
app.include_router(build_copilot_router(get_current_user, audit))
app.include_router(build_counterfactual_router(require_roles, audit, COMMERCE_REVIEW_ROLES))
app.include_router(build_workflow_router(require_roles, audit))
app.include_router(build_twin_router(get_current_user, require_roles, audit))
app.include_router(build_business_router(require_roles, audit))
app.include_router(build_semantic_router(get_current_user, require_roles, audit))


@app.post("/api/v1/workflows")
def create_workflow(
    payload: WorkflowRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WORKFLOW_WRITER_ROLES)),
):
    organization_id = _authorized_organization(user, payload.organization_id)
    workflow = Workflow(
        organization_id=organization_id,
        name=payload.name,
        definition=json.dumps(payload.definition),
        enabled=payload.enabled,
    )
    db.add(workflow)
    db.flush()
    audit(db, organization_id, user.id, "workflow.create", f"workflow:{workflow.id}", {"enabled": workflow.enabled})
    db.commit()
    db.refresh(workflow)
    return {"id": workflow.id, "name": workflow.name, "enabled": workflow.enabled}


@app.get("/api/v1/workflows")
def list_workflows(
    organization_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    workflows = db.query(Workflow).filter(Workflow.organization_id == authorized_id).all()
    return [{"id": item.id, "name": item.name, "enabled": item.enabled} for item in workflows]


@app.get("/api/v1/agents")
def list_agents(
    user: User = Depends(get_current_user),
):
    return [
        {
            "name": name,
            "responsibility": responsibility,
            "status": "deterministic_local",
            "human_approval_required": name in {"SENTINEL", "TRACE", "AEGIS", "MERCURY"},
            "provider_configured": False,
        }
        for name, responsibility in AGENT_DEFINITIONS.items()
    ]


@app.post("/api/v1/agents/executions")
def execute_agent(
    payload: AgentTaskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ORG_ADMIN_ROLES, "security_analyst", "forensic_investigator", "business_analyst", "automation_engineer")),
):
    """Run a bounded, deterministic analysis over this tenant's persisted records."""
    agent = payload.agent.upper()
    if agent not in AGENT_DEFINITIONS:
        raise HTTPException(422, "Unknown agent")
    if payload.task_type != "analyze_organization":
        raise HTTPException(422, "Supported task_type: analyze_organization")

    record_limit = 500
    incident_query = db.query(Incident).filter(Incident.organization_id == user.organization_id)
    if payload.incident_id:
        selected = incident_query.filter(Incident.id == payload.incident_id).first()
        if selected is None:
            raise HTTPException(404, "Incident not found")
        incidents = [selected]
        associated_finding = db.scalar(select(CommerceFinding).where(
            CommerceFinding.organization_id == user.organization_id, CommerceFinding.incident_id == selected.id,
        ))
        evidence_ids = finding_record(associated_finding)["evidence_ids"] if associated_finding else []
        evidence_query = db.query(Evidence).filter(
            Evidence.organization_id == user.organization_id,
            or_(Evidence.investigation_id == selected.id, Evidence.id.in_(evidence_ids)),
        )
    else:
        incidents = incident_query.order_by(Incident.created_at.desc()).limit(record_limit).all()
        evidence_query = db.query(Evidence).filter(Evidence.organization_id == user.organization_id)
    entities = db.query(IntelligenceEntity).filter(
        IntelligenceEntity.organization_id == user.organization_id
    ).order_by(IntelligenceEntity.created_at.desc()).limit(record_limit).all()
    relationships = db.query(IntelligenceRelationship).filter(
        IntelligenceRelationship.organization_id == user.organization_id
    ).order_by(IntelligenceRelationship.occurred_at.desc()).limit(record_limit).all()
    evidence = evidence_query.order_by(Evidence.created_at.desc()).limit(record_limit).all()

    names = {item.id: item.display_name for item in entities}
    findings: list[str] = []
    evidence_refs: list[str] = []
    alternatives = ["Records may be incomplete or reflect benign operational activity."]
    approval = agent in {"SENTINEL", "TRACE", "AEGIS", "MERCURY", "NEXUS"}
    if agent == "ORACLE":
        findings.append(f"Observed {len(incidents)} persisted incidents; no time-series forecast is available from this dataset.")
        if incidents:
            evidence_refs.extend(f"incident:{item.id}" for item in incidents)
    elif agent == "SENTINEL":
        findings.append(f"Reviewed {len(incidents)} incidents and {len(entities)} graph entities for defensive triage.")
        findings.extend(f"{item.severity.upper()} incident: {item.title} ({item.status})." for item in incidents[:20])
        evidence_refs.extend(f"incident:{item.id}" for item in incidents)
    elif agent == "TRACE":
        findings.append(f"Reconstructed {len(relationships)} recorded relationship(s); ordering is limited to persisted timestamps.")
        for rel in relationships[:50]:
            findings.append(f"{names.get(rel.source_id, 'Unknown entity')} —{rel.relationship_type}→ {names.get(rel.target_id, 'Unknown entity')}.")
            if rel.source_reference:
                evidence_refs.append(rel.source_reference)
    elif agent == "AEGIS":
        high = sum(item.severity.lower() in {"high", "critical"} for item in incidents)
        findings.append(f"Policy review counted {high} high or critical incident(s) among {len(incidents)} reviewed.")
        findings.append("No compliance framework or policy set is configured; this is not a compliance determination.")
        evidence_refs.extend(f"incident:{item.id}" for item in incidents)
    elif agent == "MERCURY":
        stmt = select(CommerceFinding).where(CommerceFinding.organization_id == user.organization_id)
        if payload.incident_id:
            stmt = stmt.where(CommerceFinding.incident_id == payload.incident_id)
        reports = db.scalars(stmt.order_by(CommerceFinding.created_at.desc()).limit(20)).all()
        if reports:
            findings.append(f"Reviewed {len(reports)} persisted refund findings. Scores are rule weights, not probabilities.")
            for item in reports:
                report = finding_record(item)
                factors = ", ".join(factor["code"].replace("_", " ") for factor in report["factors"])
                findings.append(f"{item.status.capitalize()} finding scored {item.score}/100 ({factors or 'no matched factors'}).")
                evidence_refs.extend([f"commerce_finding:{item.id}", f"refund:{item.refund_id}"])
                evidence_refs.extend(f"evidence:{item_id}" for item_id in report["evidence_ids"])
        else:
            findings.append("No persisted refund findings are available in this scope.")
    elif agent == "NEXUS":
        findings.append(f"Coordination summary: {len(incidents)} incidents, {len(entities)} entities, {len(relationships)} relationships, {len(evidence)} evidence records.")
        findings.append("No other agents were invoked automatically; human review is required before actions.")
    elif agent == "VERITAS":
        checks = {"verified": 0, "mismatched": 0, "unavailable": 0}
        for item in evidence[:4]:
            evidence_refs.append(f"evidence:{item.id}")
            if db.get(CustodyEnrollment, item.id):
                checks["unavailable"] += 1
                continue
            try:
                content = read_evidence_bytes(item)
            except HTTPException:
                checks["unavailable"] += 1
            else:
                checks["verified" if evidence_integrity(item, content) else "mismatched"] += 1
        findings.append(f"Rehashed up to four scoped files: {checks['verified']} verified, "
                        f"{checks['mismatched']} mismatched, {checks['unavailable']} unavailable.")
        findings.append("Hash verification does not validate the accuracy or origin of a claim.")

    output = {
        "agent": agent,
        "finding": " ".join(findings),
        "evidence": sorted(set(evidence_refs)),
        "confidence": None,
        "confidence_note": "Not calibrated: the local rules do not produce a statistically validated confidence score.",
        "alternatives": alternatives,
        "recommended_action": "Review the cited records and validate conclusions with an authorized human.",
        "requires_approval": approval,
        "limitations": [f"Deterministic analysis of at most {record_limit} recent tenant records per source; no external providers or model inference are configured."],
    }
    execution = AgentExecution(
        organization_id=user.organization_id,
        actor_id=user.id,
        agent_name=agent,
        task_type=payload.task_type,
        input_data=json.dumps({"task_type": payload.task_type, "incident_id": payload.incident_id}),
        output_data=json.dumps(output),
    )
    db.add(execution)
    db.flush()
    audit(db, user.organization_id, user.id, "agent.execute", f"agent_execution:{execution.id}", {"agent": agent, "task_type": payload.task_type})
    db.commit()
    db.refresh(execution)
    return {"id": execution.id, "status": execution.status, "created_at": execution.created_at.isoformat(), **output}


@app.get("/api/v1/agents/executions")
def list_agent_executions(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    records = db.query(AgentExecution).filter(
        AgentExecution.organization_id == user.organization_id
    ).order_by(AgentExecution.created_at.desc()).limit(limit).all()
    return [{"id": item.id, "agent": item.agent_name, "task_type": item.task_type,
             "status": item.status, "created_at": item.created_at.isoformat(),
             "output": json.loads(item.output_data)} for item in records]


@app.post("/api/v1/intelligence/correlate")
def correlate_risks(
    organization_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authorized_id = _authorized_organization(user, organization_id)
    relationships = db.query(IntelligenceRelationship).filter(
        IntelligenceRelationship.organization_id == authorized_id
    ).all()
    entities = {
        item.id: item.display_name
        for item in db.query(IntelligenceEntity).filter(
            IntelligenceEntity.organization_id == authorized_id
        ).all()
    }
    clusters = {}
    for relationship in relationships:
        key = relationship.relationship_type
        cluster = clusters.setdefault(key, {"relationship_type": key, "confidence_values": [], "evidence": []})
        cluster["confidence_values"].append(relationship.confidence)
        cluster["evidence"].append({
            "source": entities.get(relationship.source_id),
            "target": entities.get(relationship.target_id),
            "source_reference": relationship.source_reference,
        })
    findings = []
    for key, cluster in clusters.items():
        values = cluster["confidence_values"]
        findings.append({
            "risk_type": key,
            "confidence": round(sum(values) / len(values), 3),
            "relationship_count": len(values),
            "supporting_evidence": cluster["evidence"],
            "alternative_explanation": "Insufficient independent observations",
            "recommended_action": "Open an evidence-backed review",
            "requires_approval": True,
        })
    return {"organization_id": authorized_id, "findings": findings}
