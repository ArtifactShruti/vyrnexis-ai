"""Authenticated drafts, publication, durable executions, and human decisions."""
from datetime import timedelta
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from .ai_gateway import lock_organization
from .database import get_db
from .detection import notify_worker
from .forensics import Input, Purpose, canonical, stamp
from .models import Workflow, WorkflowApproval, WorkflowExecution, WorkflowStep, WorkflowStudio, WorkflowVersion, utc_now_naive
from .nexus import worker_mode
from .workflow_engine import (
    ACTIVE, EDITORS, REVIEWERS, TEMPLATES, Facts, Graph, Title, advance_one, enqueue,
    graph_order, lock_execution, record_event, terminate,
)


RequestKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,100}$")]


class Create(Input):
    name: Title
    template: Literal["incident", "refund", "custody", "agent", "summary", "security-event", "fraud-event"] | None = None


class Revision(Input):
    revision: int = Field(ge=1)


class Draft(Revision):
    name: Title
    graph: Graph


class Lifecycle(Revision):
    state: Literal["paused", "published", "archived"]


class Start(Input):
    request_key: RequestKey
    facts: Facts = Field(default_factory=dict)
    dry_run: bool = True


class Replay(Input):
    request_key: RequestKey


class Decision(Input):
    decision: Literal["approved", "rejected"]
    note: Purpose


def checked_graph(graph):
    try:
        order, _ = graph_order(graph)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return order[0]


def definition_record(workflow, studio):
    return {"id": workflow.id, "name": workflow.name, "state": studio.lifecycle, "revision": studio.revision,
            "published_version": studio.published_version, "next_due": stamp(studio.next_due) if studio.next_due else None,
            "updated_at": stamp(studio.updated_at)}


def execution_record(row):
    return {"id": row.id, "workflow_id": row.workflow_id, "parent_id": row.parent_id, "version": row.version,
            "mode": row.mode, "status": row.status, "error": row.error, "created_at": stamp(row.created_at),
            "deadline_at": stamp(row.deadline_at), "finished_at": stamp(row.finished_at) if row.finished_at else None}


def execution_detail(db, row):
    steps = db.scalars(select(WorkflowStep).where(WorkflowStep.execution_id == row.id)
                       .order_by(WorkflowStep.started_at, WorkflowStep.node_id)).all()
    approvals = db.scalars(select(WorkflowApproval).where(WorkflowApproval.execution_id == row.id)).all()
    return execution_record(row) | {
        "graph": json.loads(row.definition_json),
        "steps": [{"node_id": step.node_id, "status": step.status, "attempt": step.attempt, "error": step.error,
                   "output": json.loads(step.output_json) if step.output_json else None,
                   "started_at": stamp(step.started_at) if step.started_at else None,
                   "finished_at": stamp(step.finished_at) if step.finished_at else None} for step in steps],
        "approvals": [{"node_id": item.node_id, "status": item.status, "note": item.note,
                       "decided_at": stamp(item.decided_at) if item.decided_at else None} for item in approvals],
    }


def build_workflow_router(require_roles, audit):
    router = APIRouter(prefix="/api/v1/workflow-studio")
    editor = Depends(require_roles(*EDITORS))
    reviewer = Depends(require_roles(*REVIEWERS))
    reader = Depends(require_roles(*set(EDITORS + REVIEWERS)))

    def owned(db, user, workflow_id, revision=None):
        result = db.execute(select(Workflow, WorkflowStudio).join(
            WorkflowStudio, WorkflowStudio.workflow_id == Workflow.id,
        ).where(Workflow.id == workflow_id, Workflow.organization_id == user.organization_id)).first()
        if result is None:
            raise HTTPException(404, "Workflow is unavailable")
        workflow, studio = result
        if revision is not None and studio.revision != revision:
            raise HTTPException(409, "The workflow changed. Refresh before editing.")
        return workflow, studio

    def change(db, workflow, studio, user, event):
        studio.revision += 1
        studio.updated_at = utc_now_naive()
        audit(db, user.organization_id, user.id, f"workflow.{event}", f"workflow:{workflow.id}",
              {"revision": studio.revision, "state": studio.lifecycle})
        db.commit()
        return definition_record(workflow, studio)

    def execute(db, row):
        run_id = row.id
        db.commit()
        if worker_mode():
            notify_worker()
        else:
            factory = sessionmaker(bind=db.get_bind(), autoflush=False)
            for _ in range(25):
                if not advance_one(run_id, factory):
                    break
        db.expire_all()
        return execution_detail(db, db.get(WorkflowExecution, run_id))

    def queue_capacity(db, org):
        active = db.scalar(select(func.count()).select_from(WorkflowExecution).where(
            WorkflowExecution.organization_id == org, WorkflowExecution.status.in_(ACTIVE),
        ))
        if active >= 20:
            raise HTTPException(429, "This organization reached its active workflow limit")

    def next_trigger(trigger):
        if trigger.kind == "manual":
            return None
        if not worker_mode():
            raise HTTPException(409, "Scheduled and event publishing require the PostgreSQL worker")
        delay = timedelta(minutes=trigger.interval_minutes) if trigger.kind == "schedule" else timedelta(seconds=3)
        return utc_now_naive() + delay

    @router.get("/templates")
    def templates(user=reader):
        return [{"id": key, **value} for key, value in TEMPLATES.items()]

    @router.get("/workflows")
    def workflows(db=Depends(get_db), user=reader):
        rows = db.execute(select(Workflow, WorkflowStudio).join(WorkflowStudio, WorkflowStudio.workflow_id == Workflow.id)
            .where(Workflow.organization_id == user.organization_id).order_by(WorkflowStudio.updated_at.desc()).limit(100))
        return [definition_record(*row) for row in rows]

    @router.post("/workflows", status_code=201)
    def create(payload: Create, db=Depends(get_db), user=editor):
        lock_organization(db, user.organization_id)
        count = db.scalar(select(func.count()).select_from(WorkflowStudio).join(Workflow, Workflow.id == WorkflowStudio.workflow_id)
                          .where(Workflow.organization_id == user.organization_id))
        if count >= 100:
            raise HTTPException(429, "This organization reached its workflow limit")
        initial = {"nodes": [{"id": "trigger", "kind": "manual", "label": "Manual trigger", "x": 30, "y": 50}], "edges": []}
        graph = Graph.model_validate(TEMPLATES[payload.template]["graph"] if payload.template else initial)
        workflow = Workflow(organization_id=user.organization_id, name=payload.name)
        db.add(workflow)
        db.flush()
        studio = WorkflowStudio(workflow_id=workflow.id, creator_id=user.id, draft_json=canonical(graph.model_dump()))
        db.add(studio)
        audit(db, user.organization_id, user.id, "workflow.draft_created", f"workflow:{workflow.id}", {})
        db.commit()
        return definition_record(workflow, studio)

    @router.get("/workflows/{workflow_id}")
    def inspect(workflow_id: str, db=Depends(get_db), user=reader):
        workflow, studio = owned(db, user, workflow_id)
        versions = db.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
                              .order_by(WorkflowVersion.number.desc()).limit(30))
        return definition_record(workflow, studio) | {"graph": json.loads(studio.draft_json),
            "versions": [{"number": row.number, "created_at": stamp(row.created_at)} for row in versions]}

    @router.put("/workflows/{workflow_id}")
    def save(workflow_id: str, payload: Draft, db=Depends(get_db), user=editor):
        lock_organization(db, user.organization_id)
        workflow, studio = owned(db, user, workflow_id, payload.revision)
        if studio.lifecycle == "archived":
            raise HTTPException(409, "Archived workflows cannot be edited")
        workflow.name = payload.name
        studio.draft_json = canonical(payload.graph.model_dump())
        return change(db, workflow, studio, user, "draft_saved")

    @router.post("/validate")
    def validate(graph: Graph, user=editor):
        trigger = checked_graph(graph)
        return {"valid": True, "trigger": trigger.kind}

    @router.post("/workflows/{workflow_id}/publish")
    def publish(workflow_id: str, payload: Revision, db=Depends(get_db), user=editor):
        lock_organization(db, user.organization_id)
        workflow, studio = owned(db, user, workflow_id, payload.revision)
        if studio.lifecycle == "archived":
            raise HTTPException(409, "Archived workflows cannot be published")
        trigger = checked_graph(Graph.model_validate_json(studio.draft_json))
        next_due = next_trigger(trigger)
        number = (studio.published_version or 0) + 1
        if number > 100:
            raise HTTPException(429, "This workflow reached its version limit")
        db.add(WorkflowVersion(workflow_id=workflow.id, number=number, actor_id=user.id, definition_json=studio.draft_json))
        studio.lifecycle, studio.published_version = "published", number
        studio.next_due = next_due
        workflow.enabled = True
        return change(db, workflow, studio, user, "published")

    @router.post("/workflows/{workflow_id}/lifecycle")
    def lifecycle(workflow_id: str, payload: Lifecycle, db=Depends(get_db), user=editor):
        lock_organization(db, user.organization_id)
        workflow, studio = owned(db, user, workflow_id, payload.revision)
        allowed = {"draft": {"archived"}, "published": {"paused", "archived"}, "paused": {"published", "archived"}, "archived": set()}
        if payload.state not in allowed[studio.lifecycle]:
            raise HTTPException(409, "This lifecycle transition is unavailable")
        studio.lifecycle, studio.next_due, workflow.enabled = payload.state, None, payload.state == "published"
        if workflow.enabled:
            version = db.get(WorkflowVersion, (workflow.id, studio.published_version))
            trigger = checked_graph(Graph.model_validate_json(version.definition_json))
            studio.next_due = next_trigger(trigger)
        return change(db, workflow, studio, user, "lifecycle_changed")

    @router.post("/workflows/{workflow_id}/executions", status_code=201)
    def start(workflow_id: str, payload: Start, db=Depends(get_db), user=editor):
        lock_organization(db, user.organization_id)
        workflow, studio = owned(db, user, workflow_id)
        mode = "dry_run" if payload.dry_run else "manual"
        request_key = f"user-{payload.request_key}"
        prior = db.scalar(select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow.id,
                                                           WorkflowExecution.request_key == request_key))
        if prior:
            if prior.mode != mode or prior.parent_id or prior.facts_json != canonical(payload.facts):
                raise HTTPException(409, "The request key belongs to a different execution")
            return execute(db, prior) if prior.status in ACTIVE else execution_detail(db, prior)
        if studio.lifecycle == "archived" or (not payload.dry_run and studio.lifecycle != "published"):
            raise HTTPException(409, "Publish this workflow before starting a manual run")
        queue_capacity(db, user.organization_id)
        version = None if payload.dry_run else db.get(WorkflowVersion, (workflow.id, studio.published_version))
        graph = Graph.model_validate_json(version.definition_json if version else studio.draft_json)
        trigger = checked_graph(graph)
        if not payload.dry_run and trigger.kind != "manual":
            raise HTTPException(409, "Use the dry run to inspect a scheduled or event workflow")
        return execute(db, enqueue(db, workflow, user.id, request_key, graph, payload.facts,
                                   version.number if version else None, mode))

    @router.get("/executions")
    def executions(workflow_id: str | None = Query(None, max_length=120), db=Depends(get_db), user=reader):
        stmt = select(WorkflowExecution).where(WorkflowExecution.organization_id == user.organization_id)
        if workflow_id:
            owned(db, user, workflow_id)
            stmt = stmt.where(WorkflowExecution.workflow_id == workflow_id)
        return [execution_record(row) for row in db.scalars(stmt.order_by(WorkflowExecution.created_at.desc()).limit(60))]

    @router.get("/executions/{execution_id}")
    def execution(execution_id: str, db=Depends(get_db), user=reader):
        row = db.scalar(select(WorkflowExecution).where(WorkflowExecution.id == execution_id,
                                                         WorkflowExecution.organization_id == user.organization_id))
        if not row:
            raise HTTPException(404, "Workflow execution is unavailable")
        return execution_detail(db, row)

    @router.post("/executions/{execution_id}/cancel")
    def cancel(execution_id: str, db=Depends(get_db), user=editor):
        row = lock_execution(db, execution_id, user.organization_id)
        if not row:
            raise HTTPException(404, "Workflow execution is unavailable")
        if row.actor_id != user.id and user.role not in {"owner", "organization_admin"}:
            raise HTTPException(403, "Only the requester or an administrator can cancel this execution")
        if row.status not in ACTIVE:
            raise HTTPException(409, "The execution is already finished")
        terminate(db, row, "cancelled", actor=user.id)
        db.commit()
        return execution_detail(db, row)

    @router.post("/executions/{execution_id}/approvals/{node_id}")
    def approve(execution_id: str, node_id: str, payload: Decision, db=Depends(get_db), user=reviewer):
        row = lock_execution(db, execution_id, user.organization_id)
        if not row:
            raise HTTPException(404, "Workflow execution is unavailable")
        gate = db.get(WorkflowApproval, (row.id, node_id))
        if row.status != "waiting_approval" or gate is None or gate.status != "pending" or row.deadline_at <= utc_now_naive():
            raise HTTPException(409, "The execution has no active request for this approval")
        step = db.get(WorkflowStep, (row.id, node_id))
        gate.status, gate.reviewer_id, gate.note, gate.decided_at = payload.decision, user.id, payload.note, utc_now_naive()
        step.status, step.finished_at = ("completed" if payload.decision == "approved" else "failed"), gate.decided_at
        step.output_json = canonical({"decision": payload.decision})
        record_event(db, row, "approval_decided", user.id, node_id=node_id, decision=payload.decision)
        if payload.decision == "approved":
            row.status = "queued"
        else:
            db.flush()
            terminate(db, row, "failed", "Human approval was rejected", user.id)
        return execute(db, row)

    @router.post("/executions/{execution_id}/replay", status_code=201)
    def replay(execution_id: str, payload: Replay, db=Depends(get_db), user=editor):
        lock_organization(db, user.organization_id)
        parent = lock_execution(db, execution_id, user.organization_id)
        if not parent:
            raise HTTPException(404, "Workflow execution is unavailable")
        if parent.status not in {"failed", "cancelled", "timed_out"}:
            raise HTTPException(409, "The original execution is not replayable")
        workflow, studio = owned(db, user, parent.workflow_id)
        if studio.lifecycle == "archived":
            raise HTTPException(409, "Archived workflows cannot be replayed")
        request_key = f"user-{payload.request_key}"
        prior = db.scalar(select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow.id,
                                                           WorkflowExecution.request_key == request_key))
        if prior:
            if prior.parent_id != parent.id:
                raise HTTPException(409, "The request key belongs to a different execution")
            return execute(db, prior) if prior.status in ACTIVE else execution_detail(db, prior)
        queue_capacity(db, user.organization_id)
        return execute(db, enqueue(db, workflow, user.id, request_key,
            Graph.model_validate_json(parent.definition_json), json.loads(parent.facts_json), parent.version, "replay", parent.id))

    return router
