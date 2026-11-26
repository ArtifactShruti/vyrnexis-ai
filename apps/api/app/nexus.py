"""Persistent local investigation pipelines and leased worker execution."""
from datetime import timedelta
import json
import logging
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .detection import HEARTBEAT_KEY, notify_worker, redis_client
from .forensics import (
    Input, Label, Purpose, READERS, WRITERS, append_custody, canonical, checksum,
    custody_chain, lock_case, owned_case, stamp,
)
from .models import (
    AgentExecution, AuditLog, CustodyEnrollment, Incident, InvestigationAttempt, InvestigationDependency,
    InvestigationReplay, InvestigationRun, InvestigationTask, Organization, User, utc_now_naive, uuid_value,
)


logger = logging.getLogger(__name__)
ACTIVE_RUN = {"queued", "running"}
TERMINAL_TASK = {"completed", "failed", "timed_out", "cancelled"}
MAX_ATTEMPTS = 3
LEASE_SECONDS = 45
DEPENDENCIES = {
    "SENTINEL": (), "MERCURY": (), "TRACE": (), "ORACLE": (),
    "VERITAS": ("SENTINEL", "MERCURY", "TRACE"),
    "AEGIS": ("VERITAS",),
    "NEXUS": ("SENTINEL", "MERCURY", "TRACE", "ORACLE", "VERITAS", "AEGIS"),
}


def validate_dependencies(graph):
    completed, active = set(), set()

    def visit(agent):
        if agent in active or agent not in graph:
            raise ValueError("Dependency graph contains a cycle or unknown task")
        if agent in completed:
            return
        active.add(agent)
        for target in graph[agent]:
            visit(target)
        active.remove(agent)
        completed.add(agent)

    for agent in graph:
        visit(agent)


validate_dependencies(DEPENDENCIES)


AgentName = Literal["SENTINEL", "MERCURY", "TRACE", "ORACLE", "VERITAS", "AEGIS", "NEXUS"]


class SelectionInput(Input):
    request_key: Annotated[str, StringConstraints(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")]
    agents: Annotated[list[AgentName], Field(min_length=1, max_length=7)] | None = None


class PipelineInput(SelectionInput):
    case_id: Label | None = None
    incident_id: Label | None = None

    @model_validator(mode="after")
    def single_target(self):
        if bool(self.case_id) == bool(self.incident_id):
            raise ValueError("Choose exactly one case or incident")
        return self


class ReviewInput(Input):
    decision: Literal["approved", "rejected"]
    note: Purpose


def worker_mode():
    return os.getenv("VYRNEXIS_DETECTION_MODE", "inline") == "worker"


def audit_run(db, run, actor_id, action, details):
    db.add(AuditLog(organization_id=run.organization_id, actor_id=actor_id, action=action,
                    resource=f"investigation_run:{run.id}", details=canonical(details)))


def run_tasks(db, run_id):
    tasks = db.scalars(select(InvestigationTask).where(InvestigationTask.run_id == run_id)
                       .order_by(InvestigationTask.agent)).all()
    dependencies = db.execute(select(InvestigationDependency.task_id, InvestigationDependency.prerequisite_id)
                             .join(InvestigationTask, InvestigationTask.id == InvestigationDependency.task_id)
                             .where(InvestigationTask.run_id == run_id)).all()
    return tasks, dependencies


def schedule(db, run):
    db.flush()
    tasks, dependencies = run_tasks(db, run.id)
    states = {task.id: task.status for task in tasks}
    for task in tasks:
        prerequisites = [target for source, target in dependencies if source == task.id]
        if task.status == "waiting" and all(states.get(target) in TERMINAL_TASK for target in prerequisites):
            task.status = "queued"
    if all(task.status in TERMINAL_TASK for task in tasks):
        run.status = "awaiting_approval" if any(task.status == "completed" for task in tasks) else "failed"
        audit_run(db, run, None, "nexus.run.processed", {"status": run.status})
    run.updated_at = utc_now_naive()


def execution_plan(agents):
    planned = set(agents)
    remaining = list(planned)
    while remaining:
        needed = set(DEPENDENCIES[remaining.pop()]) - planned
        planned.update(needed)
        remaining.extend(needed)
    return {agent: requirements for agent, requirements in DEPENDENCIES.items() if agent in planned}


def make_run(db, user, payload, *, replay_of=None, full_replay_agents=None):
    # Serialize submissions from one tenant and reject reuse with changed scope.
    db.execute(update(Organization).where(Organization.id == user.organization_id).values(name=Organization.name))
    targets = sorted(set(payload.agents)) if payload.agents else None
    plan = execution_plan(targets or full_replay_agents or DEPENDENCIES)
    prior = db.scalar(select(InvestigationRun).where(
        InvestigationRun.organization_id == user.organization_id, InvestigationRun.request_key == payload.request_key,
    ))
    if prior:
        replay = db.get(InvestigationReplay, prior.id)
        tasks, _ = run_tasks(db, prior.id)
        if ((prior.case_id, prior.incident_id) != (payload.case_id, payload.incident_id)
                or (replay.source_run_id if replay else None) != replay_of
                or (replay is not None and json.loads(replay.target_agents_json) != targets)
                or {task.agent for task in tasks} != set(plan)):
            raise HTTPException(409, "Request key was already used for a different investigation")
        return prior, False
    if payload.case_id:
        owned_case(db, payload.case_id, user)
    elif not db.scalar(select(Incident.id).where(Incident.id == payload.incident_id,
                                                Incident.organization_id == user.organization_id)):
        raise HTTPException(404, "Incident not found")
    active = db.scalar(select(func.count()).select_from(InvestigationRun).where(
        InvestigationRun.organization_id == user.organization_id, InvestigationRun.status.in_(ACTIVE_RUN),
    ))
    if active >= 8:
        raise HTTPException(429, "This organization already has eight active investigations")
    run = InvestigationRun(organization_id=user.organization_id, requested_by=user.id, case_id=payload.case_id,
                           incident_id=payload.incident_id, request_key=payload.request_key)
    db.add(run)
    db.flush()
    tasks = {agent: InvestigationTask(run_id=run.id, agent=agent) for agent in plan}
    db.add_all(tasks.values())
    db.flush()
    for agent, requirements in plan.items():
        db.add_all(InvestigationDependency(task_id=tasks[agent].id, prerequisite_id=tasks[target].id)
                   for target in requirements)
    schedule(db, run)
    audit_run(db, run, user.id, "nexus.run.queued", {"case_id": run.case_id, "incident_id": run.incident_id})
    if replay_of:
        db.add(InvestigationReplay(run_id=run.id, source_run_id=replay_of, target_agents_json=canonical(targets)))
        audit_run(db, run, user.id, "nexus.run.replayed", {"source_run_id": replay_of, "target_agents": targets})
    return run, True


def locked_run(db, run_id, org=None):
    stmt = select(InvestigationRun).where(InvestigationRun.id == run_id)
    if org:
        stmt = stmt.where(InvestigationRun.organization_id == org)
    if db.get_bind().dialect.name == "sqlite":
        criteria = [InvestigationRun.id == run_id]
        if org:
            criteria.append(InvestigationRun.organization_id == org)
        db.execute(update(InvestigationRun).where(*criteria).values(updated_at=InvestigationRun.updated_at))
    return db.scalar(stmt.with_for_update())


def mark_failure(db, run, task, error, *, timed_out=False, terminal=False):
    attempt = db.get(InvestigationAttempt, (task.id, task.attempts))
    if attempt:
        attempt.status = "timed_out" if timed_out else "failed"
        attempt.finished_at, attempt.error = utc_now_naive(), error
    task.error, task.lease_until, task.lease_token = error, None, None
    if task.attempts >= MAX_ATTEMPTS or terminal:
        task.status = "timed_out" if timed_out else "failed"
    else:
        task.status = "queued"
        task.available_at = utc_now_naive() + timedelta(seconds=2 ** task.attempts)
    schedule(db, run)


def claim(run_id=None, session_factory=SessionLocal):
    now = utc_now_naive()
    with session_factory.begin() as db:
        eligible = or_(
            and_(InvestigationTask.status == "queued", InvestigationTask.available_at <= now),
            and_(InvestigationTask.status == "running", InvestigationTask.lease_until <= now),
        )
        stmt = select(InvestigationTask.id, InvestigationTask.run_id).join(
            InvestigationRun, InvestigationRun.id == InvestigationTask.run_id,
        ).where(eligible, InvestigationRun.status.in_(ACTIVE_RUN))
        if run_id:
            stmt = stmt.where(InvestigationRun.id == run_id)
        candidates = db.execute(stmt.order_by(InvestigationTask.available_at, InvestigationTask.id).limit(10)).all()
        for task_id, candidate_run_id in candidates:
            run = locked_run(db, candidate_run_id)
            if run is None or run.status not in ACTIVE_RUN:
                continue
            task = db.scalar(select(InvestigationTask).where(InvestigationTask.id == task_id, eligible).with_for_update())
            if not task:
                continue
            if task.status == "running":
                mark_failure(db, run, task, "The worker lease expired", timed_out=True)
                return True
            token = uuid_value()
            task.status, task.lease_token = "running", token
            task.lease_until, task.attempts = now + timedelta(seconds=LEASE_SECONDS), task.attempts + 1
            run.status, run.updated_at = "running", now
            db.add(InvestigationAttempt(task_id=task.id, number=task.attempts, status="running", started_at=now))
            return (run.id, task.id, token)
    return False


def still_authorized(db, run):
    actor = db.get(User, run.requested_by)
    return actor and actor.organization_id == run.organization_id and actor.is_active and actor.role in READERS


def record_evidence_access(session_factory, run_id, task_id, token, evidence):
    # Commit an access record before reading bytes, so interrupted attempts remain auditable.
    with session_factory.begin() as db:
        run = locked_run(db, run_id)
        task = db.get(InvestigationTask, task_id)
        if (run.status not in ACTIVE_RUN or task.status != "running" or task.lease_token != token
                or utc_now_naive() >= task.lease_until or not still_authorized(db, run)):
            raise HTTPException(409, "The investigation task no longer has an active lease")
        item = db.get(CustodyEnrollment, evidence.id)
        if item is None:
            audit_run(db, run, run.requested_by, "nexus.evidence.accessed", {"evidence_id": evidence.id})
            return
        actor = db.get(User, run.requested_by)
        if item.case_id != run.case_id or actor.role not in WRITERS:
            raise HTTPException(403, "Evidence access requires the registered case and a forensic writer")
        case = lock_case(db, item.case_id, actor, allow_closed=True)
        db.refresh(item)
        if item.archived or not custody_chain(db, item, evidence)[0]:
            raise HTTPException(409, "The custody ledger is unavailable for examination")
        append_custody(db, item, evidence, actor, "examined", f"VERITAS investigation {run.id}", item.custodian_id)
        db.add(AuditLog(
            organization_id=run.organization_id, actor_id=actor.id, action="forensic.custody.examined",
            resource=f"forensic_case:{case.id}", details=canonical({
                "evidence_id": evidence.id, "sequence": item.last_sequence, "investigation_id": run.id,
            }),
        ))


def execute_one(read_bytes, hash_matches, run_id=None, session_factory=SessionLocal):
    job = claim(run_id, session_factory)
    if isinstance(job, bool):
        return job
    perform_claim(job, read_bytes, hash_matches, session_factory)
    return True


def fail_claim(job, error, *, timed_out=False, session_factory=SessionLocal):
    run_id, task_id, token = job
    with session_factory.begin() as db:
        run = locked_run(db, run_id)
        task = db.get(InvestigationTask, task_id)
        if run.status in ACTIVE_RUN and task.status == "running" and task.lease_token == token:
            mark_failure(db, run, task, error, timed_out=timed_out)


def perform_claim(job, read_bytes, hash_matches, session_factory=SessionLocal):
    from .nexus_analysis import analyze

    run_id, task_id, token = job
    result, error, revoked = None, None, False

    def forensic_read(evidence):
        record_evidence_access(session_factory, run_id, task_id, token, evidence)
        return read_bytes(evidence)

    try:
        with session_factory() as db:
            run, task = db.get(InvestigationRun, run_id), db.get(InvestigationTask, task_id)
            if run.status not in ACTIVE_RUN or task.status != "running" or task.lease_token != token:
                return
            if still_authorized(db, run):
                if db.bind.dialect.name == "postgresql":
                    from sqlalchemy import text

                    db.execute(text("SET LOCAL statement_timeout = 10000"))
                result = analyze(db, run, task, forensic_read, hash_matches)
            else:
                error, revoked = "The requester no longer has investigation access", True
    except Exception:
        logger.warning("Investigation task failed during bounded analysis")
        error = "The deterministic analysis failed"
    with session_factory.begin() as db:
        run = locked_run(db, run_id)
        task = db.get(InvestigationTask, task_id)
        if run.status not in ACTIVE_RUN or task.status != "running" or task.lease_token != token:
            return
        if utc_now_naive() >= task.lease_until:
            mark_failure(db, run, task, "The task exceeded its execution lease", timed_out=True)
        elif error or not still_authorized(db, run):
            mark_failure(db, run, task, error or "The requester no longer has investigation access",
                         terminal=revoked or error is None)
        else:
            task.status, task.result_json, task.error = "completed", canonical(result), None
            task.lease_token = task.lease_until = None
            attempt = db.get(InvestigationAttempt, (task.id, task.attempts))
            attempt.status, attempt.finished_at = "completed", utc_now_naive()
            summary = {
                "agent": task.agent, "finding": result["claim"], "evidence": result["sources"],
                "confidence": None, "alternatives": result["alternative_explanations"],
                "recommended_action": "Review the supporting records with an authorized analyst.",
                "requires_approval": True, "limitations": result["limitations"],
            }
            db.add(AgentExecution(organization_id=run.organization_id, actor_id=run.requested_by,
                                  agent_name=task.agent, task_type="investigation_nexus",
                                  input_data=canonical({"run_id": run.id, "task_id": task.id}), output_data=canonical(summary)))
            audit_run(db, run, run.requested_by, "nexus.task.completed", {"task_id": task.id, "agent": task.agent})
            schedule(db, run)


def owned_run(db, run_id, user, *, lock=False):
    if lock:
        run = locked_run(db, run_id, user.organization_id)
    else:
        run = db.scalar(select(InvestigationRun).where(InvestigationRun.id == run_id,
                                                       InvestigationRun.organization_id == user.organization_id))
    if run is None:
        raise HTTPException(404, "Investigation run not found")
    return run


def run_record(run):
    return {"id": run.id, "status": run.status, "case_id": run.case_id, "incident_id": run.incident_id,
            "requested_by": run.requested_by, "reviewer_id": run.reviewer_id, "review_note": run.review_note,
            "created_at": stamp(run.created_at), "updated_at": stamp(run.updated_at)}


def full_record(db, run):
    tasks, links = run_tasks(db, run.id)
    ids = [task.id for task in tasks]
    attempts = db.scalars(select(InvestigationAttempt).where(InvestigationAttempt.task_id.in_(ids))
                         .order_by(InvestigationAttempt.number)).all()
    replay = db.get(InvestigationReplay, run.id)
    lineage = {"source_run_id": replay.source_run_id, "target_agents": json.loads(replay.target_agents_json)} if replay else None
    return run_record(run) | {"replay": lineage, "tasks": [{
        "id": task.id, "agent": task.agent, "status": task.status, "attempts": task.attempts, "error": task.error,
        "result": json.loads(task.result_json) if task.result_json else None,
        "dependencies": [target for source, target in links if source == task.id],
        "history": [{"number": item.number, "status": item.status, "started_at": stamp(item.started_at),
                     "finished_at": stamp(item.finished_at) if item.finished_at else None, "error": item.error}
                    for item in attempts if item.task_id == task.id],
    } for task in tasks]}


def build_nexus_router(require_roles, read_bytes, hash_matches):
    router = APIRouter(prefix="/api/v1/investigations")
    analyst = Depends(require_roles(*READERS))
    reviewer = Depends(require_roles(*WRITERS))

    @router.get("/worker")
    def worker_status(user: User = analyst):
        if not worker_mode():
            return {"mode": "inline", "worker_available": None}
        client = redis_client()
        available = False
        if client:
            from redis import RedisError

            try:
                available = bool(client.exists(HEARTBEAT_KEY))
            except RedisError:
                pass
            finally:
                client.close()
        return {"mode": "worker", "worker_available": available}

    @router.get("")
    def list_runs(limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), user: User = analyst):
        rows = db.scalars(select(InvestigationRun).where(InvestigationRun.organization_id == user.organization_id)
                          .order_by(InvestigationRun.created_at.desc()).limit(limit))
        return [run_record(item) for item in rows]

    def dispatch(db, user, run, new):
        run_id = run.id
        active = run.status in ACTIVE_RUN
        db.commit()
        if worker_mode():
            if new:
                notify_worker()
        elif active:
            # Keep fixture, SQLite, and PostgreSQL session ownership separate.
            from sqlalchemy.orm import sessionmaker

            factory = sessionmaker(bind=db.get_bind(), autoflush=False)
            for _ in range(len(DEPENDENCIES)):
                if not execute_one(read_bytes, hash_matches, run_id, factory):
                    break
        db.expire_all()
        return full_record(db, owned_run(db, run_id, user))

    @router.post("", status_code=201)
    def start(payload: PipelineInput, db: Session = Depends(get_db), user: User = analyst):
        run, new = make_run(db, user, payload)
        return dispatch(db, user, run, new)

    @router.post("/{run_id}/replay", status_code=201)
    def replay(run_id: str, payload: SelectionInput, db: Session = Depends(get_db), user: User = reviewer):
        original = owned_run(db, run_id, user)
        tasks, _ = run_tasks(db, original.id)
        failed = {task.agent for task in tasks if task.status in {"failed", "timed_out"}}
        if original.status not in {"failed", "awaiting_approval", "approved", "rejected"} or not failed:
            raise HTTPException(409, "Only finished investigations with failed or timed-out tasks can be replayed")
        if payload.agents and not set(payload.agents).issubset(failed):
            raise HTTPException(422, "Select failed or timed-out tasks from the original run")
        selection = PipelineInput(case_id=original.case_id, incident_id=original.incident_id, **payload.model_dump())
        run, new = make_run(db, user, selection, replay_of=original.id, full_replay_agents={task.agent for task in tasks})
        return dispatch(db, user, run, new)

    @router.get("/{run_id}")
    def inspect(run_id: str, db: Session = Depends(get_db), user: User = analyst):
        return full_record(db, owned_run(db, run_id, user))

    @router.post("/{run_id}/cancel")
    def cancel(run_id: str, db: Session = Depends(get_db), user: User = analyst):
        run = owned_run(db, run_id, user, lock=True)
        if run.requested_by != user.id and user.role not in WRITERS:
            raise HTTPException(403, "Only the requester or a forensic reviewer can cancel this run")
        if run.status not in ACTIVE_RUN:
            raise HTTPException(409, "The run can no longer be cancelled")
        run.status, run.updated_at = "cancelled", utc_now_naive()
        tasks, _ = run_tasks(db, run.id)
        for task in tasks:
            if task.status == "running":
                attempt = db.get(InvestigationAttempt, (task.id, task.attempts))
                if attempt:
                    attempt.status, attempt.finished_at = "cancelled", utc_now_naive()
            if task.status not in TERMINAL_TASK:
                task.status, task.lease_token, task.lease_until = "cancelled", None, None
        audit_run(db, run, user.id, "nexus.run.cancelled", {})
        db.commit()
        return full_record(db, run)

    @router.post("/{run_id}/review")
    def review(run_id: str, payload: ReviewInput, db: Session = Depends(get_db), user: User = reviewer):
        run = owned_run(db, run_id, user, lock=True)
        if run.status != "awaiting_approval":
            raise HTTPException(409, "The run is not awaiting human review")
        run.status, run.reviewer_id, run.review_note, run.updated_at = (
            payload.decision, user.id, payload.note, utc_now_naive(),
        )
        audit_run(db, run, user.id, "nexus.run.reviewed", payload.model_dump())
        db.commit()
        return full_record(db, run)

    @router.get("/{run_id}/report")
    def report(run_id: str, db: Session = Depends(get_db), user: User = analyst):
        run = owned_run(db, run_id, user)
        if run.status not in {"awaiting_approval", "approved", "rejected"}:
            raise HTTPException(409, "An investigation report requires completed processing")
        snapshot = full_record(db, run)
        audit_run(db, run, user.id, "nexus.run.exported", {"status": run.status})
        db.commit()
        return Response(canonical({"snapshot": snapshot, "sha256": checksum(snapshot)}),
                        media_type="application/json", headers={
                            "Content-Disposition": f"attachment; filename=investigation-{run.id}.json",
                            "Cache-Control": "private, no-store",
                        })

    return router
