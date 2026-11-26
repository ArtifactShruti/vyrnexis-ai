from datetime import timedelta

from app.models import SecurityEvent, WorkflowStudio, utc_now_naive
from app.workflow_engine import advance_one, schedule_one
from test_api import register


ROOT = "/api/v1/workflow-studio"


def create(client, auth, template=None):
    result = client.post(f"{ROOT}/workflows", headers=auth, json={"name": "Synthetic review", "template": template})
    assert result.status_code == 201, result.text
    return f"{ROOT}/workflows/{result.json()['id']}", result.json()


def node(key, kind, **details):
    return {"id": key, "kind": kind, "label": key, "x": 30, "y": 50, **details}


def test_published_graph_approval_and_idempotent_replay(client):
    _, auth = register(client, "workflow-owner")
    _, foreign = register(client, "workflow-foreign")
    path, row = create(client, auth)
    assert client.get(path, headers=foreign).status_code == 404
    graph = {"nodes": [node("start", "manual"), node("condition", "condition", fact="review", equals=True),
                       node("gate", "approval"), node("skip", "summary")],
             "edges": [{"source": "start", "target": "condition"},
                       {"source": "condition", "target": "gate", "branch": "true"},
                       {"source": "condition", "target": "skip", "branch": "false"}]}
    cyclic = graph | {"edges": graph["edges"] + [{"source": "gate", "target": "condition"}]}
    assert client.post(f"{ROOT}/validate", headers=auth, json=cyclic).status_code == 422
    saved = client.put(path, headers=auth, json={"revision": row["revision"], "name": row["name"], "graph": graph})
    assert saved.status_code == 200, saved.text
    assert client.put(path, headers=auth, json={"revision": row["revision"], "name": row["name"], "graph": graph}).status_code == 409
    published = client.post(f"{path}/publish", headers=auth, json={"revision": saved.json()["revision"]})
    assert published.status_code == 200 and published.json()["published_version"] == 1, published.text
    payload = {"request_key": "manual-review-01", "dry_run": False, "facts": {"review": True}}
    initial = client.post(f"{path}/executions", headers=auth, json=payload)
    assert initial.status_code == 201, initial.text
    run = initial.json()
    assert run["status"] == "waiting_approval"
    assert client.post(f"{path}/executions", headers=auth, json=payload).json()["id"] == run["id"]
    assert client.post(f"{path}/executions", headers=auth, json=payload | {"facts": {"review": False}}).status_code == 409
    detail = f"{ROOT}/executions/{run['id']}"
    assert client.post(f"{detail}/approvals/gate", headers=foreign,
                       json={"decision": "approved", "note": "Foreign result"}).status_code == 404
    cancelled = client.post(f"{detail}/cancel", headers=auth)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    replay = client.post(f"{detail}/replay", headers=auth, json={"request_key": "replay-authorization-01"})
    assert replay.status_code == 201, replay.text
    child = replay.json()
    assert child["parent_id"] == run["id"] and child["status"] == "waiting_approval"
    approved = client.post(f"{ROOT}/executions/{child['id']}/approvals/gate", headers=auth,
                           json={"decision": "approved", "note": "Reviewed the synthetic workflow."})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "completed"
    assert {item["node_id"]: item["status"] for item in approved.json()["steps"]}["skip"] == "skipped"
    assert client.get(detail, headers=auth).json()["status"] == "cancelled"
    assert client.post(f"{detail}/replay", headers=auth, json={"request_key": "replay-authorization-01"}).json()["id"] == child["id"]


def test_scheduler_persists_one_due_run_and_worker_resumes(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "worker")
    _, auth = register(client, "workflow-schedule")
    path, row = create(client, auth, template="summary")
    published = client.post(f"{path}/publish", headers=auth, json={"revision": row["revision"]})
    assert published.status_code == 200, published.text
    factory = client.app.state.test_session_factory
    with factory.begin() as db:
        db.get(WorkflowStudio, row["id"]).next_due = utc_now_naive() - timedelta(minutes=1)
    assert schedule_one(factory) and not schedule_one(factory)
    runs = client.get(f"{ROOT}/executions", headers=auth).json()
    assert len(runs) == 1 and runs[0]["mode"] == "scheduled" and runs[0]["status"] == "queued"
    run_id = runs[0]["id"]
    assert advance_one(run_id, factory)
    assert client.get(f"{ROOT}/executions/{run_id}", headers=auth).json()["status"] == "running"
    assert advance_one(run_id, factory)
    assert advance_one(run_id, factory)
    assert not advance_one(run_id, factory)
    final = client.get(f"{ROOT}/executions/{run_id}", headers=auth).json()
    assert final["status"] == "completed"
    assert any(step["output"] == {"incidents": 0, "refund_findings": 0} for step in final["steps"])


def test_event_trigger_delivers_only_new_tenant_events_once(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_DETECTION_MODE", "worker")
    owner, auth = register(client, "workflow-events")
    other, _ = register(client, "workflow-events-foreign")
    factory = client.app.state.test_session_factory

    def event(organization):
        return SecurityEvent(organization_id=organization["id"], source="synthetic", event_type="authentication",
                             title="Synthetic event trigger")

    with factory.begin() as db:
        db.add(event(owner["organization"]))
    path, flow = create(client, auth, template="security-event")
    result = client.post(f"{path}/publish", headers=auth, json={"revision": flow["revision"]})
    assert result.status_code == 200, result.text
    with factory.begin() as db:
        studio = db.get(WorkflowStudio, flow["id"])
        studio.next_due = utc_now_naive() - timedelta(seconds=1)
        db.add(event(other["organization"]))
    assert schedule_one(factory)
    assert client.get(f"{ROOT}/executions", headers=auth).json() == []
    with factory.begin() as db:
        db.get(WorkflowStudio, flow["id"]).next_due = utc_now_naive() - timedelta(seconds=1)
        new = event(owner["organization"])
        db.add(new)
        db.flush()
        event_id = new.id
    assert schedule_one(factory)
    run = client.get(f"{ROOT}/executions", headers=auth).json()[0]
    assert run["mode"] == "event"
    for _ in range(3):
        assert advance_one(run["id"], factory)
    detail = f"{ROOT}/executions/{run['id']}"
    data = client.get(detail, headers=auth).json()
    assert data["status"] == "waiting_approval"
    assert any(step["output"] == {"trigger": "event", "event_id": event_id} for step in data["steps"])
    assert client.post(f"{detail}/approvals/step-2", headers=auth, json={
        "decision": "approved", "note": "Checked synthetic context",
    }).status_code == 200
    assert advance_one(run["id"], factory)
    with factory.begin() as db:
        db.get(WorkflowStudio, flow["id"]).next_due = utc_now_naive() - timedelta(seconds=1)
    assert schedule_one(factory)
    assert len(client.get(f"{ROOT}/executions", headers=auth).json()) == 1
