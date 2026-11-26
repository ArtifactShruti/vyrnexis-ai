"""Simulate impacts over explicit, tenant-owned dependency relationships."""
from collections import defaultdict, deque
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import func, select

from .ai_gateway import lock_organization
from .database import get_db
from .forensics import Input, Label, Purpose, canonical, checksum, stamp
from .models import IntelligenceEntity, IntelligenceRelationship, TwinSimulation


DEPENDENCIES = {"depends_on", "data_depends_on", "process_depends_on"}
MAX_NODES = 300
MAX_EDGES = 1200
EDITORS = ("owner", "organization_admin", "security_analyst", "forensic_investigator", "automation_engineer")


class Dependency(Input):
    dependent_id: Label
    prerequisite_id: Label
    kind: Literal["depends_on", "data_depends_on", "process_depends_on"]
    reason: Purpose
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class Scenario(Input):
    title: Label
    scenario_type: Literal["outage", "application_failure", "device_isolation", "containment", "account_restriction",
                           "workflow_disruption", "policy_change", "dependency_removal"]
    target_id: Label
    assumption: Purpose
    depth: int = Field(4, ge=1, le=8)
    excluded_dependencies: list[Label] = Field(default_factory=list, max_length=12)
    request_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,80}$")]

    @model_validator(mode="after")
    def normalize(self):
        self.excluded_dependencies = sorted(set(self.excluded_dependencies))
        return self


def entity_record(item):
    return {"id": item.id, "name": item.display_name, "type": item.entity_type}


def edge_record(item):
    return {"id": item.id, "dependent_id": item.source_id, "prerequisite_id": item.target_id,
            "kind": item.relationship_type, "reference": item.source_reference}


def topology(db, org):
    entities = db.scalars(select(IntelligenceEntity).where(IntelligenceEntity.organization_id == org)
                          .order_by(IntelligenceEntity.id).limit(MAX_NODES + 1)).all()
    ids = [item.id for item in entities[:MAX_NODES]]
    relationships = db.scalars(select(IntelligenceRelationship).where(
        IntelligenceRelationship.organization_id == org, IntelligenceRelationship.relationship_type.in_(DEPENDENCIES),
        IntelligenceRelationship.source_id.in_(ids), IntelligenceRelationship.target_id.in_(ids),
    ).order_by(IntelligenceRelationship.id).limit(MAX_EDGES + 1)).all()
    snapshot = {"entities": [entity_record(item) for item in entities[:MAX_NODES]],
                "dependencies": [edge_record(item) for item in relationships[:MAX_EDGES]]}
    return snapshot | {"digest": checksum(snapshot), "truncated": len(entities) > MAX_NODES or len(relationships) > MAX_EDGES}


def impact(snapshot, target, depth, excluded):
    entities = {item["id"]: item for item in snapshot["entities"]}
    upstream = defaultdict(list)
    for edge in snapshot["dependencies"]:
        if edge["id"] not in excluded:
            upstream[edge["prerequisite_id"]].append((edge["dependent_id"], edge["id"]))
    paths = {target: ([target], [])}
    queue = deque([target])
    cutoff = False
    while queue:
        current = queue.popleft()
        path, dependencies = paths[current]
        for dependent, edge in upstream[current]:
            if dependent in paths:
                continue
            if len(dependencies) >= depth:
                cutoff = True
                continue
            paths[dependent] = (path + [dependent], dependencies + [edge])
            queue.append(dependent)
    affected = [entities[item] | {"depth": len(edges), "path": path, "dependencies": edges}
                for item, (path, edges) in paths.items()]
    return {"affected": affected, "direct": sum(item["depth"] == 1 for item in affected),
            "indirect": sum(item["depth"] > 1 for item in affected), "depth_limited": cutoff}


def simulation_record(item):
    return {"id": item.id, "created_at": stamp(item.created_at), "topology_digest": item.topology_digest,
            "input": json.loads(item.input_json), "result": json.loads(item.result_json)}


def build_twin_router(current_user, require_roles, audit):
    router = APIRouter(prefix="/api/v1/digital-twin")
    read = Depends(current_user)
    write = Depends(require_roles(*EDITORS))

    def owned(db, user, scenario_id):
        item = db.scalar(select(TwinSimulation).where(TwinSimulation.id == scenario_id,
                                                       TwinSimulation.organization_id == user.organization_id))
        if item is None:
            raise HTTPException(404, "Simulation is unavailable")
        return item

    @router.get("/topology")
    def read_topology(db=Depends(get_db), user=read):
        return topology(db, user.organization_id)

    @router.post("/dependencies", status_code=201)
    def create_dependency(payload: Dependency, db=Depends(get_db), user=write):
        if payload.dependent_id == payload.prerequisite_id:
            raise HTTPException(422, "An entity cannot depend on itself")
        lock_organization(db, user.organization_id)
        entities = db.scalars(select(IntelligenceEntity.id).where(
            IntelligenceEntity.id.in_([payload.dependent_id, payload.prerequisite_id]),
            IntelligenceEntity.organization_id == user.organization_id,
        )).all()
        if len(entities) != 2:
            raise HTTPException(404, "A dependency endpoint is unavailable")
        prior = db.scalar(select(IntelligenceRelationship).where(
            IntelligenceRelationship.organization_id == user.organization_id,
            IntelligenceRelationship.source_id == payload.dependent_id,
            IntelligenceRelationship.target_id == payload.prerequisite_id,
            IntelligenceRelationship.relationship_type == payload.kind,
        ).limit(1))
        if prior:
            return edge_record(prior)
        edge = IntelligenceRelationship(organization_id=user.organization_id, source_id=payload.dependent_id,
                                        target_id=payload.prerequisite_id, relationship_type=payload.kind, confidence=payload.confidence,
                                        source_reference=payload.reason)
        db.add(edge)
        db.flush()
        audit(db, user.organization_id, user.id, "twin.dependency.recorded", f"relationship:{edge.id}", {})
        db.commit()
        return edge_record(edge)

    @router.get("/simulations")
    def list_simulations(db=Depends(get_db), user=read):
        rows = db.scalars(select(TwinSimulation).where(TwinSimulation.organization_id == user.organization_id)
                          .order_by(TwinSimulation.created_at.desc()).limit(30))
        return [{"id": row.id, "title": json.loads(row.input_json)["title"], "created_at": stamp(row.created_at)}
                for row in rows]

    @router.post("/simulations", status_code=201)
    def simulate(payload: Scenario, db=Depends(get_db), user=write):
        lock_organization(db, user.organization_id)
        value = canonical(payload.model_dump(exclude={"request_key"}))
        prior = db.scalar(select(TwinSimulation).where(TwinSimulation.organization_id == user.organization_id,
                                                        TwinSimulation.request_key == payload.request_key))
        if prior:
            if prior.input_json != value:
                raise HTTPException(409, "The request key belongs to a different scenario")
            return simulation_record(prior)
        count = db.scalar(select(func.count()).select_from(TwinSimulation).where(
            TwinSimulation.organization_id == user.organization_id,
        ))
        if count >= 100:
            raise HTTPException(429, "This organization reached its simulation limit")
        snapshot = topology(db, user.organization_id)
        if snapshot["truncated"]:
            raise HTTPException(413, "The topology exceeds the bounded simulation size")
        edges = {edge["id"]: edge for edge in snapshot["dependencies"]}
        exclusions = set(payload.excluded_dependencies)
        if exclusions - edges.keys():
            raise HTTPException(404, "One or more mitigation dependencies are unavailable")
        target = payload.target_id
        removed = set()
        if payload.scenario_type == "dependency_removal":
            if target not in edges:
                raise HTTPException(404, "The selected dependency is unavailable")
            removed = {target}
            target = edges[target]["dependent_id"]
        elif target not in {item["id"] for item in snapshot["entities"]}:
            raise HTTPException(404, "The selected entity is unavailable")
        baseline = impact(snapshot, target, payload.depth, removed)
        alternative = impact(snapshot, target, payload.depth, removed | exclusions) if exclusions else None
        remaining = [item["id"] for item in alternative["affected"]] if alternative else []
        outcome = {"hypothetical": True, "target_entity_id": target, "baseline": baseline, "alternative": alternative,
                   "avoided_entities": [item["id"] for item in baseline["affected"] if item["id"] not in remaining]
                   if alternative else [],
                   "limitations": ["Propagation assumes downstream dependents are affected when their prerequisite is unavailable.",
                                   "Each entity has one shortest recorded path. Other paths and unrecorded dependencies may exist.",
                                   "Estimated downtime and business loss require additional operational inputs."],
                   "topology": {"entities": snapshot["entities"], "dependencies": snapshot["dependencies"]}}
        row = TwinSimulation(organization_id=user.organization_id, actor_id=user.id, request_key=payload.request_key,
                             input_json=value, topology_digest=snapshot["digest"], result_json=canonical(outcome))
        db.add(row)
        db.flush()
        audit(db, user.organization_id, user.id, "twin.simulation.created", f"twin_simulation:{row.id}",
              {"scenario_type": payload.scenario_type, "topology_digest": snapshot["digest"]})
        db.commit()
        return simulation_record(row)

    @router.get("/simulations/{scenario_id}")
    def simulation(scenario_id: str, db=Depends(get_db), user=read):
        return simulation_record(owned(db, user, scenario_id))

    @router.get("/simulations/{scenario_id}/export")
    def export(scenario_id: str, db=Depends(get_db), user=read):
        item = owned(db, user, scenario_id)
        audit(db, user.organization_id, user.id, "twin.simulation.exported", f"twin_simulation:{item.id}", {})
        db.commit()
        return Response(canonical(simulation_record(item)), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename=twin-{item.id}.json",
                                 "Cache-Control": "private, no-store"})

    return router
