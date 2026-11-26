"""Optional, separately reviewed interpretations of stored deterministic findings."""
import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import StringConstraints
from sqlalchemy import select

from .ai_gateway import generate_cited, lock_organization, settings_for
from .database import get_db
from .forensics import Input, READERS, WRITERS, stamp
from .models import AgentInterpretation, AiInvocation, InvestigationTask
from .nexus import ReviewInput, audit_run, owned_run
from .nexus_analysis import Finding


class InterpretInput(Input):
    request_key: Annotated[str, StringConstraints(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
    acknowledge_model_context: bool


def task_for(db, user, run_id, task_id):
    run = owned_run(db, run_id, user)
    task = db.scalar(select(InvestigationTask).where(InvestigationTask.run_id == run.id, InvestigationTask.id == task_id))
    if not task:
        raise HTTPException(404, "Task is unavailable")
    return run, task


def interpretation_record(row, invocation):
    return {
        "id": row.id, "status": row.status, "error": row.error,
        "review_status": row.review_status, "reviewer_id": row.reviewer_id, "review_note": row.review_note,
        "result": json.loads(row.result_json) if row.result_json else None, "created_at": stamp(row.created_at),
        "usage": ({"provider": invocation.provider, "model": invocation.model, "prompt_version": invocation.prompt_version,
                   "duration_ms": invocation.duration_ms, "input_tokens": invocation.input_tokens,
                   "output_tokens": invocation.output_tokens} if invocation else None),
    }


def build_hybrid_router(require_roles):
    router = APIRouter(prefix="/api/v1/investigations")
    reader = Depends(require_roles(*READERS))
    reviewer = Depends(require_roles(*WRITERS))
    path = "/{run_id}/tasks/{task_id}/interpretations"

    @router.get(path)
    def inspect(run_id: str, task_id: str, db=Depends(get_db), user=reader):
        _, task = task_for(db, user, run_id, task_id)
        rows = db.execute(select(AgentInterpretation, AiInvocation).outerjoin(
            AiInvocation, AiInvocation.id == AgentInterpretation.invocation_id,
        ).where(AgentInterpretation.task_id == task.id).order_by(AgentInterpretation.created_at.desc()).limit(15))
        return [interpretation_record(*item) for item in rows]

    @router.post(path)
    async def interpret(run_id: str, task_id: str, value: InterpretInput, db=Depends(get_db), user=reader):
        if not value.acknowledge_model_context:
            raise HTTPException(403, "Confirm sending the saved finding summary to the configured model")
        lock_organization(db, user.organization_id)
        run, task = task_for(db, user, run_id, task_id)
        if task.status != "completed" or not task.result_json:
            raise HTTPException(409, "A completed deterministic finding is required")
        prior = db.scalar(select(AgentInterpretation).where(
            AgentInterpretation.task_id == task.id, AgentInterpretation.request_key == value.request_key,
        ))
        if prior:
            return interpretation_record(prior, db.get(AiInvocation, prior.invocation_id) if prior.invocation_id else None)
        if settings_for(db, user.organization_id).mode != "hybrid":
            raise HTTPException(409, "Set execution mode to hybrid to interpret investigation findings")
        row = AgentInterpretation(task_id=task.id, actor_id=user.id, request_key=value.request_key)
        db.add(row)
        db.flush()
        interpretation_id = row.id
        db.commit()

        def load_summary():
            _, current = task_for(db, user, run_id, task_id)
            finding = Finding.model_validate_json(current.result_json)
            summary = {"claim": finding.claim, "record_references": finding.sources, "evidence": finding.evidence_refs,
                       "verification_status": finding.verification_status, "limitations": finding.limitations,
                       "alternative_explanations": finding.alternative_explanations}
            return [{"key": f"task:{current.id}", "title": current.agent, "excerpt": json.dumps(summary, ensure_ascii=False)}]

        try:
            answer, usage = await generate_cited(
                db, user, "Explain what this finding supports, its limitations, and what an analyst can verify next.",
                load_summary, value.acknowledge_model_context, prompt_version="nexus-interpretation-1", required_mode="hybrid",
            )
            row.status, row.invocation_id = "completed", usage["id"]
            row.result_json = json.dumps(answer.model_dump() | {"verification_status": "source_reference_validated"})
        except asyncio.CancelledError:
            row.status, row.error = "cancelled", "Interpretation was cancelled"
            db.commit()
            raise
        except HTTPException as exc:
            row.status, row.error = "failed", str(exc.detail)
            row.invocation_id = getattr(exc, "invocation_id", None)
        audit_run(db, run, user.id, "nexus.interpretation.finished",
                  {"id": interpretation_id, "task_id": task_id, "status": row.status})
        db.commit()
        return interpretation_record(row, db.get(AiInvocation, row.invocation_id) if row.invocation_id else None)

    @router.post(path + "/{interpretation_id}/review")
    def review(run_id: str, task_id: str, interpretation_id: str, value: ReviewInput, db=Depends(get_db), user=reviewer):
        lock_organization(db, user.organization_id)
        run, _ = task_for(db, user, run_id, task_id)
        row = db.scalar(select(AgentInterpretation).where(
            AgentInterpretation.id == interpretation_id, AgentInterpretation.task_id == task_id,
        ))
        if row is None:
            raise HTTPException(404, "Interpretation is unavailable")
        if row.status != "completed" or row.review_status != "pending":
            raise HTTPException(409, "This interpretation is not awaiting review")
        row.review_status, row.reviewer_id, row.review_note = value.decision, user.id, value.note
        audit_run(db, run, user.id, "nexus.interpretation.reviewed", {"id": row.id, "decision": value.decision})
        db.commit()
        return interpretation_record(row, db.get(AiInvocation, row.invocation_id) if row.invocation_id else None)

    return router
