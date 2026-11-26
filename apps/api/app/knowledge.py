"""Tenant knowledge documents, immutable versions, and ranked keyword retrieval."""
import base64
from datetime import timedelta
import hashlib
import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import delete, func, or_, select
from starlette.concurrency import run_in_threadpool

from .ai_gateway import lock_organization
from .database import get_db
from .knowledge_extract import MAX_BODY, MAX_FILE, extract
from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeEmbedding, KnowledgeEmbeddingJob, KnowledgeVersion, utc_now_naive


KNOWLEDGE_WRITERS = ("owner", "organization_admin", "forensic_investigator", "security_analyst", "business_analyst")
STOP = set("about and are could does for from have how into is of show tell that the this was were what where which who with would you".split())


class Upload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    content_base64: str = Field(min_length=4, max_length=MAX_BODY)


class DocumentInput(Upload):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    visibility: Literal["private", "organization"] = "private"
    retention_days: int = Field(90, ge=1, le=365)


class DocumentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["private", "organization"]
    retention_days: int = Field(ge=1, le=365)


def document_scope(user, *, active=True):
    clauses = [
        KnowledgeDocument.organization_id == user.organization_id,
        or_(KnowledgeDocument.visibility == "organization", KnowledgeDocument.owner_id == user.id),
    ]
    if active:
        clauses.append(or_(KnowledgeDocument.expires_at.is_(None), KnowledgeDocument.expires_at > utc_now_naive()))
    return clauses


def owned_document(db, user, document_id, *, active=True, writer=False):
    row = db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.id == document_id, *document_scope(user, active=active),
    ))
    if row is None:
        raise HTTPException(404, "Knowledge document is unavailable")
    if writer and row.owner_id != user.id and user.role not in ("owner", "organization_admin"):
        raise HTTPException(403, "Only the document owner or an organization administrator can make this change")
    return row


def document_record(row, user):
    return {"id": row.id, "title": row.title, "visibility": row.visibility, "version": row.revision,
            "status": "expired" if row.expires_at and row.expires_at <= utc_now_naive() else "ready",
            "can_manage": row.owner_id == user.id or user.role in ("owner", "organization_admin"),
            "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
            "updated_at": row.updated_at.isoformat() + "Z"}


async def read_upload(request, schema):
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > MAX_BODY:
            raise HTTPException(413, "Knowledge upload exceeds 2 MiB")
        body.extend(part)
    try:
        value = schema.model_validate_json(body)
        filename = value.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not filename or not filename.isprintable():
            raise ValueError
        payload = base64.b64decode(value.content_base64, validate=True)
    except (ValueError, ValidationError):
        raise HTTPException(422, "Upload metadata or file encoding is invalid") from None
    if not 0 < len(payload) <= MAX_FILE:
        raise HTTPException(413, "Knowledge upload exceeds 2 MiB or is empty")
    try:
        sections = await run_in_threadpool(extract, filename, payload)
    except BlockingIOError:
        raise HTTPException(503, "Document extraction is busy. Try again shortly") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return value, filename, hashlib.sha256(payload).hexdigest(), sections


def save_version(db, doc, filename, digest, sections):
    db.add(KnowledgeVersion(document_id=doc.id, number=doc.revision, filename=filename, digest=digest))
    db.flush()
    ordinal = 0
    for location, text in sections:
        for offset in range(0, len(text), 800):
            content = text[offset:offset + 1000].strip()
            ordinal += 1
            db.add(KnowledgeChunk(document_id=doc.id, version=doc.revision, ordinal=ordinal,
                                  location=location, text=content, search_text=content.casefold()))


def terms_for(query):
    return list(dict.fromkeys(term for term in re.findall(r"[^\W_][\w-]{1,39}", query.casefold())
                              if term not in STOP))[:12]


def citation(chunk, doc, version):
    return {"key": f"knowledge:{chunk.id}", "kind": "document", "title": doc.title,
            "excerpt": chunk.text, "version": chunk.version, "location": chunk.location,
            "filename": version.filename, "document_id": doc.id, "href": f"/platform/knowledge?document={doc.id}"}


def chunk_query(user):
    return select(KnowledgeChunk, KnowledgeDocument, KnowledgeVersion).select_from(KnowledgeChunk).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id,
    ).join(KnowledgeVersion, (KnowledgeVersion.document_id == KnowledgeChunk.document_id)
           & (KnowledgeVersion.number == KnowledgeChunk.version)).where(*document_scope(user))


def retrieve(db, user, query, limit=6, document_id=None):
    terms = terms_for(query)
    if not terms:
        return []
    match_conditions = [
        KnowledgeChunk.search_text.contains(term, autoescape=True) for term in terms
    ] + [
        func.lower(KnowledgeDocument.title).contains(term, autoescape=True) for term in terms
    ]
    stmt = chunk_query(user).where(KnowledgeChunk.version == KnowledgeDocument.revision, or_(*match_conditions))
    if document_id:
        stmt = stmt.where(KnowledgeDocument.id == document_id)
    rows = db.execute(stmt.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.ordinal).limit(150)).all()
    ranked = sorted(rows, key=lambda row: -sum(
        int(term in row.KnowledgeChunk.search_text) + 2 * int(term in row.KnowledgeDocument.title.casefold())
        for term in terms
    ))
    return [citation(*row) for row in ranked[:limit]]


def resolve_documents(db, user, keys):
    ids = [key.removeprefix("knowledge:") for key in keys if key.startswith("knowledge:")]
    if not ids:
        return {}
    return {f"knowledge:{chunk.id}": citation(chunk, doc, version)
            for chunk, doc, version in db.execute(
                chunk_query(user).where(
                    KnowledgeChunk.id.in_(ids),
                    KnowledgeChunk.version == KnowledgeDocument.revision,
                )
            )}


def build_knowledge_router(current_user, require_roles, audit):
    router = APIRouter(prefix="/api/v1/knowledge")
    writer = Depends(require_roles(*KNOWLEDGE_WRITERS))
    reader = Depends(current_user)

    @router.get("/documents")
    def documents(db=Depends(get_db), user=reader):
        rows = db.scalars(select(KnowledgeDocument).where(*document_scope(user, active=False))
                         .order_by(KnowledgeDocument.updated_at.desc()).limit(200))
        return [document_record(row, user) for row in rows if
                row.expires_at is None or row.expires_at > utc_now_naive() or row.owner_id == user.id]

    @router.post("/documents", status_code=201)
    async def create(request: Request, db=Depends(get_db), user=writer):
        value, filename, digest, sections = await read_upload(request, DocumentInput)
        lock_organization(db, user.organization_id)
        same = db.scalar(select(KnowledgeDocument.id).join(KnowledgeVersion).where(
            KnowledgeDocument.organization_id == user.organization_id, KnowledgeDocument.owner_id == user.id,
            KnowledgeVersion.digest == digest,
        ).limit(1))
        if same:
            raise HTTPException(409, "You already indexed this file")
        count = db.scalar(select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.organization_id == user.organization_id,
        ))
        if count >= 200:
            raise HTTPException(429, "This organization reached its document capacity")
        doc = KnowledgeDocument(organization_id=user.organization_id, owner_id=user.id, title=value.title,
                                visibility=value.visibility, expires_at=utc_now_naive() + timedelta(days=value.retention_days))
        db.add(doc)
        db.flush()
        save_version(db, doc, filename, digest, sections)
        audit(db, user.organization_id, user.id, "knowledge.document.created", f"knowledge:{doc.id}", {"version": 1})
        db.commit()
        return document_record(doc, user)

    @router.get("/documents/{document_id}")
    def document(document_id: str, db=Depends(get_db), user=reader):
        row = owned_document(db, user, document_id)
        versions = db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id == row.id)
                              .order_by(KnowledgeVersion.number.desc())).all()
        return document_record(row, user) | {"versions": [
            {"version": version.number, "filename": version.filename, "sha256": version.digest,
             "created_at": version.created_at.isoformat() + "Z"} for version in versions
        ]}

    @router.post("/documents/{document_id}/versions", status_code=201)
    async def new_version(document_id: str, request: Request, db=Depends(get_db), user=writer):
        owned_document(db, user, document_id, writer=True)
        _, filename, digest, sections = await read_upload(request, Upload)
        lock_organization(db, user.organization_id)
        row = owned_document(db, user, document_id, writer=True)
        if row.revision >= 20:
            raise HTTPException(409, "The document reached its version limit")
        if db.scalar(select(KnowledgeVersion.number).where(KnowledgeVersion.document_id == row.id,
                                                           KnowledgeVersion.digest == digest)):
            raise HTTPException(409, "This content already exists in the document history")
        row.revision += 1
        row.updated_at = utc_now_naive()
        save_version(db, row, filename, digest, sections)
        audit(db, user.organization_id, user.id, "knowledge.document.versioned", f"knowledge:{row.id}",
              {"version": row.revision})
        db.commit()
        return document_record(row, user)

    @router.put("/documents/{document_id}/policy")
    def policy(document_id: str, value: DocumentPolicy, db=Depends(get_db), user=writer):
        lock_organization(db, user.organization_id)
        row = owned_document(db, user, document_id, writer=True, active=False)
        row.visibility = value.visibility
        row.updated_at = utc_now_naive()
        row.expires_at = row.updated_at + timedelta(days=value.retention_days)
        audit(db, user.organization_id, user.id, "knowledge.document.policy", f"knowledge:{row.id}",
              {"visibility": row.visibility, "retention_days": value.retention_days})
        db.commit()
        return document_record(row, user)

    @router.delete("/documents/{document_id}", status_code=204)
    def remove(document_id: str, db=Depends(get_db), user=writer):
        lock_organization(db, user.organization_id)
        row = owned_document(db, user, document_id, writer=True, active=False)
        db.execute(delete(KnowledgeEmbeddingJob).where(KnowledgeEmbeddingJob.document_id == row.id))
        db.execute(delete(KnowledgeEmbedding).where(KnowledgeEmbedding.chunk_id.in_(
            select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == row.id),
        )).execution_options(synchronize_session=False))
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == row.id))
        db.execute(delete(KnowledgeVersion).where(KnowledgeVersion.document_id == row.id))
        db.delete(row)
        audit(db, user.organization_id, user.id, "knowledge.document.deleted", f"knowledge:{document_id}", {})
        db.commit()

    @router.get("/search")
    def search(query: str = Query(min_length=2, max_length=180), document_id: str | None = Query(None, max_length=120),
               db=Depends(get_db), user=reader):
        if document_id:
            owned_document(db, user, document_id)
        return {"method": "keyword", "sources": retrieve(db, user, query, limit=12, document_id=document_id)}

    return router
