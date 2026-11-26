"""Persist hypothetical comparisons separately from commerce and evidence."""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import model_validator
from sqlalchemy import func, select

from .ai_gateway import lock_organization
from .commerce import CorrelationPolicy, assess_refund, finding_record, utc
from .database import get_db
from .forensics import Input, Label
from .models import CommerceFinding, CommerceRecord, CounterfactualScenario, SecurityEvent


class Assumptions(Input):
    scenario: Literal["exclude_device", "legitimate_refund", "exclude_event", "adjust_thresholds"]
    event_id: Label | None = None
    policy: CorrelationPolicy | None = None

    @model_validator(mode="after")
    def select_inputs(self):
        if bool(self.event_id) != (self.scenario == "exclude_event") or bool(self.policy) != (self.scenario == "adjust_thresholds"):
            raise ValueError("Supply only the inputs needed for the selected scenario")
        return self


def assessment(report):
    return {"score": sum(row["weight"] for row in report["factors"]), **report}


def scenario_record(row):
    return {"id": row.id, "finding_id": row.finding_id, "created_at": utc(row.created_at), **json.loads(row.snapshot_json)}


def build_counterfactual_router(require_roles, audit, analyst_roles):
    router = APIRouter(prefix="/api/v1/commerce/findings")
    analyst = Depends(require_roles(*analyst_roles))

    def finding_for(db, user, finding_id):
        finding = db.scalar(select(CommerceFinding).where(
            CommerceFinding.id == finding_id, CommerceFinding.organization_id == user.organization_id,
        ))
        if not finding:
            raise HTTPException(404, "Commerce finding is unavailable")
        return finding

    @router.get("/{finding_id}/scenarios")
    def list_scenarios(finding_id: str, db=Depends(get_db), user=analyst):
        finding_for(db, user, finding_id)
        rows = db.scalars(select(CounterfactualScenario).where(
            CounterfactualScenario.finding_id == finding_id, CounterfactualScenario.organization_id == user.organization_id,
        ).order_by(CounterfactualScenario.created_at.desc()).limit(20))
        return [scenario_record(row) for row in rows]

    @router.post("/{finding_id}/scenarios", status_code=201)
    def run(finding_id: str, value: Assumptions, db=Depends(get_db), user=analyst):
        lock_organization(db, user.organization_id)
        finding = finding_for(db, user, finding_id)
        refund = db.scalar(select(CommerceRecord).where(
            CommerceRecord.id == finding.refund_id, CommerceRecord.organization_id == user.organization_id,
            CommerceRecord.kind == "refund",
        ))
        if not refund:
            raise HTTPException(404, "Refund source record is unavailable")
        original = finding_record(finding)
        if value.event_id and (value.event_id not in original["security_event_ids"] or not db.scalar(
            select(SecurityEvent.id).where(SecurityEvent.organization_id == user.organization_id, SecurityEvent.id == value.event_id)
        )):
            raise HTTPException(404, "The security event is unavailable in this finding")
        count = db.scalar(select(func.count()).select_from(CounterfactualScenario).where(
            CounterfactualScenario.finding_id == finding.id, CounterfactualScenario.organization_id == user.organization_id,
        ))
        if count >= 50:
            raise HTTPException(429, "This finding reached its scenario limit")
        original_policy = CorrelationPolicy.model_validate(original["policy"])
        baseline = assessment(assess_refund(db, refund, original_policy))
        adjusted = assessment(assess_refund(
            db, refund, value.policy or original_policy, include_refund=value.scenario != "legitimate_refund",
            match_device=value.scenario not in {"exclude_device", "legitimate_refund"}, excluded_event=value.event_id,
        ))
        original_factors = {item["code"] for item in baseline["factors"]}
        adjusted_factors = {item["code"] for item in adjusted["factors"]}
        snapshot = {
            "hypothetical": True, "assumptions": value.model_dump(), "original": original,
            "current_baseline": baseline, "adjusted": adjusted,
            "removed_factors": sorted(original_factors - adjusted_factors),
            "added_factors": sorted(adjusted_factors - original_factors),
            "remaining_factors": sorted(original_factors & adjusted_factors),
            "uncertainty": [
                "This comparison uses the stored policy and source records available at evaluation time.",
                "Rule score changes represent the supplied assumptions. They do not establish causal effects or refund legitimacy.",
            ],
        }
        row = CounterfactualScenario(organization_id=user.organization_id, finding_id=finding.id, actor_id=user.id,
                                     snapshot_json=json.dumps(snapshot, ensure_ascii=False))
        db.add(row)
        db.flush()
        audit(db, user.organization_id, user.id, "commerce.counterfactual.created", f"commerce_finding:{finding.id}",
              {"scenario_id": row.id, "scenario": value.scenario})
        db.commit()
        return scenario_record(row)

    return router
