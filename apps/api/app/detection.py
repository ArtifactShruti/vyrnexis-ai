"""Deterministic detection over submitted, tenant-owned authentication records."""
from datetime import timedelta, timezone
import hashlib
import json
import logging
import os

from redis import Redis, RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AuditLog, DetectionAlert, DetectionAlertEvent, DetectionInput, DetectionRule, DetectionRun,
)


logger = logging.getLogger(__name__)
WAKE_CHANNEL = "vyrnexis:detection:wake"
HEARTBEAT_KEY = "vyrnexis:detection:worker"
RULE_TITLES = {
    "failed_signins": "Repeated failed sign-ins",
    "unfamiliar_device": "Successful sign-in from an unfamiliar device",
}


def redis_client() -> Redis | None:
    url = os.getenv("REDIS_URL")
    return Redis.from_url(url, socket_connect_timeout=2, socket_timeout=5) if url else None


def notify_worker() -> None:
    client = redis_client()
    if client is None:
        return
    try:
        client.lpush(WAKE_CHANNEL, "pending")
        client.ltrim(WAKE_CHANNEL, 0, 255)
    except RedisError:
        logger.warning("Detection wake signal unavailable. The worker will retry from the database.")
    finally:
        client.close()


def evaluate_detections(db: Session, event: DetectionInput) -> None:
    rules = db.scalars(select(DetectionRule).where(
        DetectionRule.organization_id == event.organization_id, DetectionRule.enabled.is_(True),
    )).all()
    for rule in rules:
        explanation, supporting_ids = evaluate_rule(db, rule, event)
        alert = save_alert(db, rule, event, explanation, supporting_ids) if supporting_ids else None
        db.add(DetectionRun(
            organization_id=event.organization_id, event_id=event.event_id,
            rule_id=rule.id, alert_id=alert.id if alert else None, explanation=explanation,
        ))
    event.status = "completed"


def evaluate_rule(db: Session, rule: DetectionRule, event: DetectionInput) -> tuple[str, list[str]]:
    if not event.account or not event.outcome:
        return "No normalized authentication identity and outcome were provided.", []
    history = select(DetectionInput).where(
        DetectionInput.organization_id == event.organization_id,
        DetectionInput.account == event.account,
        DetectionInput.occurred_at >= event.occurred_at - timedelta(minutes=rule.window_minutes),
        DetectionInput.occurred_at <= event.occurred_at,
    )
    if rule.kind == "failed_signins":
        if event.outcome != "failure":
            return "The triggering event was not a failed sign-in.", []
        recent = db.scalars(history.where(
            DetectionInput.outcome == "failure", DetectionInput.event_id != event.event_id,
        ).order_by(DetectionInput.occurred_at.desc(), DetectionInput.event_id).limit(rule.threshold - 1)).all()
        if len(recent) + 1 < rule.threshold:
            return f"Fewer than {rule.threshold} failures within {rule.window_minutes} minutes.", []
        return (
            f"At least {rule.threshold} failures for one reported account within {rule.window_minutes} minutes.",
            [event.event_id, *(item.event_id for item in recent)],
        )
    if rule.kind == "unfamiliar_device":
        if event.outcome != "success" or not event.device:
            return "A successful sign-in with a reported device is required.", []
        prior = history.where(
            DetectionInput.outcome == "success", DetectionInput.device.is_not(None),
            DetectionInput.occurred_at < event.occurred_at,
        )
        if db.scalars(prior.where(DetectionInput.device == event.device).limit(1)).first():
            return "The same account previously signed in from this device within the configured window.", []
        baseline = db.scalars(prior.order_by(DetectionInput.occurred_at.desc()).limit(1)).first()
        if baseline is None:
            return "There is no earlier successful sign-in to establish a device baseline.", []
        return f"A different device was observed within the {rule.window_minutes}-minute look-back.", [
            event.event_id, baseline.event_id,
        ]
    return "Unrecognized detection rule.", []


def save_alert(
    db: Session, rule: DetectionRule, event: DetectionInput, explanation: str, supporting_ids: list[str],
) -> DetectionAlert:
    # Fixed grouping buckets cap duplicate alerts. Rule evaluation itself uses a rolling look-back.
    bucket = int(event.occurred_at.replace(tzinfo=timezone.utc).timestamp()) // (rule.window_minutes * 60)
    device = event.device if rule.kind == "unfamiliar_device" else None
    group_key = hashlib.sha256(json.dumps([rule.id, rule.window_minutes, bucket, event.account, device]).encode()).hexdigest()
    alert = db.scalar(select(DetectionAlert).where(
        DetectionAlert.organization_id == event.organization_id, DetectionAlert.group_key == group_key,
    ).with_for_update())
    if alert is None:
        alert = DetectionAlert(
            organization_id=event.organization_id, rule_id=rule.id, group_key=group_key,
            title=RULE_TITLES[rule.kind], severity=rule.severity, explanation=explanation,
        )
        db.add(alert)
        db.flush()
        db.add(AuditLog(
            organization_id=event.organization_id, action="detection.alert.created",
            resource=f"security_alert:{alert.id}", details=json.dumps({"rule": rule.kind}),
        ))
    # Once an alert has been resolved, preserve the exact source set reviewed by the analyst.
    if alert.status == "open":
        for event_id in supporting_ids:
            if db.get(DetectionAlertEvent, (alert.id, event_id)) is None:
                db.add(DetectionAlertEvent(alert_id=alert.id, event_id=event_id))
    return alert
