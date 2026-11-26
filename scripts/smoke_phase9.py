"""Exercise workflow, dependency simulation, and recorded commerce on both local stacks."""
from http.cookies import SimpleCookie
import json
import time

from smoke_forensics import api, exchange, tenant
from smoke_postgres import compose


WF = "/workflow-studio"
TWIN = "/digital-twin"
BI = "/business-intelligence"
DATES = "?start=2026-11-25&end=2026-11-25"


def await_run(path, token, port, state):
    deadline = time.monotonic() + 55
    while time.monotonic() < deadline:
        run = api(path, token=token, port=port)
        if run["status"] == state:
            return run
        if run["status"] in {"failed", "cancelled", "timed_out"}:
            raise RuntimeError(f"Workflow reached {run['status']}: {run['error']}")
        time.sleep(1)
    raise RuntimeError(f"Workflow did not reach {state} before the deadline")


def pipeline(owner, port, *, interrupt=False, incident_id=None):
    token, org = owner["access_token"], owner["organization"]["id"]
    if incident_id is None:
        incident = api("/incidents", "POST", {"organization_id": org, "title": "Synthetic Phase 9 incident",
            "severity": "high", "description": "Synthetic integrated workflow fixture."}, token, port=port)
        incident_id = incident["id"]
    workflow = api(WF + "/workflows", "POST", {"name": "Synthetic incident approval", "template": "incident"},
                   token, expected=201, port=port)
    path = f"{WF}/workflows/{workflow['id']}"
    api(path + "/publish", "POST", {"revision": workflow["revision"]}, token, port=port)
    payload = {"request_key": "phase9-start-fixture", "facts": {"incident_id": incident_id}, "dry_run": False}
    if interrupt:
        compose("stop", "worker")
    try:
        run = api(path + "/executions", "POST", payload, token, expected=201, port=port)
        assert api(path + "/executions", "POST", payload, token, expected=201, port=port)["id"] == run["id"]
        if interrupt:
            assert run["status"] == "queued"
    finally:
        if interrupt:
            compose("start", "worker")
    detail = f"{WF}/executions/{run['id']}"
    waiting = await_run(detail, token, port, "waiting_approval")
    assert any(step["output"] and step["output"].get("incident_id") == incident_id for step in waiting["steps"])
    gate = waiting["approvals"][0]["node_id"]
    api(f"{detail}/approvals/{gate}", "POST", {"decision": "approved", "note": "Synthetic approval test."}, token, port=port)
    done = await_run(detail, token, port, "completed")
    assert all(step["status"] == "completed" for step in done["steps"])
    if interrupt:
        template = api(WF + "/workflows", "POST", {"name": "Synthetic event trigger", "template": "security-event"},
                       token, expected=201, port=port)
        event_path = f"{WF}/workflows/{template['id']}"
        api(event_path + "/publish", "POST", {"revision": template["revision"]}, token, port=port)
        event = api("/security-events", "POST", {"organization_id": org, "title": "Synthetic workflow trigger",
                   "source": "phase9-smoke", "event_type": "authentication", "external_id": "phase9-workflow-event",
                   "account": "synthetic", "outcome": "failure"}, token, port=port)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            runs = api(WF + f"/executions?workflow_id={template['id']}", token=token, port=port)
            if runs:
                break
            time.sleep(1)
        else:
            raise RuntimeError("The new tenant event did not trigger a workflow")
        event_run = await_run(f"{WF}/executions/{runs[0]['id']}", token, port, "waiting_approval")
        assert event_run["mode"] == "event"
        assert any(step["output"] and step["output"].get("event_id") == event["id"] for step in event_run["steps"])
        api(f"{WF}/executions/{runs[0]['id']}/cancel", "POST", token=token, port=port)
    return done["id"]


def topology(owner, foreign, port, *, host_id=None):
    org, token = owner["organization"]["id"], owner["access_token"]

    def entity(label, kind):
        return api("/intelligence/entities", "POST", {"organization_id": org, "entity_type": kind,
            "external_id": f"phase9-{kind}", "display_name": label}, token, port=port)["id"]

    host = host_id or entity("Synthetic host", "device")
    app = entity("Synthetic application", "application")
    edge = api(TWIN + "/dependencies", "POST", {"dependent_id": app, "prerequisite_id": host,
        "kind": "depends_on", "confidence": .95, "reason": "Synthetic fixture dependency"}, token, expected=201, port=port)
    original = api(TWIN + "/topology", token=token, port=port)
    result = api(TWIN + "/simulations", "POST", {"title": "Synthetic outage", "target_id": host,
        "scenario_type": "outage", "depth": 4, "request_key": "phase9-outage", "assumption": "Host unavailable.",
        "excluded_dependencies": [edge["id"]]}, token, expected=201, port=port)
    assert result["result"]["baseline"]["direct"] == 1 and result["result"]["alternative"]["direct"] == 0
    assert api(TWIN + "/topology", token=token, port=port) == original
    api(TWIN + f"/simulations/{result['id']}", token=foreign["access_token"], expected=404, port=port)
    assert api(TWIN + f"/simulations/{result['id']}/export", token=token, port=port)["topology_digest"] == original["digest"]
    return result["id"]


def business(owner, foreign, port):
    token = owner["access_token"]
    source = api("/data-sources", "POST", {"name": "Synthetic Phase 9 commerce", "kind": "commerce"},
                 token, expected=201, port=port)
    rows = [{"record_type": kind, "external_id": f"phase9-{index}", "account": "synthetic",
             "currency": currency, "amount_minor": amount, "occurred_at": "2026-11-25T01:00:00Z"}
            for index, (kind, currency, amount) in enumerate([("payment", "USD", 2000), ("refund", "USD", 300),
                                                               ("payment", "EUR", 400)])]
    status, data, _ = exchange(f"/data-sources/{source['id']}/batches", "POST", {"version": 1, "records": rows},
                                token, port=port, headers={"Idempotency-Key": "phase9-analytics-fixture"})
    assert status == 200 and json.loads(data)["accepted"] == 3
    result = api(BI + "/report" + DATES, token=token, port=port)
    by_currency = {item["currency"]: item for item in result["summary"]}
    assert by_currency["USD"]["net_recorded_minor"] == "1700" and by_currency["EUR"]["paid_minor"] == "400"
    assert api(BI + "/report" + DATES, token=foreign["access_token"], port=port)["summary"] == []


def verify_proxy(credentials):
    proxy = "/api/workspace" + BI + "/report" + DATES
    assert exchange(proxy, port=3001)[0] == 401
    status, _, headers = exchange("/api/auth/login", "POST", credentials, port=3001)
    assert status == 200
    cookie = SimpleCookie()
    for name, value in headers:
        if name.lower() == "set-cookie":
            cookie.load(value)
    access = cookie["vyrnexis_access"]
    assert access["httponly"]
    headers = {"Cookie": f"vyrnexis_access={access.value}"}
    status, data, _ = exchange(proxy, port=3001, headers=headers)
    assert status == 200 and len(json.loads(data)["summary"]) == 2
    assert exchange("/api/workspace/workflow-studio/workflows", "POST", {"name": "Blocked"},
                    port=3001, headers=headers | {"Origin": "https://foreign.example"})[0] == 403


def verify():
    assert "(head)" in compose("exec", "-T", "api", "python", "-m", "alembic", "current")
    compose("exec", "-T", "api", "python", "-m", "alembic", "check")
    for port in (8001, 8002):
        owner, credentials = tenant(port)
        foreign, _ = tenant(port)
        pipeline(owner, port, interrupt=port == 8002)
        topology(owner, foreign, port)
        business(owner, foreign, port)
        fallback = api("/knowledge/search/hybrid", "POST", {"query": "synthetic policy",
            "acknowledge_local_processing": True}, owner["access_token"], port=port)
        assert fallback["method"] == "keyword" and fallback["sources"] == []
        if port == 8002:
            verify_proxy(credentials)
    print("Both stacks verified workflow approval, dependency simulation isolation, currency-aware analytics, and authenticated web access.")
    print("PostgreSQL verified queued workflow recovery, a tenant-event trigger, and migration head.")


if __name__ == "__main__":
    verify()
