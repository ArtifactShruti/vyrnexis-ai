"""Cited, account-owned conversations with explicit optional model execution."""
import asyncio
from contextlib import suppress
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import sessionmaker

from .ai_gateway import generate_cited, lock_organization
from .database import get_db
from .forensics import READERS, owned_case
from .knowledge import resolve_documents, retrieve, terms_for
from .semantic import hybrid_search
from .models import (
    CommerceFinding, CopilotConversation, CopilotTurn, CustodyEnrollment, CustodyEvent, DetectionAlert,
    DetectionAlertEvent, Evidence, ForensicCaseLink, ForensicNote, ForensicReport, Incident, IntelligenceEntity,
    InvestigationRun, InvestigationTask, SecurityEvent, User, utc_now_naive,
)
from .provider_stream import native_stream


Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
RequestKey = Annotated[str, StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Label
    case_id: Label | None = None
    incident_id: Label | None = None

    @model_validator(mode="after")
    def one_scope(self):
        if self.case_id and self.incident_id:
            raise ValueError("Select at most one investigation context")
        return self


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]
    request_key: RequestKey
    mode: Literal["record_search", "model_assisted"] = "record_search"
    acknowledge_model_context: bool = False


def incident_for(db, user, incident_id):
    incident = db.scalar(select(Incident).where(
        Incident.organization_id == user.organization_id, Incident.id == incident_id,
    ))
    if incident is None:
        raise HTTPException(404, "Incident context is unavailable")
    return incident


def validate_scope(db, user, case_id, incident_id):
    if case_id:
        if user.role not in READERS:
            raise HTTPException(403, "This role cannot use forensic case context")
        owned_case(db, case_id, user)
    if incident_id:
        incident_for(db, user, incident_id)


def owned_conversation(db, user, conversation_id):
    row = db.scalar(select(CopilotConversation).where(
        CopilotConversation.id == conversation_id, CopilotConversation.organization_id == user.organization_id,
        CopilotConversation.owner_id == user.id,
    ))
    if row is None:
        raise HTTPException(404, "Conversation is unavailable")
    return row


def conversation_record(row):
    return {"id": row.id, "title": row.title, "case_id": row.case_id, "incident_id": row.incident_id,
            "updated_at": row.updated_at.isoformat() + "Z"}


def source(key, kind, title, text, link):
    return {"key": key, "kind": kind, "title": title, "excerpt": text[:900], "href": link}


def saved_findings(db, user, case_id=None, incident_id=None):
    if user.role not in READERS:
        return []
    target = InvestigationRun.case_id == case_id if case_id else InvestigationRun.incident_id == incident_id
    run = db.scalar(select(InvestigationRun).where(
        InvestigationRun.organization_id == user.organization_id, target,
        InvestigationRun.status.in_(("awaiting_approval", "approved")),
    ).order_by(InvestigationRun.created_at.desc()).limit(1))
    if not run:
        return []
    tasks = db.scalars(select(InvestigationTask).where(InvestigationTask.run_id == run.id,
                                                       InvestigationTask.result_json.is_not(None)).limit(7))
    return [source(f"task:{item.id}", "agent_finding", f"{item.agent} investigation finding",
                   f"Run status {run.status}. " + json.loads(item.result_json)["claim"], "/platform/nexus")
            for item in tasks]


def case_sources(db, user, case, link):
    org = user.organization_id
    ledgers = db.execute(select(CustodyEnrollment, Evidence, CustodyEvent).select_from(CustodyEnrollment)
        .join(Evidence, Evidence.id == CustodyEnrollment.evidence_id)
        .join(CustodyEvent, (CustodyEvent.evidence_id == CustodyEnrollment.evidence_id)
              & (CustodyEvent.sequence == CustodyEnrollment.last_sequence))
        .where(CustodyEnrollment.case_id == case.id, CustodyEnrollment.organization_id == org,
               Evidence.organization_id == org, CustodyEvent.organization_id == org, CustodyEvent.case_id == case.id)
        .order_by(CustodyEvent.created_at.desc()).limit(6)).all()
    result = [source(f"custody:{file.id}:{event.sequence}", "custody", f"Evidence custody · {file.name}",
                     f"Recorded action {event.action}. {event.purpose} SHA-256 {file.sha256}. "
                     f"Archived {enrollment.archived}.", link) for enrollment, file, event in ledgers]
    reports = db.scalars(select(ForensicReport).where(ForensicReport.case_id == case.id,
        ForensicReport.organization_id == org).order_by(ForensicReport.version.desc()).limit(3))
    result.extend(source(f"report:{item.id}", "forensic_report", f"Forensic report version {item.version}",
                         f"Snapshot SHA-256 {item.integrity_hash}. Generated {item.created_at.isoformat()} UTC.",
                         f"/api/forensic/forensic-cases/{case.id}/reports/{item.id}/json") for item in reports)
    for kind, model in (("finding", CommerceFinding), ("entity", IntelligenceEntity), ("incident", Incident)):
        records = db.scalars(select(model).join(ForensicCaseLink, ForensicCaseLink.object_id == model.id).where(
            ForensicCaseLink.case_id == case.id, ForensicCaseLink.kind == kind,
            model.organization_id == org,
        ).order_by(ForensicCaseLink.created_at.desc()).limit(5))
        for item in records:
            if kind == "finding":
                result.append(commerce_source(item))
            elif kind == "entity":
                result.append(source(f"entity:{item.id}", "entity", item.display_name,
                                     f"Recorded entity category {item.entity_type}.", f"/platform/graph?focus={item.id}"))
            else:
                result.append(incident_source(item))
    return result + saved_findings(db, user, case_id=case.id)


def scoped_sources(db, user, conversation):
    if conversation.case_id:
        validate_scope(db, user, conversation.case_id, None)
        case = owned_case(db, conversation.case_id, user)
        link = f"/platform/forensics?case={case.id}"
        result = [source(f"case:{case.id}", "case", case.title, f"{case.status}. {case.description}", link)]
        latest = select(ForensicNote.note_id, func.max(ForensicNote.revision).label("revision")).where(
            ForensicNote.case_id == case.id,
        ).group_by(ForensicNote.note_id).subquery()
        notes = db.scalars(select(ForensicNote).join(latest, (latest.c.note_id == ForensicNote.note_id)
                          & (latest.c.revision == ForensicNote.revision))
                          .order_by(ForensicNote.created_at.desc(), ForensicNote.note_id).limit(10))
        result.extend(source(f"note:{note.note_id}:{note.revision}", "note", f"Case note · {note.category}", note.body, link)
                      for note in notes)
        return result + case_sources(db, user, case, link)
    if conversation.incident_id:
        row = incident_for(db, user, conversation.incident_id)
        org = user.organization_id
        events = db.scalars(select(SecurityEvent).join(DetectionAlertEvent, DetectionAlertEvent.event_id == SecurityEvent.id)
            .join(DetectionAlert, DetectionAlert.id == DetectionAlertEvent.alert_id).where(
                DetectionAlert.incident_id == row.id, DetectionAlert.organization_id == org, SecurityEvent.organization_id == org,
            ).order_by(SecurityEvent.occurred_at.desc()).limit(6))
        findings = db.scalars(select(CommerceFinding).where(
            CommerceFinding.organization_id == org, CommerceFinding.incident_id == row.id,
        ).order_by(CommerceFinding.created_at.desc()).limit(4))
        return ([incident_source(row)] + [event_source(item) for item in events]
                + [commerce_source(item) for item in findings] + saved_findings(db, user, incident_id=row.id))
    return []


def incident_source(row):
    return source(f"incident:{row.id}", "incident", row.title,
                  f"{row.severity} severity. {row.status}. {row.description}", f"/platform/incidents?id={row.id}")


def event_source(row):
    return source(f"event:{row.id}", "security_event", row.title,
                  f"{row.event_type}. {row.severity} severity. {row.description}", "/platform/security")


def commerce_source(row):
    report = json.loads(row.report)
    factors = " ".join(item["detail"] for item in report.get("factors", [])[:8])
    return source(f"finding:{row.id}", "commerce_finding", "Recorded refund finding",
                  f"Rule weight {row.score}/100. Review status {row.status}. {factors}", f"/platform/fraud?finding={row.id}")


def match_records(db, user, query):
    terms = terms_for(query)
    if not terms:
        return []
    results = []
    for model, serializer, timestamp in ((Incident, incident_source, Incident.created_at),
                                          (SecurityEvent, event_source, SecurityEvent.occurred_at)):
        matching = [func.lower(field).contains(term, autoescape=True) for term in terms
                    for field in (model.title, model.description)]
        rows = db.scalars(select(model).where(model.organization_id == user.organization_id, or_(*matching))
                         .order_by(timestamp.desc(), model.id).limit(4))
        results.extend(serializer(row) for row in rows)
    return results


def answer_sources(db, user, conversation, query, audit=None):
    scope = scoped_sources(db, user, conversation)
    terms = terms_for(query)
    prioritized = scope[:1] + [
        item for item in scope[1:] if any(term in (item["title"] + " " + item["excerpt"]).casefold() for term in terms)
    ][:4]
    global_matches = [] if scope else match_records(db, user, query)
    hybrid = hybrid_search(db, user, query, None)
    if audit:
        audit(db, user.organization_id, user.id, "knowledge.retrieval",
              "copilot:search", {
                  "method": hybrid["method"],
                  "reason": hybrid.get("reason"),
                  "source_count": len(hybrid["sources"]),
              })
    combined = []
    seen = set()
    for item in prioritized + hybrid["sources"] + global_matches:
        key = item["key"]
        if key not in seen:
            seen.add(key)
            combined.append(item)
    return combined[:12]


def resolve_sources(db, user, conversation, keys):
    resolved = resolve_documents(db, user, keys)
    try:
        resolved.update({item["key"]: item for item in scoped_sources(db, user, conversation)})
    except HTTPException:
        pass
    if not conversation.case_id and not conversation.incident_id:
        for prefix, model, serializer in (("incident:", Incident, incident_source), ("event:", SecurityEvent, event_source)):
            ids = [key.removeprefix(prefix) for key in keys if key.startswith(prefix)]
            if ids:
                rows = db.scalars(select(model).where(model.id.in_(ids), model.organization_id == user.organization_id))
                resolved.update((item["key"], item) for item in map(serializer, rows))
    return [resolved[key] for key in keys if key in resolved]


def turn_record(db, user, conversation, turn):
    keys = json.loads(turn.sources_json)
    citations = resolve_sources(db, user, conversation, keys) if keys else []
    answer = turn.answer
    if len(keys) != len(citations):
        answer = "Some original sources are unavailable. Run a new search for current evidence."
    mode = "record_search" if turn.status == "completed" and not turn.model_json else turn.mode
    return {"id": turn.id, "request_key": turn.request_key, "question": turn.question, "mode": mode,
            "status": turn.status, "answer": answer, "sources": citations,
            "model": json.loads(turn.model_json) if turn.model_json else None,
            "created_at": turn.created_at.isoformat() + "Z"}


async def model_until_cancelled(db, actor, conversation, turn_id, value, sources, on_partial=None):
    factory = sessionmaker(bind=db.get_bind())

    def load_sources():
        state = db.scalar(select(CopilotTurn.status).where(CopilotTurn.id == turn_id))
        if state != "running":
            raise HTTPException(409, "This question is no longer running")
        validate_scope(db, actor, conversation.case_id, conversation.incident_id)
        allowed = resolve_sources(db, actor, conversation, [item["key"] for item in sources])
        return [{"key": item["key"], "title": item["title"], "excerpt": item["excerpt"]} for item in allowed]

    async def stream(connection, model, **options):
        return await native_stream(connection, model, on_partial=on_partial, **options)

    task = asyncio.create_task(generate_cited(db, actor, value.text, load_sources, value.acknowledge_model_context,
                                               gateway_call=stream if on_partial else None))
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.5)
            if task.done():
                break
            with factory() as check:
                state = check.scalar(select(CopilotTurn.status).where(CopilotTurn.id == turn_id))
            if state != "running":
                return None
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def build_copilot_router(current_user, audit):
    router = APIRouter(prefix="/api/v1/copilot")
    reader = Depends(current_user)

    @router.get("/conversations")
    def list_conversations(query: str = Query("", max_length=120), db=Depends(get_db), user=reader):
        stmt = select(CopilotConversation).where(
            CopilotConversation.organization_id == user.organization_id, CopilotConversation.owner_id == user.id,
        )
        if query:
            stmt = stmt.where(func.lower(CopilotConversation.title).contains(query.casefold(), autoescape=True))
        return [conversation_record(row) for row in db.scalars(stmt.order_by(CopilotConversation.updated_at.desc()).limit(100))]

    @router.post("/conversations", status_code=201)
    def create(value: ConversationInput, db=Depends(get_db), user=reader):
        validate_scope(db, user, value.case_id, value.incident_id)
        lock_organization(db, user.organization_id)
        count = db.scalar(select(func.count()).select_from(CopilotConversation).where(CopilotConversation.owner_id == user.id))
        if count >= 100:
            raise HTTPException(429, "This account reached its conversation limit")
        row = CopilotConversation(organization_id=user.organization_id, owner_id=user.id, **value.model_dump())
        db.add(row)
        db.flush()
        audit(db, user.organization_id, user.id, "copilot.conversation.created", f"copilot:{row.id}", {})
        db.commit()
        return conversation_record(row)

    @router.get("/conversations/{conversation_id}")
    def inspect(conversation_id: str, db=Depends(get_db), user=reader):
        row = owned_conversation(db, user, conversation_id)
        turns = db.scalars(select(CopilotTurn).where(CopilotTurn.conversation_id == row.id)
                           .order_by(CopilotTurn.created_at, CopilotTurn.id).limit(100)).all()
        return conversation_record(row) | {"turns": [turn_record(db, user, row, turn) for turn in turns]}

    @router.delete("/conversations/{conversation_id}", status_code=204)
    def remove(conversation_id: str, db=Depends(get_db), user=reader):
        lock_organization(db, user.organization_id)
        row = owned_conversation(db, user, conversation_id)
        db.execute(delete(CopilotTurn).where(CopilotTurn.conversation_id == row.id))
        db.delete(row)
        audit(db, user.organization_id, user.id, "copilot.conversation.deleted", f"copilot:{conversation_id}", {})
        db.commit()

    @router.get("/conversations/{conversation_id}/export")
    def export(conversation_id: str, db=Depends(get_db), user=reader):
        report = inspect(conversation_id, db, user)
        audit(db, user.organization_id, user.id, "copilot.conversation.exported", f"copilot:{conversation_id}", {})
        db.commit()
        return Response(json.dumps(report, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename=copilot-{conversation_id}.json",
                                 "Cache-Control": "private, no-store"})

    async def process_question(conversation_id, value, db, user, on_partial=None):
        if value.mode == "model_assisted" and not value.acknowledge_model_context:
            raise HTTPException(403, "Confirm sharing the question and selected sources with the configured model")
        lock_organization(db, user.organization_id)
        row = owned_conversation(db, user, conversation_id)
        validate_scope(db, user, row.case_id, row.incident_id)
        prior = db.scalar(select(CopilotTurn).where(
            CopilotTurn.conversation_id == row.id, CopilotTurn.request_key == value.request_key,
        ))
        if prior:
            if (prior.question, prior.mode) != (value.text, value.mode):
                raise HTTPException(409, "Request key was already used for a different question")
            return turn_record(db, user, row, prior)
        count = db.scalar(select(func.count()).select_from(CopilotTurn).where(CopilotTurn.conversation_id == row.id))
        if count >= 100:
            raise HTTPException(429, "This conversation reached its turn limit")
        db.add(turn := CopilotTurn(conversation_id=row.id, request_key=value.request_key,
                                  question=value.text, mode=value.mode, status="running"))
        row.updated_at = utc_now_naive()
        sources = answer_sources(db, user, row, value.text, audit)
        keys = [item["key"] for item in sources]
        db.flush()
        turn_id = turn.id
        db.commit()
        answer = "No matching authorized records were found. Try a specific term or select an investigation."
        model = None
        state = "completed"
        stored_mode = value.mode
        if not sources:
            stored_mode = "record_search"
        elif value.mode == "record_search":
            answer = "Matching authorized record excerpts are shown in Sources."
        else:
            try:
                completed = await model_until_cancelled(db, user, row, turn_id, value, sources, on_partial)
                if completed is None:
                    state, answer, keys = "cancelled", None, []
                else:
                    result, model = completed
                    answer, keys = result.answer, list(dict.fromkeys(result.citations))
            except HTTPException as exc:
                state, answer = "failed", exc.detail
            except asyncio.CancelledError:
                db.execute(update(CopilotTurn).where(CopilotTurn.id == turn_id, CopilotTurn.status == "running")
                           .values(status="cancelled"))
                db.commit()
                raise
        lock_organization(db, user.organization_id)
        row = owned_conversation(db, user, conversation_id)
        changed = db.execute(update(CopilotTurn).where(CopilotTurn.id == turn_id, CopilotTurn.status == "running").values(
            status=state, answer=answer, sources_json=json.dumps(keys), model_json=json.dumps(model) if model else None,
        )).rowcount
        if changed:
            audit(db, user.organization_id, user.id, "copilot.turn.finished", f"copilot:{row.id}",
                  {"status": state, "mode": stored_mode, "source_count": len(keys)})
        db.commit()
        return turn_record(db, user, row, db.get(CopilotTurn, turn_id, populate_existing=True))

    @router.post("/conversations/{conversation_id}/turns")
    async def ask(conversation_id: str, value: Question, db=Depends(get_db), user=reader):
        return await process_question(conversation_id, value, db, user)

    @router.post("/conversations/{conversation_id}/stream")
    def stream_question(conversation_id: str, value: Question, db=Depends(get_db), user=reader):
        owned_conversation(db, user, conversation_id)
        if value.mode != "model_assisted" or not value.acknowledge_model_context:
            raise HTTPException(403, "Live generation requires model assistance and context acknowledgement")
        factory = sessionmaker(bind=db.get_bind(), autoflush=False)
        user_id, org = user.id, user.organization_id

        async def events():
            queue = asyncio.Queue(maxsize=12)

            async def partial(text):
                await queue.put(("partial", {"text": text}))

            async def produce():
                with factory() as session:
                    actor = session.get(User, user_id)
                    if not actor or not actor.is_active or actor.organization_id != org:
                        await queue.put(("error", {"detail": "Conversation access is unavailable"}))
                        return
                    try:
                        value_out = await process_question(conversation_id, value, session, actor, partial)
                        await queue.put(("done", value_out))
                    except HTTPException as exc:
                        await queue.put(("error", {"detail": str(exc.detail)}))
                    except Exception:
                        await queue.put(("error", {"detail": "Model streaming failed"}))

            producer = asyncio.create_task(produce())
            try:
                yield 'event: ready\ndata: {}\n\n'
                while True:
                    try:
                        event, data = await asyncio.wait_for(queue.get(), timeout=8)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                    if event in {"done", "error"}:
                        break
            finally:
                if not producer.done():
                    producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})

    @router.post("/conversations/{conversation_id}/cancel/{request_key}")
    def stop(conversation_id: str, request_key: RequestKey, db=Depends(get_db), user=reader):
        lock_organization(db, user.organization_id)
        row = owned_conversation(db, user, conversation_id)
        changed = db.execute(update(CopilotTurn).where(CopilotTurn.conversation_id == row.id,
            CopilotTurn.request_key == request_key, CopilotTurn.status == "running",
        ).values(status="cancelled")).rowcount
        if not changed:
            raise HTTPException(409, "There is no running request with this key")
        audit(db, user.organization_id, user.id, "copilot.turn.cancelled", f"copilot:{row.id}", {})
        db.commit()
        return {"status": "cancelled"}

    return router
