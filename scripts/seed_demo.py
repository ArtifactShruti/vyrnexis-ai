"""Create a deterministic, isolated VYRNEXIS demonstration workspace.

This script seeds only .dev-logs/vyrnexis-demo.db.
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from getpass import getpass
import os
from pathlib import Path
import secrets
from argon2 import PasswordHasher

DEMO_DATABASE_URL = "sqlite:///./.dev-logs/vyrnexis-demo.db"
if os.environ.get("DATABASE_URL") not in (None, DEMO_DATABASE_URL):
    raise RuntimeError("seed_demo.py only writes to .dev-logs/vyrnexis-demo.db; refusing the configured DATABASE_URL")
os.environ["DATABASE_URL"] = DEMO_DATABASE_URL
Path(".dev-logs").mkdir(exist_ok=True)

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.detection import evaluate_detections  # noqa: E402
from app.forensics import append_custody, canonical  # noqa: E402
from app.ingestion import store_batch  # noqa: E402
from app.models import (  # noqa: E402
    CommerceFinding,
    CommerceRecord,
    CustodyEnrollment,
    DataSource,
    DetectionInput,
    DetectionRule,
    Incident,
    Evidence,
    EvidenceFileMetadata,
    ForensicCase,
    ForensicCaseLink,
    ForensicNote,
    IntelligenceEntity,
    IntelligenceRelationship,
    Organization,
    SecurityEvent,
    User,
)


ORG_ID = "demo-vyrnexis-lab"
DEMO_OWNER = "demo.admin@vyrnexis-demo.org"
ENTITIES = [
    ("demo-user-01", "user", "Synthetic analyst account"),
    ("demo-device-01", "device", "Engineering workstation"),
    ("demo-ip-01", "ip_address", "198.51.100.24 (documentation range)"),
    ("demo-event-01", "security_event", "Unfamiliar device sign-in"),
    ("demo-txn-01", "transaction", "Refund review TXN-DEMO-1042"),
    ("demo-evidence-01", "evidence", "Authorized demo event bundle"),
]
RELATIONSHIPS = [
    ("demo-rel-01", "demo-user-01", "demo-device-01", "signed_in_from", .94, "demo-auth-event-01"),
    ("demo-rel-02", "demo-device-01", "demo-ip-01", "observed_at_address", .99, "demo-network-event-01"),
    ("demo-rel-03", "demo-user-01", "demo-event-01", "associated_with", .88, "demo-auth-event-01"),
    ("demo-rel-04", "demo-user-01", "demo-txn-01", "refund_activity", .76, "demo-refund-1042"),
    ("demo-rel-05", "demo-event-01", "demo-evidence-01", "supported_by", .91, "demo-evidence-bundle-01"),
]


def seed_detection_scenario(db) -> None:
    for kind, duration in [("failed_signins", 15), ("unfamiliar_device", 30)]:
        if not db.query(DetectionRule).filter_by(organization_id=ORG_ID, kind=kind).first():
            db.add(DetectionRule(organization_id=ORG_ID, kind=kind, window_minutes=duration,
                                 severity="high", threshold=3, enabled=True))
    db.flush()

    reference_time = datetime(2026, 11, 25, 1, 0)
    steps = [("success", "training-device-a"), ("failure", "training-device-b"),
             ("failure", "training-device-b"), ("failure", "training-device-b"),
             ("success", "training-device-b")]
    for index, (outcome, device) in enumerate(steps, start=1):
        event_id = f"demo-detection-auth-{index:02}"
        if db.get(SecurityEvent, event_id):
            continue
        occurred_at = reference_time + timedelta(minutes=index)
        db.add(SecurityEvent(
            id=event_id, organization_id=ORG_ID, source="synthetic-detection-lab",
            event_type="authentication", severity="low", title=f"Synthetic sign-in {outcome} #{index}",
            description="Generated locally for the detection scenario.", source_reference=event_id,
            occurred_at=occurred_at,
        ))
        db.flush()
        telemetry = DetectionInput(
            event_id=event_id, organization_id=ORG_ID, source="synthetic-detection-lab",
            external_id=event_id, payload_hash=hashlib.sha256(event_id.encode()).hexdigest(),
            account="training-account", device=device, outcome=outcome, occurred_at=occurred_at,
        )
        db.add(telemetry)
        db.flush()
        evaluate_detections(db, telemetry)
        db.flush()


def seed_forensic_case(db, owner, evidence, evidence_path, commerce_source_id):
    case_id = "demo-forensic-case-01"
    if owner is None or db.get(ForensicCase, case_id):
        return
    case = ForensicCase(
        id=case_id, organization_id=ORG_ID, creator_id=owner.id, investigator_id=owner.id,
        team="Demonstration lab", title="Synthetic sign-in and refund review",
        description="Training case linked to the synthetic incident, commerce finding, and demonstration evidence.",
        category="fraud", priority="high", status="investigating",
    )
    db.add(case)
    db.flush()
    refs = [{"kind": "incident", "object_id": "demo-incident-01"}]
    finding = db.query(CommerceFinding).join(CommerceRecord, CommerceRecord.id == CommerceFinding.refund_id).filter(
        CommerceFinding.organization_id == ORG_ID, CommerceRecord.source_id == commerce_source_id,
        CommerceRecord.external_id == "synthetic-refund-3",
    ).one_or_none()
    if finding is not None:
        refs.append({"kind": "finding", "object_id": finding.id})
    if db.get(CustodyEnrollment, evidence.id) is None:
        actual = evidence_path.read_bytes()
        if (hashlib.sha256(actual).hexdigest(), hashlib.sha512(actual).hexdigest()) != (evidence.sha256, evidence.sha512):
            raise RuntimeError("Demo forensic evidence bytes failed integrity verification")
        if db.get(EvidenceFileMetadata, evidence.id) is None:
            db.add(EvidenceFileMetadata(evidence_id=evidence.id, original_filename=evidence.name, size_bytes=len(actual)))
        enrollment = CustodyEnrollment(case_id=case.id, organization_id=ORG_ID, evidence_id=evidence.id,
                                       classification="log", tags_json=canonical(["synthetic"]))
        db.add(enrollment)
        db.flush()
        append_custody(db, enrollment, evidence, owner, "registered", "Register authorized synthetic evidence", owner.id)
        append_custody(db, enrollment, evidence, owner, "verified", "Compare both digests of synthetic evidence", owner.id)
        refs.append({"kind": "evidence", "object_id": evidence.id})
    for ref in refs:
        db.add(ForensicCaseLink(case_id=case.id, **ref))
    db.add(ForensicNote(
        revision=1, case_id=case.id, author_id=owner.id, category="observation",
        body="The linked synthetic observations support analyst review. Establishing causation requires additional evidence.",
        references_json=canonical(refs),
    ))


def seed(create_demo_user: bool = False) -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if not db.get(Organization, ORG_ID):
            db.add(Organization(id=ORG_ID, name="VYRNEXIS Demonstration Lab", slug="vyrnexis-demo-lab"))
        for entity_id, entity_type, display_name in ENTITIES:
            row = db.get(IntelligenceEntity, entity_id)
            if row is None:
                db.add(IntelligenceEntity(
                    id=entity_id,
                    organization_id=ORG_ID,
                    entity_type=entity_type,
                    external_id=entity_id.upper(),
                    display_name=display_name,
                    properties='{"synthetic": true, "mode": "demonstration"}',
                ))
        for rel_id, source_id, target_id, rel_type, confidence, reference in RELATIONSHIPS:
            if db.get(IntelligenceRelationship, rel_id) is None:
                db.add(IntelligenceRelationship(
                    id=rel_id,
                    organization_id=ORG_ID,
                    source_id=source_id,
                    target_id=target_id,
                    relationship_type=rel_type,
                    confidence=confidence,
                    source_reference=reference,
                ))
        if not db.get(Incident, "demo-incident-01"):
            db.add(Incident(
                id="demo-incident-01",
                organization_id=ORG_ID,
                title="Unfamiliar sign-in and refund activity",
                severity="high",
                status="review",
                description=(
                    "Synthetic demonstration scenario: an account sign-in from a previously "
                    "unseen device is associated with a refund record. This is correlation, "
                    "not verified causation; analyst review is required."
                ),
            ))
        for event in [
            SecurityEvent(
                id="demo-security-auth-01",
                organization_id=ORG_ID,
                source="synthetic-auth-log",
                event_type="authentication_anomaly",
                severity="high",
                title="Unfamiliar device sign-in",
                description="Synthetic observation for demonstration. It does not establish account compromise or attribution.",
                source_reference="demo-auth-event-01",
                occurred_at=datetime(2026, 11, 25, 1, 14),
            ),
            SecurityEvent(
                id="demo-security-refund-01",
                organization_id=ORG_ID,
                source="synthetic-commerce-audit",
                event_type="refund_review",
                severity="medium",
                title="Refund review TXN-DEMO-1042",
                description="Synthetic refund review record correlated with the sign-in scenario for analyst training.",
                source_reference="demo-refund-1042",
                occurred_at=datetime(2026, 11, 25, 1, 14),
            ),
        ]:
            if db.get(SecurityEvent, event.id) is None:
                db.add(event)
        seed_detection_scenario(db)
        evidence_id = "demo-evidence-file-01"
        evidence_content = (
            "VYRNEXIS SYNTHETIC DEMONSTRATION EVIDENCE\n"
            "Scenario: unfamiliar device sign-in was observed alongside a refund review.\n"
            "Interpretation: these observations are correlated for training only; causation is unverified.\n"
            "Source: fabricated local demonstration event bundle.\n"
        ).encode("utf-8")
        evidence = db.get(Evidence, evidence_id)
        if evidence is None:
            evidence = Evidence(
                id=evidence_id,
                organization_id=ORG_ID,
                investigation_id="demo-incident-01",
                name="synthetic-auth-refund-event.txt",
                sha256=hashlib.sha256(evidence_content).hexdigest(),
                sha512=hashlib.sha512(evidence_content).hexdigest(),
                mime_type="text/plain",
                immutable=True,
            )
            db.add(evidence)
            db.flush()
        root = Path(os.getenv("VYRNEXIS_EVIDENCE_DIR", ".dev-logs/evidence")).resolve()
        organization_key = hashlib.sha256(ORG_ID.encode("utf-8")).hexdigest()
        evidence_directory = root / organization_key
        evidence_path = evidence_directory / f"{evidence_id}.blob"
        if not evidence_path.exists():
            if evidence.sha256 != hashlib.sha256(evidence_content).hexdigest():
                raise RuntimeError("Refusing to restore demo evidence bytes that do not match stored metadata")
            evidence_directory.mkdir(parents=True, exist_ok=True)
            temporary = evidence_directory / f".{evidence_id}.{secrets.token_hex(8)}.tmp"
            with temporary.open("xb") as bundle:
                bundle.write(evidence_content)
                bundle.flush()
                os.fsync(bundle.fileno())
            os.replace(temporary, evidence_path)
        commerce_source_id = "demo-commerce-intake-01"
        commerce_source = db.get(DataSource, commerce_source_id)
        if commerce_source is None:
            commerce_source = DataSource(id=commerce_source_id, organization_id=ORG_ID,
                                         kind="commerce", name="Synthetic commerce scenario")
            db.add(commerce_source)
            db.flush()
        rows = [{
            "record_type": "refund", "external_id": f"synthetic-refund-{index}",
            "account": "training-account", "device": "training-device-b",
            "occurred_at": f"2026-11-25T01:0{index + 5}:00Z", "currency": "USD", "amount_minor": 1250,
            **({"evidence_id": evidence_id} if index == 3 else {}),
        } for index in range(1, 4)]
        store_batch(db, commerce_source, rows, "demo-commerce-batch-01",
                    hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
                    actor_id=None, run_inline=True)
        if create_demo_user:
            email = DEMO_OWNER
            user = db.query(User).filter(User.email == email).first()
            if not user:
                password = getpass("Choose a password for the local demo owner (12+ characters): ")
                confirmation = getpass("Confirm demo owner password: ")
                if len(password) < 12 or password != confirmation:
                    raise ValueError("Passwords must match and contain at least 12 characters.")
                db.add(User(
                    organization_id=ORG_ID,
                    email=email,
                    full_name="Demo Organization Owner",
                    password_hash=PasswordHasher().hash(password),
                    role="owner",
                ))
                print(f"Created local demo owner: {email} (password stored as an Argon2id hash)")
            else:
                print(f"Local demo owner already exists: {email}")
        db.flush()
        owner = db.query(User).filter_by(email=DEMO_OWNER, organization_id=ORG_ID, role="owner", is_active=True).one_or_none()
        seed_forensic_case(db, owner, evidence, evidence_path, commerce_source_id)
        db.commit()
    print(f"Seeded isolated demonstration organization: {ORG_ID}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-demo-user", action="store_true", help="prompt securely to create a local demo owner account")
    seed(create_demo_user=parser.parse_args().create_demo_user)
