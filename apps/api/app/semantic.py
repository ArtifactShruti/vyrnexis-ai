"""Opt-in local Ollama embeddings and bounded tenant-filtered cosine retrieval."""
from dataclasses import dataclass
from datetime import timedelta
import json
from math import hypot, isfinite
import os
import re
from time import monotonic
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
import httpx
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .ai_gateway import lock_organization
from .database import SessionLocal, get_db
from .detection import notify_worker
from .forensics import Input, Label, canonical
from .knowledge import KNOWLEDGE_WRITERS, chunk_query, citation, owned_document, retrieve
from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeEmbedding, KnowledgeEmbeddingJob, User, utc_now_naive
from .nexus import worker_mode


BATCH = 16
CANDIDATES = 800


class EmbeddingError(ValueError):
    pass


@dataclass(frozen=True)
class EmbeddingProvider:
    base: str
    model: str
    revision: str

    @property
    def profile(self):
        return f"ollama:{self.model}:{self.revision}"

    def embed(self, inputs, transport=None):
        try:
            deadline = monotonic() + 6
            with httpx.Client(timeout=4, follow_redirects=False, trust_env=False, transport=transport) as client:
                with client.stream("POST", self.base + "/api/embed", json={
                    "model": self.model, "input": inputs, "truncate": False, "keep_alive": "2m",
                }) as response:
                    if not response.is_success:
                        raise EmbeddingError("embedding_provider_rejected")
                    data = bytearray()
                    for part in response.iter_bytes():
                        if monotonic() > deadline:
                            raise EmbeddingError("embedding_provider_deadline")
                        data.extend(part)
                        if len(data) > 768 * 1024:
                            raise EmbeddingError("embedding_response_limit")
            vectors = json.loads(data)["embeddings"]
            if not isinstance(vectors, list) or len(vectors) != len(inputs):
                raise EmbeddingError("embedding_invalid_response")
            result = [unit_vector(row) for row in vectors]
            if len({len(vector) for vector in result}) != 1:
                raise EmbeddingError("embedding_invalid_response")
            return result
        except httpx.RequestError as exc:
            raise EmbeddingError("embedding_provider_unreachable") from exc
        except EmbeddingError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise EmbeddingError("embedding_invalid_response") from exc


def unit_vector(values):
    if (not isinstance(values, list) or not 2 <= len(values) <= 2048
            or any(type(value) not in (float, int) or not isfinite(value) for value in values)):
        raise EmbeddingError("embedding_invalid_response")
    scale = hypot(*values)
    if not scale or not isfinite(scale):
        raise EmbeddingError("embedding_invalid_response")
    return [value / scale for value in values]


def configured_embedding():
    if os.getenv("VYRNEXIS_EMBEDDINGS_ENABLED") != "1":
        return None
    model = os.getenv("VYRNEXIS_EMBEDDING_MODEL", "")
    revision = os.getenv("VYRNEXIS_EMBEDDING_REVISION", "1")
    base = os.getenv("VYRNEXIS_EMBEDDING_URL", "").rstrip("/")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,100}", model)
            or model.lower().endswith(("-cloud", ":cloud")) or not re.fullmatch(r"\w{1,24}", revision)):
        return None
    try:
        url = urlsplit(base)
        _ = url.port
    except ValueError:
        return None
    if (url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1", "::1", "ollama", "host.docker.internal"}
            or url.username or url.password or url.query or url.fragment or url.path):
        return None
    return EmbeddingProvider(base, model, revision)


def process_embeddings(document_id=None, session_factory=SessionLocal):
    provider = configured_embedding()
    if provider is None:
        return False
    with session_factory.begin() as db:
        filters = [KnowledgeEmbeddingJob.profile == provider.profile, KnowledgeEmbeddingJob.status == "queued",
                   KnowledgeEmbeddingJob.available_at <= utc_now_naive()]
        if document_id:
            filters.append(KnowledgeEmbeddingJob.document_id == document_id)
        candidate = db.execute(select(KnowledgeEmbeddingJob.document_id, KnowledgeEmbeddingJob.version,
            KnowledgeDocument.organization_id).join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeEmbeddingJob.document_id)
            .where(*filters).order_by(KnowledgeEmbeddingJob.available_at).limit(1)).first()
        if candidate is None:
            return False
        lock_organization(db, candidate.organization_id)
        job = db.scalar(select(KnowledgeEmbeddingJob).where(*filters,
            KnowledgeEmbeddingJob.document_id == candidate.document_id,
            KnowledgeEmbeddingJob.version == candidate.version,
        ).with_for_update())
        if job is None:
            return False
        actor = db.get(User, job.actor_id)
        doc = db.get(KnowledgeDocument, job.document_id)
        if not actor or not actor.is_active or actor.role not in KNOWLEDGE_WRITERS or doc is None or (
            doc.organization_id != actor.organization_id or doc.revision != job.version
            or (doc.visibility == "private" and doc.owner_id != actor.id)
            or (doc.expires_at and doc.expires_at <= utc_now_naive())
        ):
            job.status, job.error = "failed", "document_unavailable"
            return True
        chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id,
            KnowledgeChunk.version == job.version, KnowledgeChunk.ordinal > job.cursor)
            .order_by(KnowledgeChunk.ordinal).limit(BATCH)).all()
        if not chunks:
            job.status = "completed"
            return True
        try:
            vectors = provider.embed([chunk.text for chunk in chunks])
        except EmbeddingError as exc:
            job.failures += 1
            job.error = str(exc)
            if job.failures >= 3:
                job.status = "failed"
            else:
                job.available_at = utc_now_naive() + timedelta(seconds=5 * job.failures)
            return True
        db.add_all(KnowledgeEmbedding(chunk_id=chunk.id, profile=job.profile, vector_json=canonical(vector))
                   for chunk, vector in zip(chunks, vectors, strict=True))
        job.cursor, job.error, job.failures = chunks[-1].ordinal, None, 0
        if len(chunks) < BATCH:
            job.status = "completed"
        return True


class IndexRequest(Input):
    acknowledge_local_processing: Literal[True]


class SemanticRequest(Input):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=180)]
    document_id: Label | None = None
    acknowledge_local_processing: Literal[True]


def hybrid_search(db, user, query, document_id):
    keywords = retrieve(db, user, query, limit=12, document_id=document_id)
    provider = configured_embedding()
    if provider is None:
        return {"method": "keyword", "reason": "local_embeddings_unconfigured", "sources": keywords}
    stmt = chunk_query(user).add_columns(KnowledgeEmbedding.vector_json).join(
        KnowledgeEmbedding, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id,
    ).join(KnowledgeEmbeddingJob, (KnowledgeEmbeddingJob.document_id == KnowledgeChunk.document_id)
           & (KnowledgeEmbeddingJob.version == KnowledgeChunk.version)
           & (KnowledgeEmbeddingJob.profile == KnowledgeEmbedding.profile),
    ).where(KnowledgeEmbedding.profile == provider.profile, KnowledgeChunk.version == KnowledgeDocument.revision,
            KnowledgeEmbeddingJob.status == "completed")
    if document_id:
        stmt = stmt.where(KnowledgeDocument.id == document_id)
    if db.execute(stmt.limit(1)).first() is None:
        return {"method": "keyword", "reason": "no_authorized_vectors", "sources": keywords}
    try:
        query_vector = provider.embed([query])[0]
    except EmbeddingError as exc:
        return {"method": "keyword", "reason": str(exc), "sources": retrieve(db, user, query, limit=12, document_id=document_id)}
    keywords = retrieve(db, user, query, limit=12, document_id=document_id)
    candidates = db.execute(stmt.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.id).limit(CANDIDATES + 1)).all()
    scored = []
    for chunk, doc, version, packed in candidates[:CANDIDATES]:
        vector = json.loads(packed)
        if len(vector) == len(query_vector):
            similarity = sum(left * right for left, right in zip(vector, query_vector, strict=True))
            scored.append((similarity, citation(chunk, doc, version)))
    if not scored:
        return {"method": "keyword", "reason": "embedding_dimension_mismatch", "sources": keywords}
    semantic = [item for score, item in sorted(scored, key=lambda row: -row[0])[:12] if score > 0]
    sources, weights = {}, {}
    for matches in (keywords, semantic):
        for rank, item in enumerate(matches, 1):
            sources[item["key"]] = item
            weights[item["key"]] = weights.get(item["key"], 0) + 1 / (10 + rank)
    combined = [sources[key] for key in sorted(weights, key=lambda key: (-weights[key], key))[:12]]
    return {"method": "hybrid", "profile": provider.profile, "candidate_limit_reached": len(candidates) > CANDIDATES,
            "sources": combined}


def build_semantic_router(current_user, require_roles, audit):
    router = APIRouter(prefix="/api/v1/knowledge")
    writer = Depends(require_roles(*KNOWLEDGE_WRITERS))
    reader = Depends(current_user)

    def index_state(db, document, provider):
        job = db.get(KnowledgeEmbeddingJob, (document.id, document.revision, provider.profile)) if provider else None
        return {"enabled": provider is not None, "status": job.status if job else "not_indexed",
                "chunks": job.cursor if job else 0, "error": job.error if job else None}

    @router.get("/embeddings/availability")
    def availability(user=reader):
        return {"enabled": configured_embedding() is not None}

    @router.get("/documents/{document_id}/embedding")
    def status(document_id: str, db=Depends(get_db), user=reader):
        return index_state(db, owned_document(db, user, document_id), configured_embedding())

    @router.post("/documents/{document_id}/embedding", status_code=202)
    def index(document_id: str, payload: IndexRequest, db=Depends(get_db), user=writer):
        provider = configured_embedding()
        if provider is None:
            raise HTTPException(409, "An authorized local embedding model is required")
        lock_organization(db, user.organization_id)
        doc = owned_document(db, user, document_id, writer=True)
        job = db.get(KnowledgeEmbeddingJob, (doc.id, doc.revision, provider.profile))
        if job is None:
            db.add(KnowledgeEmbeddingJob(document_id=doc.id, version=doc.revision,
                                         profile=provider.profile, actor_id=user.id))
            audit(db, user.organization_id, user.id, "knowledge.embedding.queued", f"knowledge:{doc.id}",
                  {"version": doc.revision, "profile": provider.profile})
        db.commit()
        if worker_mode():
            notify_worker()
        else:
            factory = sessionmaker(bind=db.get_bind())
            for _ in range(8):
                if not process_embeddings(document_id, factory):
                    break
        db.expire_all()
        return index_state(db, owned_document(db, user, document_id), provider)

    @router.post("/search/hybrid")
    def search(value: SemanticRequest, db=Depends(get_db), user=reader):
        if value.document_id:
            owned_document(db, user, value.document_id)
        result = hybrid_search(db, user, value.query, value.document_id)
        audit(db, user.organization_id, user.id, "knowledge.retrieval",
              f"knowledge:{value.document_id}" if value.document_id else "knowledge:search",
              {"method": result["method"], "reason": result.get("reason"),
               "source_count": len(result["sources"])})
        db.commit()
        return result

    return router
