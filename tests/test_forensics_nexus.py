from datetime import timedelta
import hashlib
import subprocess
import sys

import pytest
from argon2 import PasswordHasher

from app.forensics import canonical
from app.main import evidence_integrity, read_evidence_bytes
from app.models import CustodyEvent, InvestigationAttempt, InvestigationRun, InvestigationTask, User, utc_now_naive
from app.nexus import claim, execute_one, validate_dependencies
from app.nexus_worker import supervise_claim
from test_api import register


def new_case(client, auth, title="Synthetic refund investigation"):
    result = client.post("/api/v1/forensic-cases", headers=auth, json={
        "title": title, "description": "Review authorized demonstration records.", "category": "fraud", "priority": "high",
    })
    assert result.status_code == 201, result.text
    return result.json()


def test_case_assignment_notes_custody_report_and_tenant_isolation(client):
    owner, auth = register(client, "case")
    foreign, other = register(client, "case-other")
    owner_id, org = owner["user"]["id"], owner["organization"]["id"]
    case = new_case(client, auth)
    uri = f"/api/v1/forensic-cases/{case['id']}"
    assert client.get(uri).status_code == 401
    assert client.get(uri, headers=other).status_code == 404
    assert client.put(f"{uri}/assignment", headers=auth, json={
        "investigator_id": foreign["user"]["id"], "expected_version": case["version"],
    }).status_code == 404
    assigned = client.put(f"{uri}/assignment", headers=auth, json={
        "investigator_id": owner_id, "team": "Response team", "expected_version": case["version"],
    })
    assert assigned.status_code == 200, assigned.text
    assert client.put(f"{uri}/assignment", headers=auth, json={"expected_version": case["version"]}).status_code == 409
    assert len(client.get("/api/v1/forensic-cases?assigned=true&query=refund", headers=auth).json()["items"]) == 1
    upload = client.post("/api/v1/evidence", params={"organization_id": org, "name": "Evidence log"},
                         files={"file": ("actual-name.txt", b"synthetic artifact", "text/plain")}, headers=auth)
    assert upload.status_code == 200, upload.text
    evidence = upload.json()["id"]
    enrolled = client.post(f"{uri}/evidence", headers=auth, json={
        "evidence_id": evidence, "classification": "log", "tags": ["synthetic"], "purpose": "Register case evidence",
    })
    assert enrolled.status_code == 201 and enrolled.json()["original_filename"] == "actual-name.txt", enrolled.text
    assert client.get(f"/api/v1/evidence/{evidence}/download", headers=auth).status_code == 409
    custody = f"{uri}/evidence/{evidence}/custody"
    assert client.get(custody, headers=other).status_code == 404
    assert client.post(custody, headers=auth, json={
        "action": "transfer", "purpose": "Foreign assignee", "custodian_id": foreign["user"]["id"], "expected_sequence": 1,
    }).status_code == 404
    note_ref = {"kind": "evidence", "object_id": evidence}
    note = client.post(f"{uri}/notes", headers=auth, json={
        "category": "hypothesis", "body": "First interpretation needs review.", "references": [note_ref],
    }).json()
    revised = client.post(f"{uri}/notes/{note['id']}/revisions", headers=auth, json={
        "category": "review", "body": "Reviewed the source record and recorded the limitation.",
        "references": [note_ref], "expected_revision": 1,
    })
    assert revised.status_code == 201 and revised.json()["revision"] == 2
    assert client.post(f"{uri}/notes/{note['id']}/revisions", headers=auth, json={
        "category": "review", "body": "Outdated update attempt.", "expected_revision": 1,
    }).status_code == 409
    verification = client.post(custody, headers=auth, json={
        "action": "verify", "purpose": "Check original evidence", "expected_sequence": 1,
    })
    assert verification.status_code == 200 and verification.json()["action"] == "verified"
    assert client.post(custody, headers=auth, json={
        "action": "examine", "purpose": "Stale request", "expected_sequence": 1,
    }).status_code == 409
    exported = client.post(f"{uri}/evidence/{evidence}/export", headers=auth, json={"purpose": "Prepare review copy"})
    assert exported.content == b"synthetic artifact"
    chain = client.get(custody, headers=auth).json()
    assert chain["chain_status"] == "valid" and [row["action"] for row in chain["events"]] == [
        "registered", "verified", "exported",
    ]
    for status in ("investigating", "review", "closed"):
        current = client.get(uri, headers=auth).json()
        changed = client.post(f"{uri}/transition", headers=auth, json={
            "status": status, "reason": "Reviewer recorded adequate evidence limitations.",
            "expected_version": current["version"],
        })
        assert changed.status_code == 200, changed.text
    assert client.post(f"{uri}/notes", headers=auth, json={"category": "observation", "body": "Closed case write"}).status_code == 409
    reports = []
    for version in (1, 2):
        result = client.post(f"{uri}/reports", headers=auth)
        assert result.status_code == 201 and result.json()["version"] == version, result.text
        reports.append(result.json())
    report_path = f"{uri}/reports/{reports[0]['id']}"
    data = client.get(f"{report_path}/json", headers=auth).json()
    assert hashlib.sha256(canonical(data["snapshot"]).encode()).hexdigest() == data["integrity_hash"]
    assert {row["revision"] for row in data["snapshot"]["notes"]} == {1, 2}
    pdf = client.get(f"{report_path}/pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert client.get(f"{report_path}/pdf", headers=other).status_code == 404
    with client.app.state.test_session_factory() as db:
        db.get(CustodyEvent, (evidence, 2)).purpose = "tampered"
        db.commit()
    assert client.get(custody, headers=auth).json()["chain_status"] == "mismatch"
    assert client.post(f"{uri}/evidence/{evidence}/export", headers=auth, json={"purpose": "Try altered chain"}).status_code == 409


def test_agent_pipeline_dependency_review_replay_and_scope(client):
    owner, auth = register(client, "pipeline")
    _, foreign = register(client, "pipeline-other")
    case = new_case(client, auth)
    path = "/api/v1/investigations"
    args = {"case_id": case["id"], "request_key": "pipeline-test-01"}
    assert client.post(path, headers=foreign, json=args).status_code == 404
    started = client.post(path, headers=auth, json=args)
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "awaiting_approval"
    assert len(run["tasks"]) == 7 and all(task["status"] == "completed" for task in run["tasks"])
    assert next(task for task in run["tasks"] if task["agent"] == "TRACE")["result"]["verification_status"] == "insufficient_evidence"
    assert len(next(task for task in run["tasks"] if task["agent"] == "NEXUS")["dependencies"]) == 6
    assert client.post(path, headers=auth, json=args).json()["id"] == run["id"]
    assert len(client.get("/api/v1/agents/executions", headers=auth).json()) == 7
    scope = f"{path}/{run['id']}"
    assert client.get(scope, headers=foreign).status_code == 404
    assert client.get(f"{scope}/report", headers=auth).json()["snapshot"]["status"] == "awaiting_approval"
    assert client.post(f"{scope}/review", headers=foreign, json={"decision": "approved", "note": "Foreign reviewer"}).status_code == 404
    result = client.post(f"{scope}/review", headers=auth, json={"decision": "approved", "note": "Reviewed partial results"})
    assert result.status_code == 200 and result.json()["status"] == "approved"
    assert client.post(f"{scope}/review", headers=auth, json={"decision": "approved", "note": "Repeat review"}).status_code == 409
    uri = f"/api/v1/forensic-cases/{case['id']}"
    uploaded = client.post("/api/v1/evidence", params={"organization_id": owner["organization"]["id"], "name": "lab.txt"},
                           files={"file": ("lab.txt", b"synthetic artifact", "text/plain")}, headers=auth)
    assert uploaded.status_code == 200, uploaded.text
    evidence_id = uploaded.json()["id"]
    assert client.post(f"{uri}/evidence", headers=auth, json={
        "evidence_id": evidence_id, "classification": "log", "purpose": "Register a laboratory artifact",
    }).status_code == 201
    rerun = client.post(path, headers=auth, json=args | {"request_key": "pipeline-custody-01"}).json()
    verified = next(task for task in rerun["tasks"] if task["agent"] == "VERITAS")
    assert verified["result"]["verification_status"] == "supported_by_records"
    assert "1 of 1 upstream references resolved" in verified["result"]["claim"]
    custody = client.get(f"{uri}/evidence/{evidence_id}/custody", headers=auth).json()
    assert [event["action"] for event in custody["events"]] == ["registered", "examined"]
    assert client.post(path, headers=auth, json=args | {"request_key": "pipeline-custody-01"}).json()["id"] == rerun["id"]
    assert client.get(f"{uri}/evidence/{evidence_id}/custody", headers=auth).json() == custody
    with pytest.raises(ValueError):
        validate_dependencies({"A": ("B",), "B": ("A",)})


def test_worker_recovers_expired_lease_and_cancels_remaining_tasks(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "worker")
    _, auth = register(client, "leased")
    case = new_case(client, auth)
    root = "/api/v1/investigations"
    run = client.post(root, headers=auth, json={"case_id": case["id"], "request_key": "lease-test-01"}).json()
    assert run["status"] == "queued"
    factory = client.app.state.test_session_factory
    _, task_id, _ = claim(run["id"], factory)
    with factory.begin() as db:
        task = db.get(InvestigationTask, task_id)
        task.lease_until = utc_now_naive() - timedelta(seconds=1)
    assert claim(run["id"], factory) is True
    with factory.begin() as db:
        assert db.get(InvestigationAttempt, (task_id, 1)).status == "timed_out"
        db.get(InvestigationTask, task_id).available_at = utc_now_naive() - timedelta(seconds=10)
    assert execute_one(read_evidence_bytes, evidence_integrity, run["id"], factory)
    with factory() as db:
        assert db.get(InvestigationAttempt, (task_id, 2)).status == "completed"
    path = f"{root}/{run['id']}"
    assert client.post(f"{path}/review", headers=auth, json={"decision": "approved", "note": "Premature"}).status_code == 409
    result = client.post(f"{path}/cancel", headers=auth).json()
    assert result["status"] == "cancelled"
    assert sum(task["status"] == "cancelled" for task in result["tasks"]) == 6
    assert not execute_one(read_evidence_bytes, evidence_integrity, run["id"], factory)


def test_case_roles_and_authorized_custody_transfer(client):
    owner, auth = register(client, "transfer")
    organization_id = owner["organization"]["id"]
    password = "isolated-forensic-fixture-password"
    password_hash = PasswordHasher().hash(password)
    people = [User(
        organization_id=organization_id, email=f"{role}@forensics.example.org",
        full_name=role, password_hash=password_hash, role=role,
    ) for role in ("forensic_investigator", "security_analyst")]
    with client.app.state.test_session_factory.begin() as db:
        db.add_all(people)
        db.flush()
        investigator_id = people[0].id
        emails = [person.email for person in people]

    def login(email):
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    investigator, analyst = map(login, emails)
    case = new_case(client, auth)
    uri = f"/api/v1/forensic-cases/{case['id']}"
    assert client.get(uri, headers=analyst).status_code == 200
    assert client.post(f"{uri}/notes", headers=analyst, json={
        "category": "observation", "body": "Role check for notes.",
    }).status_code == 403
    assert client.put(f"{uri}/assignment", headers=investigator, json={
        "expected_version": case["version"], "investigator_id": investigator_id,
    }).status_code == 403
    upload = client.post("/api/v1/evidence", params={"organization_id": organization_id, "name": "Custody test"},
                         files={"file": ("record.txt", b"synthetic transfer record", "text/plain")}, headers=auth)
    assert upload.status_code == 200
    evidence_id = upload.json()["id"]
    assert client.post(f"{uri}/evidence", headers=auth, json={
        "evidence_id": evidence_id, "classification": "log", "purpose": "Register test transfer file.",
    }).status_code == 201
    custody = f"{uri}/evidence/{evidence_id}/custody"
    archive = {"action": "archive", "purpose": "Archive after investigator review.", "expected_sequence": 1}
    assert client.post(custody, headers=investigator, json=archive).status_code == 403
    transferred = client.post(custody, headers=auth, json={
        "action": "transfer", "purpose": "Assign the new authorized custodian.",
        "expected_sequence": 1, "custodian_id": investigator_id,
    })
    assert transferred.status_code == 200
    assert transferred.json()["previous_custodian_id"] == owner["user"]["id"]
    assert transferred.json()["new_custodian_id"] == investigator_id
    assert client.post(custody, headers=investigator, json=archive | {"expected_sequence": 2}).status_code == 200
    assert client.get(custody, headers=analyst).json()["chain_status"] == "valid"
    assert client.post(f"{uri}/evidence/{evidence_id}/export", headers=auth, json={
        "purpose": "Archived bytes cannot be exported.",
    }).status_code == 409


def test_supervisor_times_out_a_child_and_preserves_the_retry(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "worker")
    _, auth = register(client, "process-timeout")
    case = new_case(client, auth)
    response = client.post("/api/v1/investigations", headers=auth, json={
        "case_id": case["id"], "request_key": "process-timeout-test",
    })
    assert response.status_code == 201
    run_id = response.json()["id"]
    factory = client.app.state.test_session_factory
    job = claim(run_id, factory)
    _, task_id, _ = job
    run_child = subprocess.run

    def slow_child(_command, **kwargs):
        return run_child([sys.executable, "-c", "from time import sleep; sleep(8)"], **kwargs)

    monkeypatch.setattr("app.nexus_worker.subprocess.run", slow_child)
    supervise_claim(job, 0.25, factory)
    with factory.begin() as db:
        timed_out = db.get(InvestigationAttempt, (task_id, 1))
        assert timed_out.status == "timed_out" and "execution deadline" in timed_out.error
        task = db.get(InvestigationTask, task_id)
        assert task.status == "queued" and task.lease_token is None
        task.available_at = utc_now_naive() - timedelta(seconds=10)
    assert execute_one(read_evidence_bytes, evidence_integrity, run_id, factory)
    with factory() as db:
        assert db.get(InvestigationAttempt, (task_id, 2)).status == "completed"


def test_replay_closes_dependencies_keeps_original_and_is_idempotent(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "worker")
    _, auth = register(client, "replay")
    _, foreign = register(client, "replay-foreign")
    case = new_case(client, auth)
    root = "/api/v1/investigations"
    original = client.post(root, headers=auth, json={"case_id": case["id"], "request_key": "replay-original-key"}).json()
    source_path = f"{root}/{original['id']}"
    veritas = next(task for task in original["tasks"] if task["agent"] == "VERITAS")
    with client.app.state.test_session_factory.begin() as db:
        db.get(InvestigationRun, original["id"]).status = "awaiting_approval"
        db.get(InvestigationTask, veritas["id"]).status = "timed_out"
        db.get(InvestigationTask, veritas["id"]).attempts = 3
    payload = {"request_key": "replay-new-key", "agents": ["VERITAS"]}
    assert client.post(source_path + "/replay", headers=foreign, json=payload).status_code == 404
    assert client.post(source_path + "/replay", headers=auth, json=payload | {"agents": ["TRACE"]}).status_code == 422
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "inline")
    replay = client.post(source_path + "/replay", headers=auth, json=payload)
    assert replay.status_code == 201, replay.text
    run = replay.json()
    assert run["id"] != original["id"] and run["status"] == "awaiting_approval"
    assert {task["agent"] for task in run["tasks"]} == {"SENTINEL", "MERCURY", "TRACE", "VERITAS"}
    assert all(task["status"] == "completed" for task in run["tasks"])
    assert run["replay"] == {"source_run_id": original["id"], "target_agents": ["VERITAS"]}
    assert client.post(source_path + "/replay", headers=auth, json=payload).json()["id"] == run["id"]
    assert client.post(root, headers=auth, json=payload | {"case_id": case["id"]}).status_code == 409
    assert client.post(source_path + "/replay", headers=auth, json={"request_key": payload["request_key"]}).status_code == 409
    parent = client.get(source_path, headers=auth).json()
    assert next(task for task in parent["tasks"] if task["id"] == veritas["id"])["status"] == "timed_out"
