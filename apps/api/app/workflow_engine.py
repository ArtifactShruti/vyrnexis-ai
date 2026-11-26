"""Validate workflow graphs and advance a bounded node in a database transaction."""
from collections import defaultdict, deque
from datetime import timedelta
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StringConstraints
from sqlalchemy import and_, func, literal, or_, select, text, update

from .database import SessionLocal
from .forensics import Input, READERS, canonical, custody_chain, stamp
from .models import (
    AuditLog, CommerceFinding, CustodyEnrollment, Evidence, Incident, InvestigationRun, InvestigationTask, SecurityEvent,
    User, Workflow, WorkflowApproval, WorkflowExecution, WorkflowStep, WorkflowStudio, WorkflowVersion, utc_now_naive,
)


EDITORS = ("owner", "organization_admin", "automation_engineer")
REVIEWERS = ("owner", "organization_admin", "security_analyst", "forensic_investigator")
ACTIVE = {"queued", "running", "waiting_approval"}
TRIGGERS = {"manual", "schedule", "event"}
EVENT_MODELS = {"security_event": (SecurityEvent, SecurityEvent.received_at, "event_id"),
                "fraud_finding": (CommerceFinding, CommerceFinding.created_at, "finding_id"),
                "incident": (Incident, Incident.created_at, "incident_id")}
Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,48}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Scalar = Annotated[str, StringConstraints(max_length=300)] | StrictBool | StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)] | None
Facts = Annotated[dict[Key, Scalar], Field(max_length=20)]


class Node(Input):
    id: Key
    kind: Literal["manual", "schedule", "event", "condition", "map", "approval", "incident", "refund", "custody", "agent", "summary"]
    label: Title
    x: int = Field(ge=0, le=2400)
    y: int = Field(ge=0, le=1800)
    fact: Key | None = None
    target: Key | None = None
    equals: Scalar = None
    agent: Literal["ORACLE", "SENTINEL", "TRACE", "AEGIS", "MERCURY", "NEXUS", "VERITAS"] | None = None
    interval_minutes: int | None = Field(None, ge=5, le=1440)
    event_type: Literal["security_event", "fraud_finding", "incident"] | None = None


class Edge(Input):
    source: Key
    target: Key
    branch: Literal["always", "true", "false"] = "always"


class Graph(Input):
    nodes: list[Node] = Field(max_length=24)
    edges: list[Edge] = Field(max_length=64)


def graph_order(graph):
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise ValueError("Node IDs must be unique")
    unique_edges = {(edge.source, edge.target, edge.branch) for edge in graph.edges}
    if len(unique_edges) != len(graph.edges):
        raise ValueError("The graph has duplicate connections")
    triggers = [node for node in graph.nodes if node.kind in TRIGGERS]
    if len(triggers) != 1:
        raise ValueError("Choose exactly one manual, scheduled, or tenant event trigger")
    trigger = triggers[0]
    for node in graph.nodes:
        if node.kind in {"condition", "map", "incident", "refund", "custody", "agent"} and not node.fact:
            raise ValueError(f"{node.label} needs a named input fact")
        if node.kind == "map" and not node.target:
            raise ValueError(f"{node.label} needs an output field")
        if node.kind == "schedule" and not node.interval_minutes:
            raise ValueError("Configure the scheduled interval")
        if node.kind == "event" and not node.event_type:
            raise ValueError("Choose the tenant event to watch")
        if node.kind == "agent" and not node.agent:
            raise ValueError("Choose an agent for the saved finding node")
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge in graph.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("A connection refers to a missing node")
        if (edge.branch != "always") != (nodes[edge.source].kind == "condition"):
            raise ValueError("Use true or false branches only on condition nodes")
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    if incoming[trigger.id]:
        raise ValueError("The trigger cannot receive a connection")
    indegree = {node: len(incoming[node]) for node in nodes}
    ready = deque(node for node in nodes if not indegree[node])
    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for edge in outgoing[node]:
            indegree[edge.target] -= 1
            if not indegree[edge.target]:
                ready.append(edge.target)
    if len(order) != len(nodes):
        raise ValueError("The workflow contains a cycle")
    if any(node != trigger.id and not incoming[node] for node in nodes):
        raise ValueError("Connect every node to the trigger")
    return [nodes[node] for node in order], incoming


def template(title, kinds, **configuration):
    nodes = [
        {"id": f"step-{index}", "label": label, "kind": kind, "x": 28 + (index % 4) * 186,
         "y": 55 + (index // 4) * 112, **configuration.get(kind, {})}
        for index, (label, kind) in enumerate(kinds)
    ]
    edges = [{"source": left["id"], "target": right["id"], "branch": "always"} for left, right in zip(nodes, nodes[1:])]
    return {"title": title, "graph": Graph.model_validate({"nodes": nodes, "edges": edges}).model_dump()}


TEMPLATES = {
    "incident": template("Incident review", [("Manual trigger", "manual"), ("Read incident", "incident"),
                                               ("Analyst approval", "approval")], incident={"fact": "incident_id"}),
    "refund": template("Refund finding review", [("Manual trigger", "manual"), ("Read refund finding", "refund"),
                                                   ("Analyst approval", "approval")], refund={"fact": "finding_id"}),
    "custody": template("Evidence custody review", [("Manual trigger", "manual"), ("Check custody ledger", "custody")],
                        custody={"fact": "evidence_id"}),
    "agent": template("Nexus finding review", [("Manual trigger", "manual"), ("Read NEXUS finding", "agent"),
                                                 ("Analyst approval", "approval")],
                      agent={"agent": "NEXUS", "fact": "run_id"}),
    "summary": template("Scheduled risk summary", [("Every 60 minutes", "schedule"), ("Count recorded risks", "summary")],
                        schedule={"interval_minutes": 60}),
    "security-event": template("Security event to analyst review", [("Security event", "event"),
        ("Count recorded risks", "summary"), ("Analyst approval", "approval")], event={"event_type": "security_event"}),
    "fraud-event": template("New refund finding to analyst review", [("Refund finding", "event"),
        ("Read finding", "refund"), ("Analyst approval", "approval")], event={"event_type": "fraud_finding"},
        refund={"fact": "finding_id"}),
}


def record_event(db, run, action, actor=None, **details):
    db.add(AuditLog(organization_id=run.organization_id, actor_id=actor, action=f"workflow.{action}",
                    resource=f"workflow_execution:{run.id}", details=canonical(details)))


def enqueue(db, workflow, actor_id, key, graph, facts, version, mode, parent=None, timeout_minutes=60):
    row = WorkflowExecution(organization_id=workflow.organization_id, workflow_id=workflow.id, actor_id=actor_id,
                            parent_id=parent, request_key=key, version=version, mode=mode,
                            definition_json=canonical(graph.model_dump()), facts_json=canonical(facts),
                            deadline_at=utc_now_naive() + timedelta(minutes=timeout_minutes))
    db.add(row)
    db.flush()
    db.add_all(WorkflowStep(execution_id=row.id, node_id=node.id) for node in graph.nodes)
    record_event(db, row, "queued", actor_id, mode=mode, parent_id=parent)
    return row


def lock_execution(db, execution_id, org):
    filters = (WorkflowExecution.id == execution_id, WorkflowExecution.organization_id == org)
    if db.bind.dialect.name == "sqlite":
        db.execute(update(WorkflowExecution).where(*filters).values(status=WorkflowExecution.status))
    return db.scalar(select(WorkflowExecution).where(*filters).with_for_update()
                     .execution_options(populate_existing=True))


def node_output(db, actor, node, facts):
    value = facts.get(node.fact)
    if node.kind in TRIGGERS:
        return {"trigger": node.kind, **(facts if node.kind == "event" else {})}
    if node.kind == "condition":
        match = node.fact in facts and type(value) is type(node.equals) and value == node.equals
        return {"branch": "true" if match else "false"}
    if node.kind == "summary":
        models = {"incidents": Incident, "refund_findings": CommerceFinding}
        return {name: db.scalar(select(func.count()).select_from(model).where(model.organization_id == actor.organization_id))
                for name, model in models.items()}
    if node.kind == "map":
        if node.fact not in facts:
            raise ValueError("The required fact is missing")
        return {node.target: value}
    if not isinstance(value, str) or len(value) > 120:
        raise ValueError("The source ID fact is missing or invalid")
    if node.kind in {"incident", "refund"}:
        model = Incident if node.kind == "incident" else CommerceFinding
        row = db.scalar(select(model).where(model.id == value, model.organization_id == actor.organization_id))
        if row is None:
            raise ValueError("The source record is unavailable")
        return ({"incident_id": row.id, "severity": row.severity, "status": row.status} if node.kind == "incident"
                else {"finding_id": row.id, "score": row.score, "status": row.status})
    if actor.role not in READERS:
        raise ValueError("The requester lacks forensic or Nexus access")
    if node.kind == "custody":
        file = db.scalar(select(Evidence).where(Evidence.id == value, Evidence.organization_id == actor.organization_id))
        row = db.get(CustodyEnrollment, value)
        if not file or not row or row.organization_id != actor.organization_id:
            raise ValueError("The evidence custody ledger is unavailable")
        consistent, events = custody_chain(db, row, file)
        return {"evidence_id": file.id, "chain_status": "valid" if consistent else "mismatch", "entries": len(events)}
    saved = db.scalar(select(InvestigationTask).join(InvestigationRun, InvestigationRun.id == InvestigationTask.run_id).where(
        InvestigationRun.id == value, InvestigationRun.organization_id == actor.organization_id,
        InvestigationTask.agent == node.agent, InvestigationTask.status == "completed",
    ))
    if saved is None or not saved.result_json:
        raise ValueError("The requested saved agent finding is unavailable")
    result = json.loads(saved.result_json)
    return {"task_id": saved.id, "agent": saved.agent, "verification_status": result["verification_status"],
            "claim": result["claim"]}


def terminate(db, run, status, error=None, actor=None):
    run.status, run.finished_at, run.error = status, utc_now_naive(), error
    if status in {"cancelled", "timed_out", "failed"}:
        db.execute(update(WorkflowApproval).where(WorkflowApproval.execution_id == run.id,
            WorkflowApproval.status == "pending").values(status="cancelled", decided_at=run.finished_at))
        db.execute(update(WorkflowStep).where(WorkflowStep.execution_id == run.id,
            WorkflowStep.status.in_(("pending", "waiting_approval"))).values(status="skipped", finished_at=run.finished_at))
    record_event(db, run, status, actor, error=error)


def advance_one(execution_id=None, session_factory=SessionLocal):
    now = utc_now_naive()
    with session_factory.begin() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = 5000"))
        eligible = or_(WorkflowExecution.status.in_(("queued", "running")),
                       and_(WorkflowExecution.status == "waiting_approval", WorkflowExecution.deadline_at <= now))
        stmt = select(WorkflowExecution).where(eligible)
        if execution_id:
            stmt = stmt.where(WorkflowExecution.id == execution_id)
            if db.bind.dialect.name == "sqlite":
                db.execute(update(WorkflowExecution).where(WorkflowExecution.id == execution_id, eligible)
                           .values(status=WorkflowExecution.status))
        run = db.scalar(stmt.order_by(WorkflowExecution.created_at, WorkflowExecution.id).limit(1)
                        .with_for_update(skip_locked=True))
        if run is None:
            return False
        if run.deadline_at <= now:
            terminate(db, run, "timed_out", "Workflow deadline expired")
            return True
        actor = db.get(User, run.actor_id)
        if not actor or not actor.is_active or actor.organization_id != run.organization_id or actor.role not in EDITORS:
            terminate(db, run, "failed", "Requester no longer has workflow execution permission")
            return True
        order, incoming = graph_order(Graph.model_validate_json(run.definition_json))
        states = {step.node_id: step for step in db.scalars(
            select(WorkflowStep).where(WorkflowStep.execution_id == run.id)
        )}
        run.status = "running"
        for node in order:
            step = states[node.id]
            if step.status != "pending":
                continue
            edges = incoming[node.id]
            active = any(states[edge.source].status == "completed" and (
                edge.branch == "always" or json.loads(states[edge.source].output_json or "{}").get("branch") == edge.branch
            ) for edge in edges)
            if edges and not active:
                step.status, step.finished_at = "skipped", now
                record_event(db, run, "node_skipped", node_id=node.id)
                continue
            step.attempt += 1
            step.started_at = now
            if node.kind == "approval":
                step.status, run.status = "waiting_approval", "waiting_approval"
                db.add(WorkflowApproval(execution_id=run.id, node_id=node.id))
                record_event(db, run, "approval_requested", node_id=node.id)
                return True
            try:
                step.output_json = canonical(node_output(db, actor, node, json.loads(run.facts_json)))
            except ValueError as exc:
                step.status, step.error, step.finished_at = "failed", str(exc)[:240], utc_now_naive()
                db.flush()
                terminate(db, run, "failed", step.error)
                return True
            step.status, step.finished_at = "completed", utc_now_naive()
            record_event(db, run, "node_completed", node_id=node.id, attempt=step.attempt)
            return True
        terminate(db, run, "completed")
        return True


def schedule_one(session_factory=SessionLocal):
    now = utc_now_naive()
    with session_factory.begin() as db:
        due = db.execute(select(WorkflowStudio, Workflow).join(Workflow, Workflow.id == WorkflowStudio.workflow_id)
            .where(WorkflowStudio.lifecycle == "published", WorkflowStudio.next_due <= now)
            .order_by(WorkflowStudio.next_due).limit(1).with_for_update(skip_locked=True)).first()
        if due is None:
            return False
        studio, workflow = due
        version = db.get(WorkflowVersion, (workflow.id, studio.published_version))
        graph = Graph.model_validate_json(version.definition_json)
        trigger = next(node for node in graph.nodes if node.kind in {"schedule", "event"})
        key = f"schedule-{studio.published_version}-{stamp(studio.next_due)}"
        studio.next_due = now + (timedelta(minutes=trigger.interval_minutes) if trigger.kind == "schedule" else timedelta(seconds=3))
        actor = db.get(User, studio.creator_id)
        if actor and actor.is_active and actor.organization_id == workflow.organization_id and actor.role in EDITORS:
            active = db.scalar(select(func.count()).select_from(WorkflowExecution).where(
                WorkflowExecution.workflow_id == workflow.id, WorkflowExecution.status.in_(ACTIVE),
            ))
            if not active:
                if trigger.kind == "schedule":
                    enqueue(db, workflow, actor.id, key, graph, {}, version.number, "scheduled")
                else:
                    model, occurred_at, fact = EVENT_MODELS[trigger.event_type]
                    prefix = f"event-{version.number}-"
                    handled = select(WorkflowExecution.id).where(
                        WorkflowExecution.workflow_id == workflow.id,
                        WorkflowExecution.request_key == literal(prefix) + model.id,
                    ).exists()
                    event_id = db.scalar(select(model.id).where(
                        model.organization_id == workflow.organization_id, occurred_at >= version.created_at,
                        ~handled,
                    ).order_by(occurred_at, model.id).limit(1))
                    if event_id:
                        enqueue(db, workflow, actor.id, prefix + event_id, graph, {fact: event_id}, version.number, "event")
        return True
