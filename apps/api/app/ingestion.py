"""Versioned, bounded ingestion for authorized organizational records."""
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import io
import json
import os
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .detection import evaluate_detections
from .models import (
    Asset, AuditLog, CommerceRecord, DataSource, DetectionInput, Evidence, IngestionBatch,
    IngestionReceipt, SecurityEvent, utc_now_naive,
)
from .commerce import evaluate_refund


Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
Severity = Literal["low", "medium", "high", "critical"]
SourceKind = Literal["security", "commerce", "assets"]
MAX_BODY = 512 * 1024
MAX_ROWS = min(200, max(1, int(os.getenv("VYRNEXIS_MAX_BATCH_ROWS", "100"))))
MAX_BATCHES_PER_MINUTE = 12


class SourceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    kind: SourceKind


class KeySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Name
    expires_in_days: int = Field(default=30, ge=1, le=90)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: Label
    occurred_at: datetime

    @field_validator("occurred_at", mode="before")
    @classmethod
    def require_timestamp_string(cls, value):
        if not isinstance(value, str):
            raise ValueError("Timestamp requires an ISO 8601 string")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamp requires a timezone offset")
        return value.astimezone(timezone.utc).replace(tzinfo=None)


def normal_label(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.casefold()
    if len(value) > 200:
        raise ValueError("Normalized label exceeds 200 characters")
    return value


class SecurityObservation(Record):
    record_type: Literal["security"]
    event_type: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=2, max_length=120)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=240)]
    severity: Severity = "medium"
    description: str = Field(default="", max_length=4000)
    source_reference: str = Field(default="", max_length=240)
    account: Label | None = None
    device: Label | None = None
    outcome: Literal["success", "failure"] | None = None

    @field_validator("account", "device")
    @classmethod
    def normalize_identity(cls, value):
        return normal_label(value)

    def validate_outcome(self):
        if self.outcome and (not self.account or self.event_type not in {"authentication", "login", "sign_in"}):
            raise ValueError("Authentication outcome requires an account and a sign-in event type")


class CommerceObservation(Record):
    record_type: Literal["payment", "refund"]
    account: Label
    device: Label | None = None
    order_reference: Label | None = None
    currency: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$")]
    amount_minor: int = Field(gt=0, le=2_000_000_000)
    evidence_id: Label | None = None

    @field_validator("amount_minor", mode="before")
    @classmethod
    def require_integer_amount(cls, value):
        if type(value) is not int and not (isinstance(value, str) and value.isascii() and value.isdecimal()):
            raise ValueError("Use integer minor units")
        return value

    @field_validator("account", "device")
    @classmethod
    def normalize_identity(cls, value):
        return normal_label(value)


class AssetObservation(Record):
    record_type: Literal["asset"]
    name: Label
    asset_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    identifier: str = Field(default="", max_length=200)
    criticality: Severity = "medium"
    status: Literal["active", "maintenance", "retired"] = "active"


SCHEMAS = {"security": SecurityObservation, "payment": CommerceObservation, "refund": CommerceObservation,
           "asset": AssetObservation}
SOURCE_RECORDS = {"security": {"security"}, "commerce": {"payment", "refund"}, "assets": {"asset"}}
CSV_HEADERS = {"schema_version"} | {name for model in SCHEMAS.values() for name in model.model_fields}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def parse_batch(request: Request) -> tuple[list, str]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in {"application/json", "text/csv"}:
        raise HTTPException(415, "Use application/json or text/csv")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Compressed request bodies are unsupported")
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "Batch exceeds the 512 KiB limit")
        buffer.extend(chunk)
    body = bytes(buffer)
    try:
        encoding = "utf-8-sig"
        if media_type == "application/json":
            envelope = json.loads(body.decode(encoding))
            if (not isinstance(envelope, dict) or set(envelope) != {"version", "records"}
                    or type(envelope["version"]) is not int or envelope["version"] != 1
                    or not isinstance(envelope["records"], list)):
                raise HTTPException(422, "Expected version 1 and a records array")
            rows = envelope["records"]
        else:
            reader = csv.DictReader(io.StringIO(body.decode(encoding), newline=""), strict=True)
            headers = reader.fieldnames or []
            if (len(set(headers)) != len(headers) or not set(headers) <= CSV_HEADERS
                    or not {"schema_version", "record_type", "external_id", "occurred_at"} <= set(headers)):
                raise HTTPException(422, "Invalid CSV headers for ingestion schema version 1")
            rows = []
            for row in reader:
                if len(rows) >= MAX_ROWS:
                    raise HTTPException(413, f"Batch exceeds {MAX_ROWS} rows")
                if None in row or None in row.values():
                    rows.append(None)
                    continue
                version = row.pop("schema_version")
                rows.append({k: v for k, v in row.items() if v != ""} if version == "1" else None)
    except (UnicodeError, csv.Error, ValueError, RecursionError) as exc:
        raise HTTPException(422, "Malformed UTF-8 JSON or CSV batch") from exc
    if not rows:
        raise HTTPException(422, "Batch must include at least one record")
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"Batch exceeds {MAX_ROWS} rows")
    return rows, digest(media_type.encode() + b":" + body)


def batch_record(batch: IngestionBatch, *, details=False) -> dict:
    record = {"id": batch.id, "source_id": batch.source_id, "status": batch.status,
              "schema_version": batch.schema_version, "accepted": batch.accepted,
              "duplicate": batch.duplicate, "rejected": batch.rejected,
              "created_at": batch.created_at.replace(tzinfo=timezone.utc).isoformat()}
    if details:
        record["results"] = json.loads(batch.results)
    return record


def store_batch(
    db: Session, source: DataSource, rows: list, request_key: str, payload_digest: str,
    *, actor_id: str | None, run_inline: bool,
) -> tuple[IngestionBatch, bool]:
    # The source write lock serializes the rate limit, idempotency check and receipts.
    locked = db.execute(update(DataSource).where(
        DataSource.id == source.id, DataSource.organization_id == source.organization_id, DataSource.active.is_(True),
    ).values(active=True))
    if not locked.rowcount:
        raise HTTPException(409, "Data source is inactive")
    prior = db.scalar(select(IngestionBatch).where(
        IngestionBatch.source_id == source.id, IngestionBatch.request_key == request_key,
    ))
    if prior:
        if prior.payload_digest != payload_digest:
            raise HTTPException(409, "Batch key already refers to a different payload")
        return prior, False
    recent = db.scalar(select(func.count()).select_from(IngestionBatch).where(
        IngestionBatch.source_id == source.id,
        IngestionBatch.created_at >= utc_now_naive() - timedelta(minutes=1),
    ))
    if recent >= MAX_BATCHES_PER_MINUTE:
        raise HTTPException(429, "Source batch rate exceeded", headers={"Retry-After": "60"})
    batch = IngestionBatch(source_id=source.id, request_key=request_key, payload_digest=payload_digest,
                           schema_version=1, status="completed", accepted=0, duplicate=0, rejected=0)
    results = []
    for number, row in enumerate(rows, 1):
        result = {"row": number}
        try:
            kind = row.get("record_type") if isinstance(row, dict) else None
            if not isinstance(kind, str) or kind not in SOURCE_RECORDS[source.kind]:
                raise ValueError("Invalid row or record type for this source")
            observation = SCHEMAS[kind].model_validate(row)
            if isinstance(observation, SecurityObservation):
                observation.validate_outcome()
            identity = digest(observation.model_dump_json().encode())
            receipt = db.scalar(select(IngestionReceipt).where(
                IngestionReceipt.source_id == source.id, IngestionReceipt.external_id == observation.external_id,
            ))
            if receipt:
                if receipt.payload_digest != identity:
                    raise ValueError("Source event ID already refers to different data")
                batch.duplicate += 1
                result.update(status="duplicate", record_id=receipt.record_id)
            else:
                with db.begin_nested():
                    record_id = store_observation(db, source, observation, identity)
                    db.add(IngestionReceipt(source_id=source.id, external_id=observation.external_id,
                                            payload_digest=identity, record_id=record_id))
                batch.accepted += 1
                result.update(status="accepted", record_id=record_id)
        except ValidationError as exc:
            failures = exc.errors(include_input=False, include_context=False, include_url=False)
            allowed_fields = {field for schema in SCHEMAS.values() for field in schema.model_fields}
            errors = [f"{item['loc'][0]}: {item['msg']}" if item["loc"] and item["loc"][0] in allowed_fields
                      else "Unexpected field or invalid row" for item in failures[:4]]
            batch.rejected += 1
            result.update(status="rejected", errors=errors)
        except ValueError as exc:
            batch.rejected += 1
            result.update(status="rejected", errors=[str(exc)])
        results.append(result)
    # Re-evaluate accepted refunds after the full batch, independent of the row ordering.
    if source.kind == "commerce":
        for result in results:
            if result["status"] == "accepted":
                row = db.get(CommerceRecord, result["record_id"])
                if row.kind == "refund":
                    evaluate_refund(db, row)
    if source.kind == "security" and run_inline:
        ids = [result["record_id"] for result in results if result["status"] == "accepted"]
        for telemetry in db.scalars(select(DetectionInput).where(DetectionInput.event_id.in_(ids))
                                    .order_by(DetectionInput.occurred_at, DetectionInput.event_id)):
            evaluate_detections(db, telemetry)
            db.flush()
    if batch.rejected:
        batch.status = "partial" if batch.accepted or batch.duplicate else "rejected"
    batch.results = json.dumps(results)
    db.add(batch)
    db.flush()
    db.add(AuditLog(organization_id=source.organization_id, actor_id=actor_id, action="ingestion.batch.recorded",
                    resource=f"ingestion_batch:{batch.id}", details=json.dumps({
                        "source_id": source.id, "accepted": batch.accepted, "duplicate": batch.duplicate,
                        "rejected": batch.rejected,
                    })))
    return batch, True


def store_observation(db: Session, source: DataSource, observation: Record, identity: str) -> str:
    org = source.organization_id
    if isinstance(observation, SecurityObservation):
        scoped_source = f"batch:{source.id}"
        event = SecurityEvent(organization_id=org, source=scoped_source, event_type=observation.event_type,
                              title=observation.title, description=observation.description,
                              source_reference=observation.source_reference or observation.external_id,
                              occurred_at=observation.occurred_at, severity=observation.severity)
        db.add(event)
        db.flush()
        telemetry = DetectionInput(event_id=event.id, organization_id=org, source=scoped_source,
                                   external_id=observation.external_id, payload_hash=identity,
                                   account=observation.account, device=observation.device,
                                   outcome=observation.outcome, occurred_at=event.occurred_at)
        db.add(telemetry)
        db.flush()
        return event.id
    if isinstance(observation, CommerceObservation):
        if observation.evidence_id and not db.scalar(select(Evidence.id).where(
            Evidence.id == observation.evidence_id, Evidence.organization_id == org,
        )):
            raise ValueError("Evidence reference was not found for this organization")
        record = CommerceRecord(organization_id=org, source_id=source.id, kind=observation.record_type,
                                **observation.model_dump(exclude={"record_type"}))
    else:
        record = Asset(organization_id=org, **observation.model_dump(exclude={"record_type", "external_id", "occurred_at"}))
    db.add(record)
    db.flush()
    return record.id
