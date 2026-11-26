"""Exercise Phase 5 using synthetic records on the dedicated local PostgreSQL stack."""
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json
import secrets
from uuid import uuid4

from smoke_postgres import compose, request, wait_for_worker


def register_tenant():
    slug = "phase5-smoke-" + uuid4().hex[:12]
    credentials = {"email": slug + "@example.org", "password": secrets.token_urlsafe(24)}
    token = request("/auth/register", "POST", {
        "organization_name": "Synthetic Phase 5 verification " + slug,
        "organization_slug": slug, "full_name": "Synthetic Verification Owner",
        **credentials,
    })["access_token"]
    return token, credentials


def batch(source, key, rows, token):
    connection = HTTPConnection("127.0.0.1", 8002, timeout=10)
    try:
        connection.request("POST", f"/api/v1/data-sources/{source}/batches",
                           body=json.dumps({"version": 1, "records": rows}), headers={
                               "Authorization": "Bearer " + token, "Content-Type": "application/json",
                               "Idempotency-Key": key,
                           })
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Batch request failed with HTTP {response.status}")
        return json.load(response)
    finally:
        connection.close()


def verify_web_proxy(credentials, expected_finding):
    connection = HTTPConnection("localhost", 3001, timeout=10)
    try:
        connection.request("POST", "/api/auth/login", json.dumps(credentials), {"Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 200
        cookies = SimpleCookie()
        for name, value in response.getheaders():
            if name.lower() == "set-cookie":
                cookies.load(value)
        response.read()
        access = cookies["vyrnexis_access"]
        assert access["httponly"]
        connection.request("GET", "/api/intake/commerce/findings", headers={"Cookie": f"vyrnexis_access={access.value}"})
        response = connection.getresponse()
        assert response.status == 200
        assert any(row["id"] == expected_finding for row in json.load(response))
    finally:
        connection.close()


def verify():
    assert "(head)" in compose("exec", "-T", "api", "python", "-m", "alembic", "current")
    compose("exec", "-T", "api", "python", "-m", "alembic", "check")
    token, credentials = register_tenant()
    foreign, _ = register_tenant()
    security = request("/data-sources", "POST", {"name": "Synthetic application logs", "kind": "security"},
                       token, expected=201)["id"]
    commerce = request("/data-sources", "POST", {"name": "Synthetic refund intake", "kind": "commerce"},
                       token, expected=201)["id"]
    assert request("/detection-status", token=token)["mode"] == "worker"
    request("/detection-rules/failed_signins", "PUT", {"threshold": 3}, token)
    request("/detection-rules/unfamiliar_device", "PUT", {"window_minutes": 30}, token)
    anchor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    auth = [{
        "record_type": "security", "external_id": f"auth-{i}", "event_type": "authentication",
        "title": "Synthetic authentication observation", "account": "TRAINING", "device": device,
        "outcome": outcome, "occurred_at": (anchor + timedelta(minutes=i)).isoformat(),
    } for i, device, outcome in [(0, "old", "success"), (1, "new", "failure"), (2, "new", "failure"),
                                 (3, "new", "failure"), (4, "new", "success")]]
    receipt = batch(security, "pg-auth-01", auth + [{"record_type": "asset"}], token)
    assert (receipt["accepted"], receipt["rejected"], receipt["status"]) == (5, 1, "partial")
    assert batch(security, "pg-auth-01", auth + [{"record_type": "asset"}], token)["id"] == receipt["id"]
    wait_for_worker(token, 5)
    alerts = request("/security-alerts", token=token)
    assert any("failed" in alert["title"].lower() for alert in alerts)
    assert any("unfamiliar" in alert["title"].lower() for alert in alerts)
    refunds = [{
        "record_type": "refund", "external_id": f"refund-{i}", "account": "training", "device": "new",
        "occurred_at": (anchor + timedelta(minutes=i)).isoformat(), "currency": "USD", "amount_minor": 1250,
    } for i in range(5, 8)]
    processed = batch(commerce, "pg-refunds-01", refunds, token)
    assert processed["accepted"] == 3
    assert all(item["last_accepted_at"] for item in request("/data-sources", token=token))
    assert request("/data-sources", token=foreign) == []
    final_refund = processed["results"][-1]["record_id"]
    findings = request("/commerce/findings", token=token)
    finding = next(item for item in findings if item["refund_id"] == final_refund)
    assert finding["score"] == 100
    request(f"/commerce/findings/{finding['id']}/sources", token=foreign, expected=404)
    scenario_path = f"/commerce/findings/{finding['id']}/scenarios"
    scenario = request(scenario_path, "POST", {"scenario": "exclude_device"}, token, expected=201)
    assert scenario["hypothetical"] and scenario["original"]["score"] == 100 and scenario["adjusted"]["score"] == 65
    assert request(scenario_path, token=token)[0]["id"] == scenario["id"]
    path = f"/commerce/findings/{finding['id']}/incident"
    incident = request(path, "POST", token=token)
    assert request(path, "POST", token=token)["incident_id"] == incident["incident_id"]
    records = request(f"/incidents/{incident['incident_id']}/security-events", token=token)
    assert len(records) == 5 and len(request("/incidents", token=token)) == 1
    graph = request(f"/intelligence/graph?focus_id={incident['graph_entity_id']}", token=token)
    assert len(graph["relationships"]) == 8
    verify_web_proxy(credentials, finding["id"])
    print("PostgreSQL intake, partial failure, replay, worker processing, refund correlation, counterfactual, tenant checks and incident graph verified.")
    return token, commerce, anchor, incident, finding, graph


if __name__ == "__main__":
    verify()
