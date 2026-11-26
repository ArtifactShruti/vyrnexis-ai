"""Run the linked synthetic demonstration on the isolated PostgreSQL Docker stack."""
import time
from datetime import timedelta

from smoke_forensics import api, checksum, create_case, exchange, tenant, verify_image_upload
from smoke_intake import batch, verify as verify_intake
from smoke_phase9 import BI, pipeline, topology


def investigate(case_id, token):
    run = api("/investigations", "POST", {
        "case_id": case_id, "request_key": "flagship-investigation",
    }, token, expected=201)
    path = f"/investigations/{run['id']}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = api(path, token=token)
        if run["status"] == "awaiting_approval":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Synthetic investigation did not reach review")
    assert len(run["tasks"]) == 7 and all(task["status"] == "completed" for task in run["tasks"])
    reviewed = api(path + "/review", "POST", {
        "decision": "approved", "note": "Reviewed the synthetic findings and their limitations.",
    }, token)
    assert reviewed["status"] == "approved"
    return run["id"]


def verify():
    token, commerce, anchor, incident, finding, graph = verify_intake()
    profile = api("/auth/me", token=token)
    user, org = profile["user"], profile["organization"]
    owner = {"access_token": token, **profile}
    case = create_case(token)
    case_path = f"/forensic-cases/{case['id']}"
    assigned = api(case_path + "/assignment", "PUT", {
        "expected_version": case["version"], "investigator_id": user["id"], "team": "Synthetic investigation",
    }, token)
    assert assigned["investigator_id"] == user["id"]
    for kind, object_id in (("incident", incident["incident_id"]), ("finding", finding["id"])):
        api(case_path + "/links", "POST", {"kind": kind, "object_id": object_id}, token)

    evidence_id = verify_image_upload(owner, 8002)
    evidence_path = case_path + f"/evidence/{evidence_id}"
    api(case_path + "/evidence", "POST", {
        "evidence_id": evidence_id, "classification": "image", "purpose": "Store the synthetic incident fixture.",
    }, token, expected=201)
    api(evidence_path + "/custody", "POST", {
        "action": "verify", "expected_sequence": 1, "purpose": "Verify synthetic image integrity.",
    }, token)
    custody = api(evidence_path + "/custody", token=token)
    assert [entry["action"] for entry in custody["events"]] == ["registered", "verified"]
    investigation = investigate(case["id"], token)

    conversation = api("/copilot/conversations", "POST", {
        "title": "Synthetic incident evidence", "case_id": case["id"],
    }, token, expected=201)
    turn = api(f"/copilot/conversations/{conversation['id']}/turns", "POST", {
        "text": "What evidence custody action and SHA-256 were recorded?", "request_key": "flagship-copilot",
    }, token)
    assert turn["status"] == "completed" and turn["mode"] == "record_search"
    assert any(item["key"].startswith(f"custody:{evidence_id}:") for item in turn["sources"])

    workflow = pipeline(owner, 8002, incident_id=incident["incident_id"])
    foreign, _ = tenant(8002)
    refund_node = next(item for item in graph["entities"] if item["external_id"] == finding["refund_id"])
    refund_graph = api(f"/intelligence/graph?focus_id={refund_node['id']}", token=token)
    device = next(item for item in refund_graph["entities"]
                  if item["entity_type"] == "device" and item["display_name"] == "new")
    simulation = topology(owner, foreign, 8002, host_id=device["id"])

    report = api(case_path + "/reports", "POST", token=token, expected=201)
    report_path = case_path + f"/reports/{report['id']}"
    saved = api(report_path + "/json", token=token)
    assert saved["integrity_hash"] == checksum(saved["snapshot"])
    assert len(saved["snapshot"]["agent_findings"]) == 7
    status, pdf, _ = exchange(report_path + "/pdf", token=token)
    assert status == 200 and pdf.startswith(b"%PDF")

    day = anchor.date().isoformat()
    report_query = f"{BI}/report?start={day}&end={day}&currency=USD"
    before = api(report_query, token=token)["summary"][0]
    assert before["refunded_minor"] == "3750" and before["payments"] == 0
    payment = batch(commerce, "flagship-payment", [{
        "record_type": "payment", "external_id": "flagship-payment-1", "account": "training", "device": "new",
        "occurred_at": (anchor + timedelta(minutes=9)).isoformat(), "currency": "USD", "amount_minor": 5000,
    }], token)
    assert payment["accepted"] == 1
    after = api(report_query, token=token)["summary"][0]
    assert after["payments"] == 1 and after["net_recorded_minor"] == "1250"
    print(f"Synthetic flagship complete. Organization {org['id']}, incident {incident['incident_id']}, case {case['id']}.")
    print(f"Persisted investigation {investigation}, workflow {workflow}, simulation {simulation}, and report {report['id']}.")
    print("Business Intelligence reflected the submitted payment. Copilot used cited record search.")


if __name__ == "__main__":
    verify()
