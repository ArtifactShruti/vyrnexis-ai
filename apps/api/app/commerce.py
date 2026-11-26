"""Explainable correlation over recorded refunds and authentication observations."""
from datetime import timedelta, timezone
import json

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CommerceFinding, CommerceRecord, CorrelationSettings, DetectionInput


class CorrelationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_minutes: int = Field(default=30, ge=5, le=1440)
    refund_threshold: int = Field(default=3, ge=2, le=20)
    failure_threshold: int = Field(default=3, ge=2, le=20)


def utc(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def get_policy(db: Session, organization_id: str) -> CorrelationPolicy:
    stored = db.get(CorrelationSettings, organization_id)
    return CorrelationPolicy.model_validate(stored, from_attributes=True) if stored else CorrelationPolicy()


def evaluate_refund(db: Session, refund: CommerceRecord) -> CommerceFinding | None:
    pending = db.scalar(select(CommerceFinding).where(
        CommerceFinding.organization_id == refund.organization_id, CommerceFinding.refund_id == refund.id,
    ).with_for_update())
    if pending and pending.status != "open":
        return pending
    report = assess_refund(db, refund, get_policy(db, refund.organization_id))
    if not report["factors"] and pending is None:
        return None
    record = pending or CommerceFinding(organization_id=refund.organization_id, refund_id=refund.id)
    record.score = sum(item["weight"] for item in report["factors"])
    record.report = json.dumps(report)
    if pending is None:
        db.add(record)
    db.flush()
    return record


def assess_refund(db: Session, refund: CommerceRecord, policy: CorrelationPolicy, *,
                  include_refund=True, match_device=True, excluded_event=None) -> dict:
    start = refund.occurred_at - timedelta(minutes=policy.window_minutes)
    refunds = db.scalars(select(CommerceRecord).where(
        CommerceRecord.organization_id == refund.organization_id,
        CommerceRecord.account == refund.account, CommerceRecord.currency == refund.currency,
        CommerceRecord.kind == "refund", CommerceRecord.occurred_at.between(start, refund.occurred_at),
        CommerceRecord.id != refund.id,
    ).order_by(CommerceRecord.occurred_at.desc(), CommerceRecord.id)
       .limit(policy.refund_threshold - int(include_refund))).all()
    by_account = select(DetectionInput).where(
        DetectionInput.organization_id == refund.organization_id,
        DetectionInput.account == refund.account,
    )
    if excluded_event:
        by_account = by_account.where(DetectionInput.event_id != excluded_event)
    failures = db.scalars(by_account.where(
        DetectionInput.outcome == "failure", DetectionInput.occurred_at.between(start, refund.occurred_at),
    ).order_by(DetectionInput.occurred_at.desc(), DetectionInput.event_id).limit(policy.failure_threshold)).all()
    success = None
    baseline = None
    if refund.device and match_device:
        success = db.scalars(by_account.where(
            DetectionInput.outcome == "success", DetectionInput.device == refund.device,
            DetectionInput.occurred_at.between(start, refund.occurred_at),
        ).order_by(DetectionInput.occurred_at, DetectionInput.event_id).limit(1)).first()
    if success:
        history = by_account.where(
            DetectionInput.outcome == "success", DetectionInput.device.is_not(None),
            DetectionInput.occurred_at >= success.occurred_at - timedelta(days=30),
            DetectionInput.occurred_at < success.occurred_at,
        )
        seen = db.scalars(history.where(DetectionInput.device == refund.device).limit(1)).first()
        if seen is None:
            baseline = db.scalars(history.order_by(DetectionInput.occurred_at.desc()).limit(1)).first()
    factors = []
    auth_ids = set()
    refund_ids = [refund.id] if include_refund else []
    if len(refunds) + int(include_refund) >= policy.refund_threshold:
        factors.append({"code": "refund_frequency", "weight": 35,
                        "detail": f"At least {policy.refund_threshold} refunds in one currency within the window."})
        refund_ids.extend(record.id for record in refunds)
    if len(failures) >= policy.failure_threshold:
        factors.append({"code": "failed_signins", "weight": 30,
                        "detail": f"At least {policy.failure_threshold} failed sign-ins for the reported account."})
        auth_ids.update(record.event_id for record in failures)
    if success and baseline:
        factors.append({"code": "unfamiliar_refund_device", "weight": 35,
                        "detail": "A successful sign-in used the refund's reported device with a different prior device in the local history."})
        auth_ids.update([success.event_id, baseline.event_id])
    return {
        "factors": factors, "policy": policy.model_dump(), "security_event_ids": sorted(auth_ids),
        "refund_ids": refund_ids, "evidence_ids": sorted(set(
            row.evidence_id for row in [refund, *refunds] if row.id in refund_ids and row.evidence_id
        )),
        "limitations": "An uncalibrated rule score based on reported identifiers and available history. It does not establish causation or compromise.",
        "alternative_explanations": ["Authorized device replacement or shared device",
                                     "Legitimate refund processing or incomplete source data"],
    }


def commerce_record(record: CommerceRecord) -> dict:
    return {key: getattr(record, key) for key in (
        "id", "external_id", "kind", "account", "device", "order_reference", "currency",
        "amount_minor", "evidence_id", "source_id",
    )} | {"occurred_at": utc(record.occurred_at)}


def finding_record(finding: CommerceFinding) -> dict:
    return {"id": finding.id, "refund_id": finding.refund_id, "score": finding.score, "status": finding.status,
            "incident_id": finding.incident_id, "created_at": utc(finding.created_at), **json.loads(finding.report)}
