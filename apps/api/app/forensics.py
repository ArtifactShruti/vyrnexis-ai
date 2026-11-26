"""Tenant forensic cases, immutable note revisions and custody ledgers."""
from datetime import timezone
import hashlib
import hmac
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .evidence_exif import image_metadata_record, inspect_verified_image
from .forensic_pdf import render_report
from .models import (
    AuditLog, CommerceFinding, CustodyEnrollment, CustodyEvent, Evidence, EvidenceFileMetadata, EvidenceImageMetadata,
    ForensicCase, ForensicCaseLink, ForensicNote, ForensicReport, Incident, IntelligenceEntity,
    InvestigationRun, InvestigationTask, User, utc_now_naive,
)


ADMIN = {"owner", "organization_admin"}
WRITERS = ADMIN | {"forensic_investigator"}
READERS = WRITERS | {"security_analyst"}
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)]
Purpose = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Status = Literal["open", "investigating", "review", "closed"]
REFERENCES = {"incident": Incident, "finding": CommerceFinding, "entity": IntelligenceEntity, "evidence": Evidence}
TRANSITIONS = {"open": {"investigating"}, "investigating": {"review"},
               "review": {"investigating", "closed"}, "closed": {"investigating"}}
CUSTODY_LIMIT = 1000


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseInput(Input):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=240)]
    description: Description
    category: Literal["security", "fraud", "compliance", "other"]
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class Assignment(Input):
    investigator_id: Label | None = None
    team: Label | None = None
    expected_version: int = Field(ge=1)


class Transition(Input):
    status: Status
    expected_version: int = Field(ge=1)
    reason: Purpose


class Reference(Input):
    kind: Literal["incident", "finding", "entity", "evidence"]
    object_id: Label


class NoteInput(Input):
    category: Literal["observation", "hypothesis", "finding", "review"]
    body: Description
    references: list[Reference] = Field(default_factory=list, max_length=12)


class NoteRevision(NoteInput):
    expected_revision: int = Field(ge=1)


class Registration(Input):
    evidence_id: Label
    classification: Literal["document", "log", "image", "archive", "other"]
    tags: list[Label] = Field(default_factory=list, max_length=12)
    custodian_id: Label | None = None
    purpose: Purpose


class CustodyInput(Input):
    action: Literal["transfer", "verify", "examine", "archive"]
    purpose: Purpose
    custodian_id: Label | None = None
    expected_sequence: int = Field(ge=1)


class ExportInput(Input):
    purpose: Purpose


def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def canonical(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(payload) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def owned_case(db, case_id, user):
    case = db.scalar(select(ForensicCase).where(
        ForensicCase.id == case_id, ForensicCase.organization_id == user.organization_id,
    ))
    if case is None:
        raise HTTPException(404, "Forensic case not found")
    return case


def lock_case(db, case_id, user, version=None, *, allow_closed=False):
    where = [ForensicCase.id == case_id, ForensicCase.organization_id == user.organization_id]
    if not allow_closed:
        where.append(ForensicCase.status != "closed")
    if version is not None:
        where.append(ForensicCase.version == version)
    changed = db.execute(update(ForensicCase).where(*where).values(
        version=ForensicCase.version + 1, updated_at=utc_now_naive(),
    )).rowcount
    case = owned_case(db, case_id, user)
    if not changed:
        raise HTTPException(409, "Reload the case. Its version or status has changed.")
    return case


def case_record(case, investigator_name=None):
    return {key: getattr(case, key) for key in (
        "id", "title", "description", "category", "priority", "status", "investigator_id", "team",
        "closure_summary", "version", "creator_id",
    )} | {"investigator_name": investigator_name, "created_at": stamp(case.created_at), "updated_at": stamp(case.updated_at)}


def case_owner(db, case):
    if case.investigator_id is None:
        return None
    return db.scalar(select(User.full_name).where(User.id == case.investigator_id,
                                                  User.organization_id == case.organization_id))


def note_record(note):
    return {"id": note.note_id, "revision": note.revision, "author_id": note.author_id,
            "category": note.category, "body": note.body, "references": json.loads(note.references_json),
            "time": stamp(note.created_at)}


def case_activity(db, case):
    events = db.scalars(select(AuditLog).where(AuditLog.organization_id == case.organization_id,
        AuditLog.resource == f"forensic_case:{case.id}")
        .order_by(AuditLog.created_at.desc(), AuditLog.id).limit(100)).all()
    return [{"action": item.action, "actor_id": item.actor_id, "time": stamp(item.created_at),
             "details": json.loads(item.details)} for item in events]


def validate_reference(db, case, reference):
    model = REFERENCES[reference.kind]
    if not db.scalar(select(model.id).where(model.id == reference.object_id,
                                             model.organization_id == case.organization_id)):
        raise HTTPException(404, "Related object not found")


def investigator(db, org, user_id):
    if user_id is None:
        return None
    item = db.scalar(select(User).where(User.id == user_id, User.organization_id == org,
                                        User.is_active.is_(True), User.role.in_(WRITERS)))
    if item is None:
        raise HTTPException(404, "Eligible investigator not found")
    return item


def custody_payload(event):
    return {key: getattr(event, key) for key in (
        "evidence_id", "sequence", "case_id", "organization_id", "actor_id", "action", "previous_custodian_id",
        "new_custodian_id", "purpose", "evidence_hash", "previous_hash",
    )} | {"time": stamp(event.created_at)}


def custody_chain(db, enrollment, evidence):
    rows = db.scalars(select(CustodyEvent).where(CustodyEvent.evidence_id == enrollment.evidence_id,
        CustodyEvent.organization_id == enrollment.organization_id, CustodyEvent.case_id == enrollment.case_id)
        .order_by(CustodyEvent.sequence).limit(CUSTODY_LIMIT + 1)).all()
    previous = None
    custodian = None
    valid = 0 < len(rows) <= CUSTODY_LIMIT
    for index, row in enumerate(rows, 1):
        valid = (valid and row.sequence == index and row.previous_hash == previous
                 and row.previous_custodian_id == custodian and row.evidence_hash == evidence.sha256
                 and hmac.compare_digest(row.integrity_hash, checksum(custody_payload(row))))
        previous, custodian = row.integrity_hash, row.new_custodian_id
    valid = (valid and previous == enrollment.head_hash and len(rows) == enrollment.last_sequence
             and custodian == enrollment.custodian_id and enrollment.archived == (
                 bool(rows) and rows[-1].action == "archived"))
    return valid, [custody_payload(row) | {"integrity_hash": row.integrity_hash} for row in rows]


def append_custody(db, enrollment, evidence, actor, action, purpose, new_custodian):
    if enrollment.last_sequence >= CUSTODY_LIMIT:
        raise HTTPException(409, "The custody ledger reached its configured event limit")
    row = CustodyEvent(
        case_id=enrollment.case_id, organization_id=enrollment.organization_id,
        evidence_id=enrollment.evidence_id, sequence=enrollment.last_sequence + 1,
        actor_id=actor.id, action=action, previous_custodian_id=enrollment.custodian_id,
        new_custodian_id=new_custodian, purpose=purpose, evidence_hash=evidence.sha256,
        previous_hash=enrollment.head_hash, created_at=utc_now_naive(),
    )
    row.integrity_hash = checksum(custody_payload(row))
    enrollment.last_sequence, enrollment.head_hash, enrollment.custodian_id = (
        row.sequence, row.integrity_hash, new_custodian,
    )
    db.add(row)
    return custody_payload(row) | {"integrity_hash": row.integrity_hash}


def evidence_summary(db, item, evidence):
    meta = db.get(EvidenceFileMetadata, evidence.id)
    return {"id": evidence.id, "name": evidence.name, "sha256": evidence.sha256, "sha512": evidence.sha512,
            "mime_type": evidence.mime_type, "original_filename": meta.original_filename if meta else None,
            "signature": meta.signature if meta else None, "size_bytes": meta.size_bytes if meta else None,
            "image_metadata": image_metadata_record(db.get(EvidenceImageMetadata, evidence.id)),
            "classification": item.classification, "tags": json.loads(item.tags_json),
            "custodian_id": item.custodian_id, "sequence": item.last_sequence, "archived": item.archived}


def case_evidence(db, case):
    return db.execute(select(CustodyEnrollment, Evidence).join(Evidence, Evidence.id == CustodyEnrollment.evidence_id)
        .where(CustodyEnrollment.case_id == case.id, CustodyEnrollment.organization_id == case.organization_id,
               Evidence.organization_id == case.organization_id).order_by(Evidence.created_at).limit(101)).all()


def enrolled(db, case, evidence_id):
    item = db.get(CustodyEnrollment, evidence_id)
    evidence = db.get(Evidence, evidence_id)
    if (item is None or evidence is None or item.case_id != case.id or item.organization_id != case.organization_id
            or evidence.organization_id != case.organization_id):
        raise HTTPException(404, "Case evidence not found")
    return item, evidence


def report_record(report):
    return {"id": report.id, "version": report.version, "integrity_hash": report.integrity_hash,
            "created_at": stamp(report.created_at)}


def build_forensic_router(require_roles, audit, read_bytes, integrity_ok):
    router = APIRouter(prefix="/api/v1/forensic-cases")
    reader = Depends(require_roles(*READERS))
    writer = Depends(require_roles(*WRITERS))
    administrator = Depends(require_roles(*ADMIN))

    @router.get("/investigators")
    def investigator_list(db: Session = Depends(get_db), user: User = reader):
        rows = db.scalars(select(User).where(User.organization_id == user.organization_id,
            User.is_active.is_(True), User.role.in_(WRITERS)).order_by(User.full_name).limit(200)).all()
        return [{"id": row.id, "name": row.full_name} for row in rows]

    @router.get("")
    def list_cases(
        status: Status | None = None, query: str = Query(default="", max_length=120),
        assigned: bool = False, sort: Literal["recent", "oldest", "title"] = "recent",
        offset: int = Query(0, ge=0, le=10000), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(get_db), user: User = reader,
    ):
        stmt = select(ForensicCase).where(ForensicCase.organization_id == user.organization_id)
        if status:
            stmt = stmt.where(ForensicCase.status == status)
        if assigned:
            stmt = stmt.where(ForensicCase.investigator_id == user.id)
        if query.strip():
            stmt = stmt.where(ForensicCase.title.icontains(query.strip(), autoescape=True)
                              | ForensicCase.id.icontains(query.strip(), autoescape=True))
        ordering = {"recent": ForensicCase.updated_at.desc(), "oldest": ForensicCase.created_at,
                    "title": ForensicCase.title}
        rows = db.scalars(stmt.order_by(ordering[sort], ForensicCase.id).offset(offset).limit(limit + 1)).all()
        return {"items": [case_record(item, case_owner(db, item)) for item in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None}

    @router.post("", status_code=201)
    def create_case(payload: CaseInput, db: Session = Depends(get_db), user: User = writer):
        case = ForensicCase(organization_id=user.organization_id, creator_id=user.id, **payload.model_dump())
        db.add(case)
        db.flush()
        audit(db, user.organization_id, user.id, "forensic.case.created", f"forensic_case:{case.id}", {})
        db.commit()
        return case_record(case)

    @router.get("/{case_id}")
    def detail(case_id: str, db: Session = Depends(get_db), user: User = reader):
        case = owned_case(db, case_id, user)
        links = db.scalars(select(ForensicCaseLink).where(ForensicCaseLink.case_id == case.id)
                           .order_by(ForensicCaseLink.created_at.desc()).limit(200)).all()
        notes = db.scalars(select(ForensicNote).where(ForensicNote.case_id == case.id)
                           .order_by(ForensicNote.created_at.desc(), ForensicNote.revision.desc()).limit(100)).all()
        return case_record(case, case_owner(db, case)) | {"links": [
            {"kind": item.kind, "object_id": item.object_id} for item in links
        ], "notes": [note_record(note) for note in notes],
            "evidence": [evidence_summary(db, *item) for item in case_evidence(db, case)[:100]],
            "activity": case_activity(db, case)}

    @router.put("/{case_id}/assignment")
    def assign(case_id: str, payload: Assignment, db: Session = Depends(get_db), user: User = administrator):
        target = investigator(db, user.organization_id, payload.investigator_id)
        case = lock_case(db, case_id, user, payload.expected_version)
        previous = case.investigator_id
        case.investigator_id, case.team = payload.investigator_id, payload.team
        audit(db, user.organization_id, user.id, "forensic.case.assigned", f"forensic_case:{case.id}",
              {"previous_investigator_id": previous, "investigator_id": case.investigator_id, "team": case.team})
        db.commit()
        return case_record(case, target.full_name if target else None)

    @router.post("/{case_id}/transition")
    def transition(case_id: str, payload: Transition, db: Session = Depends(get_db), user: User = writer):
        case = lock_case(db, case_id, user, payload.expected_version, allow_closed=True)
        if case.status == "closed" and user.role not in ADMIN:
            raise HTTPException(403, "Only an organization administrator can reopen a case")
        if payload.status not in TRANSITIONS[case.status]:
            raise HTTPException(409, "Unsupported case status transition")
        if payload.status == "closed":
            if case.investigator_id is None or len(payload.reason) < 12:
                raise HTTPException(422, "Closure requires an assigned investigator and a substantive summary")
            # Only the most recent revision of a note can satisfy closure.
            latest = select(ForensicNote.note_id, func.max(ForensicNote.revision).label("revision")).where(
                ForensicNote.case_id == case.id).group_by(ForensicNote.note_id).subquery()
            review = db.scalar(select(ForensicNote.note_id).join(latest, (ForensicNote.note_id == latest.c.note_id)
                & (ForensicNote.revision == latest.c.revision)).where(ForensicNote.category == "review").limit(1))
            if not review:
                raise HTTPException(422, "Closure requires a current reviewer note")
        previous = case.status
        case.status = payload.status
        case.closure_summary = payload.reason if payload.status == "closed" else None
        audit(db, user.organization_id, user.id, "forensic.case.transition", f"forensic_case:{case.id}",
              {"from": previous, "to": payload.status, "reason": payload.reason})
        db.commit()
        return case_record(case, case_owner(db, case))

    @router.post("/{case_id}/links")
    def link(case_id: str, payload: Reference, db: Session = Depends(get_db), user: User = writer):
        case = lock_case(db, case_id, user)
        validate_reference(db, case, payload)
        if payload.kind == "evidence":
            raise HTTPException(422, "Register evidence through the custody enrollment endpoint")
        identity = (case.id, payload.kind, payload.object_id)
        if not db.get(ForensicCaseLink, identity):
            db.add(ForensicCaseLink(case_id=case.id, **payload.model_dump()))
            audit(db, user.organization_id, user.id, "forensic.case.linked", f"forensic_case:{case.id}", payload.model_dump())
        db.commit()
        return payload.model_dump()

    def save_note(db, case, user, payload, prior=None):
        for reference in payload.references:
            validate_reference(db, case, reference)
            if not db.get(ForensicCaseLink, (case.id, reference.kind, reference.object_id)):
                raise HTTPException(422, "Note references must already be associated with this case")
        note = ForensicNote(case_id=case.id, author_id=user.id, category=payload.category, body=payload.body,
                            references_json=canonical([item.model_dump() for item in payload.references]),
                            revision=prior.revision + 1 if prior else 1)
        if prior:
            note.note_id = prior.note_id
        db.add(note)
        db.flush()
        audit(db, user.organization_id, user.id, "forensic.note.revised" if prior else "forensic.note.created",
              f"forensic_case:{case.id}", {"note_id": note.note_id, "revision": note.revision})
        db.commit()
        return note_record(note)

    @router.post("/{case_id}/notes", status_code=201)
    def add_note(case_id: str, payload: NoteInput, db: Session = Depends(get_db), user: User = writer):
        return save_note(db, lock_case(db, case_id, user), user, payload)

    @router.post("/{case_id}/notes/{note_id}/revisions", status_code=201)
    def revise_note(case_id: str, note_id: str, payload: NoteRevision, db: Session = Depends(get_db), user: User = writer):
        case = lock_case(db, case_id, user)
        latest = db.scalars(select(ForensicNote).where(ForensicNote.case_id == case.id, ForensicNote.note_id == note_id)
                            .order_by(ForensicNote.revision.desc()).limit(2)).all()
        if not latest:
            raise HTTPException(404, "Note not found")
        original_author = db.scalar(select(ForensicNote.author_id).where(
            ForensicNote.case_id == case.id, ForensicNote.note_id == note_id, ForensicNote.revision == 1,
        ))
        if user.id != original_author and user.role not in ADMIN:
            raise HTTPException(403, "Only the original author or an administrator can revise this note")
        if latest[0].revision != payload.expected_revision:
            raise HTTPException(409, "The note has a newer revision")
        return save_note(db, case, user, payload, latest[0])

    @router.post("/{case_id}/evidence", status_code=201)
    def register_evidence(case_id: str, payload: Registration, db: Session = Depends(get_db), user: User = writer):
        case = lock_case(db, case_id, user)
        evidence = db.scalar(select(Evidence).where(Evidence.id == payload.evidence_id,
                                                     Evidence.organization_id == user.organization_id))
        if evidence is None:
            raise HTTPException(404, "Evidence not found")
        investigator(db, user.organization_id, payload.custodian_id)
        item = CustodyEnrollment(case_id=case.id, organization_id=user.organization_id,
                                 evidence_id=evidence.id, classification=payload.classification,
                                 tags_json=canonical(sorted(set(payload.tags))))
        db.add(item)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Evidence already has a forensic custody ledger") from exc
        db.add(ForensicCaseLink(case_id=case.id, kind="evidence", object_id=evidence.id))
        append_custody(db, item, evidence, user, "registered", payload.purpose, payload.custodian_id or user.id)
        audit(db, user.organization_id, user.id, "forensic.evidence.registered", f"forensic_case:{case.id}",
              {"evidence_id": evidence.id})
        db.commit()
        return evidence_summary(db, item, evidence)

    @router.get("/{case_id}/evidence/{evidence_id}/custody")
    def custody(case_id: str, evidence_id: str, db: Session = Depends(get_db), user: User = reader):
        item, evidence = enrolled(db, owned_case(db, case_id, user), evidence_id)
        valid, rows = custody_chain(db, item, evidence)
        return {"chain_status": "valid" if valid else "mismatch", "events": rows}

    @router.post("/{case_id}/evidence/{evidence_id}/custody")
    def change_custody(case_id: str, evidence_id: str, payload: CustodyInput,
                       db: Session = Depends(get_db), user: User = writer):
        case = lock_case(db, case_id, user)
        item, evidence = enrolled(db, case, evidence_id)
        if item.archived or item.last_sequence != payload.expected_sequence or not custody_chain(db, item, evidence)[0]:
            raise HTTPException(409, "Custody ledger is archived, changed, or inconsistent")
        target = item.custodian_id
        if payload.action in {"transfer", "archive"} and user.id != target and user.role not in ADMIN:
            raise HTTPException(403, "Only the custodian or an administrator can transfer or archive evidence")
        if payload.action == "transfer":
            if not payload.custodian_id or payload.custodian_id == target:
                raise HTTPException(422, "Select a different investigator for the transfer")
            target = investigator(db, user.organization_id, payload.custodian_id).id
        action = {"transfer": "transferred", "examine": "examined", "archive": "archived", "verify": "verified"}[payload.action]
        if payload.action == "verify":
            try:
                content = read_bytes(evidence)
            except HTTPException:
                action = "bytes_unavailable"
            else:
                valid = integrity_ok(evidence, content)
                if valid:
                    inspect_verified_image(db, evidence.id, content)
                action = "verified" if valid else "verification_failed"
        item.archived = action == "archived"
        result = append_custody(db, item, evidence, user, action, payload.purpose, target)
        audit(db, user.organization_id, user.id, f"forensic.custody.{action}", f"forensic_case:{case.id}",
              {"evidence_id": evidence.id, "sequence": item.last_sequence})
        db.commit()
        return result

    @router.post("/{case_id}/evidence/{evidence_id}/export")
    def export_evidence(case_id: str, evidence_id: str, payload: ExportInput,
                        db: Session = Depends(get_db), user: User = writer):
        from urllib.parse import quote

        case = lock_case(db, case_id, user, allow_closed=True)
        item, evidence = enrolled(db, case, evidence_id)
        if not custody_chain(db, item, evidence)[0]:
            raise HTTPException(409, "Custody chain failed its consistency check")
        content = read_bytes(evidence)
        if not integrity_ok(evidence, content) or item.archived:
            raise HTTPException(409, "Evidence has changed or is archived")
        append_custody(db, item, evidence, user, "exported", payload.purpose, item.custodian_id)
        audit(db, user.organization_id, user.id, "forensic.evidence.exported", f"forensic_case:{case.id}",
              {"evidence_id": evidence.id})
        db.commit()
        return Response(content, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(evidence.name, safe='')}",
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        })

    @router.get("/{case_id}/reports")
    def reports(case_id: str, db: Session = Depends(get_db), user: User = reader):
        case = owned_case(db, case_id, user)
        rows = db.scalars(select(ForensicReport).where(ForensicReport.case_id == case.id,
            ForensicReport.organization_id == user.organization_id).order_by(ForensicReport.version.desc()).limit(100))
        return [report_record(row) for row in rows]

    @router.post("/{case_id}/reports", status_code=201)
    def create_report(case_id: str, db: Session = Depends(get_db), user: User = writer):
        case = lock_case(db, case_id, user, allow_closed=True)
        notes = db.scalars(select(ForensicNote).where(ForensicNote.case_id == case.id)
                           .order_by(ForensicNote.created_at, ForensicNote.note_id, ForensicNote.revision).limit(201)).all()
        links = db.scalars(select(ForensicCaseLink).where(ForensicCaseLink.case_id == case.id)
                           .order_by(ForensicCaseLink.kind, ForensicCaseLink.object_id).limit(501)).all()
        evidence_rows = case_evidence(db, case)
        if len(notes) > 200 or len(links) > 500 or len(evidence_rows) > 100 or sum(item.last_sequence for item, _ in evidence_rows) > 1000:
            raise HTTPException(413, "This case exceeds the bounded report size")
        items = []
        for item, evidence in evidence_rows:
            valid, chain = custody_chain(db, item, evidence)
            items.append(evidence_summary(db, item, evidence) | {"chain_status": "valid" if valid else "mismatch", "custody": chain})
        version = (db.scalar(select(func.max(ForensicReport.version)).where(ForensicReport.case_id == case.id)) or 0) + 1
        now = utc_now_naive()
        run = db.scalars(select(InvestigationRun).where(InvestigationRun.case_id == case.id,
            InvestigationRun.organization_id == user.organization_id,
            InvestigationRun.status.in_(("approved", "awaiting_approval")))
            .order_by(InvestigationRun.created_at.desc()).limit(1)).first()
        agent_tasks = db.scalars(select(InvestigationTask).where(
            InvestigationTask.run_id == run.id, InvestigationTask.result_json.is_not(None),
        ).order_by(InvestigationTask.agent)).all() if run else []
        snapshot = {"version": version, "created_at": stamp(now), "generated_by": user.id,
                    "scope": "Recorded investigation material. Analyst hypotheses and automated analysis are not independently certified conclusions.",
                    "case": case_record(case, case_owner(db, case)), "notes": [note_record(note) for note in notes],
                    "links": [{"kind": link.kind, "object_id": link.object_id} for link in links],
                    "evidence": items, "activity": case_activity(db, case),
                    "agent_run_status": run.status if run else None,
                    "agent_findings": [json.loads(task.result_json) for task in agent_tasks]}
        encoded = canonical(snapshot)
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise HTTPException(413, "This case exceeds the bounded report size")
        report = ForensicReport(case_id=case.id, organization_id=user.organization_id, creator_id=user.id,
                                version=version, snapshot_json=encoded,
                                integrity_hash=checksum(snapshot), created_at=now)
        db.add(report)
        db.flush()
        audit(db, user.organization_id, user.id, "forensic.report.created", f"forensic_case:{case.id}",
              {"report_id": report.id, "version": version})
        db.commit()
        return report_record(report)

    @router.get("/{case_id}/reports/{report_id}/{format}")
    def report_content(case_id: str, report_id: str, format: Literal["json", "pdf"],
                       db: Session = Depends(get_db), user: User = reader):
        case = owned_case(db, case_id, user)
        report = db.scalar(select(ForensicReport).where(ForensicReport.id == report_id, ForensicReport.case_id == case.id,
                                                        ForensicReport.organization_id == user.organization_id))
        if report is None:
            raise HTTPException(404, "Forensic report not found")
        snapshot = json.loads(report.snapshot_json)
        if not hmac.compare_digest(checksum(snapshot), report.integrity_hash):
            raise HTTPException(409, "The stored report integrity check failed")
        payload = (canonical(report_record(report) | {"snapshot": snapshot}).encode("utf-8") if format == "json"
                   else render_report(snapshot, report.integrity_hash))
        audit(db, user.organization_id, user.id, "forensic.report.exported", f"forensic_case:{case.id}",
              {"report_id": report.id, "format": format})
        db.commit()
        return Response(payload, media_type="application/json" if format == "json" else "application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=case-{case.id}-v{report.version}.{format}",
                                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    return router
