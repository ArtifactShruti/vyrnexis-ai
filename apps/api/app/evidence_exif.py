"""Store an allowlisted metadata snapshot separately from original evidence."""
import json

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .image_metadata import inspect_image
from .models import EvidenceImageMetadata, utc_now_naive


def image_metadata_record(row):
    if row is None:
        return None
    return {"status": row.status, "fields": json.loads(row.fields_json),
            "inspected_at": row.inspected_at.isoformat() + "Z"}


def save_image_metadata(db, evidence_id, inspection):
    constructor = postgresql_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = constructor(EvidenceImageMetadata).values(
        evidence_id=evidence_id, status=inspection["status"],
        fields_json=json.dumps(inspection["fields"], separators=(",", ":")), inspected_at=utc_now_naive(),
    )
    db.execute(stmt.on_conflict_do_update(
        index_elements=[EvidenceImageMetadata.evidence_id],
        set_={"status": stmt.excluded.status, "fields_json": stmt.excluded.fields_json,
              "inspected_at": stmt.excluded.inspected_at},
        where=EvidenceImageMetadata.status == "unavailable",
    ))
    return image_metadata_record(db.get(EvidenceImageMetadata, evidence_id, populate_existing=True))


def inspect_verified_image(db, evidence_id, content):
    existing = db.get(EvidenceImageMetadata, evidence_id)
    if existing is not None and existing.status != "unavailable":
        return image_metadata_record(existing)
    return save_image_metadata(db, evidence_id, inspect_image(content))
