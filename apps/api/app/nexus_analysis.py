"""Bounded, deterministic investigation tasks over stored tenant records."""
from collections import Counter
from datetime import timezone
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .forensics import case_evidence, custody_chain, stamp
from .models import (
    CommerceFinding, CommerceRecord, DetectionAlert, DetectionAlertEvent, Evidence, ForensicCase,
    ForensicCaseLink, Incident, IntelligenceEntity, InvestigationTask, SecurityEvent,
)

SOURCE_MODELS = {
    "commerce_finding": CommerceFinding, "evidence": Evidence, "incident": Incident,
    "entity": IntelligenceEntity, "refund": CommerceRecord, "security_event": SecurityEvent,
}

class Finding(BaseModel):
    task_id: str
    investigation_id: str
    organization_id: str
    agent: str
    category: str
    claim: str
    sources: list[str] = Field(max_length=100)
    evidence_refs: list[str] = Field(max_length=30)
    reasoning_summary: str
    verification_status: Literal["supported_by_records", "partially_supported", "insufficient_evidence", "conflicting_evidence"]
    limitations: list[str]
    alternative_explanations: list[str]
    risk_factors: list[str] = Field(max_length=40)
    created_at: str
    human_review: Literal["pending"] = "pending"


def context(db, run):
    org = run.organization_id
    relations = {"incident": [], "finding": [], "evidence": [], "entity": []}
    if run.case_id:
        case = db.scalar(select(ForensicCase).where(ForensicCase.id == run.case_id, ForensicCase.organization_id == org))
        if case is None:
            raise ValueError("Case no longer available")
        for row in db.scalars(select(ForensicCaseLink).where(ForensicCaseLink.case_id == case.id)
                              .order_by(ForensicCaseLink.created_at.desc()).limit(100)):
            if row.kind in relations:
                relations[row.kind].append(row.object_id)
    else:
        case = None
        relations["incident"].append(run.incident_id)
    incidents = db.scalars(select(Incident).where(Incident.organization_id == org,
                                                 Incident.id.in_(relations["incident"]))).all()
    incident_ids = [item.id for item in incidents]
    findings = db.scalars(select(CommerceFinding).where(CommerceFinding.organization_id == org,
        CommerceFinding.id.in_(relations["finding"]) | CommerceFinding.incident_id.in_(incident_ids))
        .order_by(CommerceFinding.created_at.desc()).limit(20)).all()
    for item in findings:
        relations["evidence"].extend(json.loads(item.report)["evidence_ids"])
    files = db.scalars(select(Evidence).where(Evidence.organization_id == org,
        Evidence.investigation_id.in_(incident_ids) | Evidence.id.in_(relations["evidence"]))
        .order_by(Evidence.created_at.desc()).limit(30)).all()
    return case, incidents, findings, files, relations["entity"]


def check_source_ownership(db, run, agents):
    upstream = db.scalars(select(InvestigationTask).where(
        InvestigationTask.run_id == run.id, InvestigationTask.agent.in_(agents),
        InvestigationTask.result_json.is_not(None),
    )).all()
    refs = set()
    available = set()
    for task in upstream:
        result = Finding.model_validate_json(task.result_json)
        refs.update(result.sources)
        refs.update(result.evidence_refs)
    for kind, model in SOURCE_MODELS.items():
        prefix = f"{kind}:"
        ids = [ref[len(prefix):] for ref in refs if ref.startswith(prefix)]
        if not ids:
            continue
        query = select(model.id).where(model.id.in_(ids), model.organization_id == run.organization_id)
        if kind == "refund":
            query = query.where(CommerceRecord.kind == "refund")
        available.update(prefix + item_id for item_id in db.scalars(query))
    return available, refs - available


def analyze(db, run, task, read_bytes, hash_matches):
    from .models import utc_now_naive

    org = run.organization_id
    case, incidents, findings, files, entity_ids = context(db, run)
    incident_ids = [item.id for item in incidents]
    claim, sources, evidence, factors = "", [], [], []
    status = "supported_by_records"
    notes = ["Deterministic analysis of bounded persisted records. Results describe available observations."]
    alternatives = ["The scope may omit relevant records or legitimate explanations."]
    agent = task.agent

    if agent == "SENTINEL":
        alert_events = db.scalars(select(DetectionAlertEvent.event_id).join(
            DetectionAlert, DetectionAlert.id == DetectionAlertEvent.alert_id,
        ).where(DetectionAlert.organization_id == org, DetectionAlert.incident_id.in_(incident_ids)).limit(100)).all()
        event_ids = set(alert_events)
        for item in findings:
            event_ids.update(json.loads(item.report)["security_event_ids"])
        events = db.scalars(select(SecurityEvent).where(SecurityEvent.organization_id == org,
            SecurityEvent.id.in_(event_ids)).order_by(SecurityEvent.occurred_at.desc()).limit(50)).all()
        sources = [f"security_event:{event.id}" for event in events]
        claim = (f"Reviewed {len(events)} linked security observations. "
                 "Compare recorded sign-ins with the authorized device inventory before treating a pattern as compromise.")
        if not events:
            status = "insufficient_evidence"
    elif agent == "MERCURY":
        refund_ids = {value for item in findings for value in json.loads(item.report)["refund_ids"]}
        refunds = db.scalars(select(CommerceRecord).where(CommerceRecord.organization_id == org,
            CommerceRecord.id.in_(refund_ids), CommerceRecord.kind == "refund").limit(80)).all()
        sources = [f"commerce_finding:{item.id}" for item in findings] + [f"refund:{item.id}" for item in refunds]
        claim = f"Reviewed {len(findings)} saved rule reports supported by {len(refunds)} recorded refunds."
        for item in findings[:8]:
            factors.extend(factor["code"] for factor in json.loads(item.report)["factors"])
        if not findings:
            status = "insufficient_evidence"
    elif agent == "TRACE":
        evidence = [f"evidence:{item.id}" for item in files]
        custody = [custody_chain(db, item, file)[0] for item, file in case_evidence(db, case)[:8]] if case else []
        linked_entities = db.scalars(select(IntelligenceEntity.id).where(
            IntelligenceEntity.id.in_(entity_ids), IntelligenceEntity.organization_id == org,
        )).all()
        sources = evidence + [f"entity:{item_id}" for item_id in linked_entities]
        claim = f"Reviewed metadata for {len(files)} evidence records and checked {len(custody)} custody ledgers. {sum(custody)} matched."
        if not files:
            status = "insufficient_evidence"
        elif any(not result for result in custody):
            status = "conflicting_evidence"
        elif not custody:
            status = "partially_supported"
    elif agent == "VERITAS":
        counts = Counter()
        available, missing = check_source_ownership(db, run, ("SENTINEL", "MERCURY", "TRACE"))
        for item in files[:4]:
            evidence.append(f"evidence:{item.id}")
            try:
                valid = hash_matches(item, read_bytes(item))
            except HTTPException:
                counts["unavailable"] += 1
            else:
                counts["match" if valid else "mismatch"] += 1
        sources = sorted(available | set(evidence))
        claim = (f"{len(available)} of {len(available) + len(missing)} upstream references resolved in this organization. "
                 f"Rehashed up to four files. {counts['match']} matched, {counts['mismatch']} differed, "
                 f"and {counts['unavailable']} were unavailable.")
        notes.append("Record availability and matching hashes establish reference and byte consistency. Factual claims and original authorship require separate evidence.")
        if counts["mismatch"]:
            status = "conflicting_evidence"
        elif missing or counts["unavailable"] or len(files) > 4:
            status = "partially_supported" if available or counts["match"] else "insufficient_evidence"
        elif not sources:
            status = "insufficient_evidence"
    elif agent == "AEGIS":
        high = [row for row in incidents if row.severity.lower() in {"critical", "high"}]
        sources = [f"incident:{row.id}" for row in incidents] + [f"commerce_finding:{item.id}" for item in findings]
        factors = [f"{len(high)} linked high or critical incidents", f"{len(findings)} persisted commerce rule reports"]
        claim = "Review the recorded severity and rule weights with the analyst. No compliance determination is available."
        if not sources:
            status = "insufficient_evidence"
    elif agent == "ORACLE":
        history = db.scalars(select(Incident).where(Incident.organization_id == org)
                             .order_by(Incident.created_at.desc()).limit(60)).all()
        days = Counter(item.created_at.replace(tzinfo=timezone.utc).date().isoformat() for item in history)
        sources = [f"incident:{item.id}" for item in history]
        claim = f"{len(history)} recent incidents were recorded across {len(days)} distinct UTC days."
        if len(days) < 4:
            claim += " The observed coverage is insufficient for a trend comparison or forecast."
            status = "insufficient_evidence"
        else:
            ordered_counts = [days[day] for day in sorted(days)]
            midpoint = len(ordered_counts) // 2
            older, newer = ordered_counts[:midpoint], ordered_counts[midpoint:]
            claim += f" The mean per observed day was {sum(older)/len(older):.1f} in the earlier sample and {sum(newer)/len(newer):.1f} in the later sample."
            notes.append("Unobserved dates are excluded. The comparison cannot establish a complete trend or forecast.")
    elif agent == "NEXUS":
        jobs = db.scalars(select(InvestigationTask).where(InvestigationTask.run_id == run.id,
                                                         InvestigationTask.id != task.id)).all()
        results = [json.loads(job.result_json) for job in jobs if job.result_json]
        excluded = len(jobs) - len(results)
        missing = sum(item["verification_status"] == "insufficient_evidence" for item in results)
        conflicts = sum(item["verification_status"] == "conflicting_evidence" for item in results)
        sources = [f"investigation_task:{job.id}" for job in jobs if job.result_json]
        evidence = sorted({ref for result in results for ref in result["evidence_refs"]})[:30]
        claim = (f"Aggregated {len(results)} completed tasks. {missing} reported insufficient records, "
                 f"{conflicts} reported consistency problems, and {excluded} had no result. Human review is required.")
        if conflicts:
            status = "conflicting_evidence"
        elif excluded or missing:
            status = "partially_supported" if results else "insufficient_evidence"
    else:
        raise ValueError("Unknown investigation task")
    return Finding(task_id=task.id, investigation_id=run.id, organization_id=org, agent=agent,
                   category=agent.lower(), claim=claim, sources=sorted(set(sources))[:100],
                   evidence_refs=sorted(set(evidence))[:30],
                   reasoning_summary="Used tenant-scoped persisted records selected for this task.",
                   verification_status=status, limitations=notes, alternative_explanations=alternatives,
                   risk_factors=sorted(set(factors))[:40], created_at=stamp(utc_now_naive())).model_dump()
