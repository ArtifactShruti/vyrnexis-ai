import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select

from app.models import AuditLog, DetectionAlert, DetectionRule, Incident, SecurityEvent, User


def submit_auth_event(client, headers, org_id, key, stamp, *, device="known", outcome="failure", account="test-account"):
    return client.post("/api/v1/security-events", headers=headers, json={
        "organization_id": org_id, "source": "Synthetic Test Feed", "event_type": "authentication",
        "external_id": key, "title": "Synthetic authentication record", "account": account,
        "device": device, "outcome": outcome, "occurred_at": stamp,
    })


def test_detection_deduplication_confirmation_and_graph(client):
    principal, headers = register(client, "detect")
    other, other_headers = register(client, "detect-other")
    org_id = principal["organization"]["id"]
    rule = "/api/v1/detection-rules/failed_signins"
    settings = {"threshold": 3, "window_minutes": 15, "severity": "high"}
    assert client.put(rule, json=settings).status_code == 401
    assert client.put(rule, headers=headers, json=settings).status_code == 200
    assert client.get("/api/v1/detection-rules", headers=other_headers).json() == []
    assert submit_auth_event(client, other_headers, other["organization"]["id"], "test-1",
                             "2026-11-25T02:01:00Z").status_code == 200

    sample = submit_auth_event(client, headers, org_id, "test-1", "2026-11-25T02:01:00Z")
    assert sample.status_code == 200, sample.text
    retry = submit_auth_event(client, headers, org_id, "test-1", "2026-11-25T02:01:00Z")
    assert retry.json()["id"] == sample.json()["id"]
    assert submit_auth_event(client, headers, org_id, "test-1", "2026-11-25T02:01:00Z",
                             device="updated").status_code == 409
    ids = {sample.json()["id"]}
    for i in range(2, 5):
        response = submit_auth_event(client, headers, org_id, f"test-{i}", f"2026-11-25T02:0{i}:00Z")
        assert response.status_code == 200, response.text
        ids.add(response.json()["id"])
        if i == 2:
            assert client.get("/api/v1/security-alerts", headers=headers).json() == []
    alerts = client.get("/api/v1/security-alerts", headers=headers).json()
    assert len(alerts) == 1
    alert = f"/api/v1/security-alerts/{alerts[0]['id']}"
    assert client.get(f"{alert}/events", headers=other_headers).status_code == 404
    assert client.post(f"{alert}/incident", headers=other_headers).status_code == 404
    assert client.get("/api/v1/detection-runs", headers=other_headers).json() == []
    assert len(client.get("/api/v1/detection-runs", headers=headers).json()) == 4
    assert {event["id"] for event in client.get(f"{alert}/events", headers=headers).json()} == ids
    confirmed = client.post(f"{alert}/incident", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    incident = confirmed.json()["incident_id"]
    assert client.post(f"{alert}/incident", headers=headers).json()["incident_id"] == incident
    assert len(client.get("/api/v1/incidents", headers=headers).json()) == 1
    assert client.get(f"/api/v1/incidents/{incident}/security-events", headers=other_headers).status_code == 404
    assert {event["id"] for event in client.get(f"/api/v1/incidents/{incident}/security-events", headers=headers).json()} == ids
    assert client.patch(f"/api/v1/incidents/{incident}/status", headers=headers,
                        json={"status": "investigating"}).status_code == 200
    assert client.get("/api/v1/security-alerts", headers=headers).json()[0]["incident_status"] == "investigating"
    graph = client.get("/api/v1/intelligence/graph", headers=headers).json()
    assert len(graph["relationships"]) >= 4
    assert "supported_by" in {edge["relationship_type"] for edge in graph["relationships"]}


def test_device_baseline_and_alert_feedback(client):
    principal, headers = register(client, "devices")
    org_id = principal["organization"]["id"]
    rule = "/api/v1/detection-rules/unfamiliar_device"
    assert client.put(rule, headers=headers, json={"window_minutes": 30}).status_code == 200
    for index, minute, device in [(1, "00", "A"), (2, "04", "a"), (3, "12", "B")]:
        result = submit_auth_event(client, headers, org_id, str(index), f"2026-11-25T02:{minute}:00Z",
                                   device=device, outcome="success")
        assert result.status_code == 200, result.text
        if index < 3:
            assert not client.get("/api/v1/security-alerts", headers=headers).json()
    alerts = client.get("/api/v1/security-alerts", headers=headers).json()
    assert len(alerts) == 1
    alert = f"/api/v1/security-alerts/{alerts[0]['id']}"
    assert client.post(f"{alert}/false-positive", headers=headers,
                       json={"note": "Approved workstation replacement"}).status_code == 200
    assert client.post(f"{alert}/incident", headers=headers).status_code == 409
    with client.app.state.test_session_factory() as db:
        db.get(User, principal["user"]["id"]).role = "viewer"
        db.commit()
    assert client.get("/api/v1/security-alerts", headers=headers).json()[0]["status"] == "false_positive"
    assert client.put(rule, headers=headers, json={"enabled": False}).status_code == 403
    assert client.post(f"{alert}/incident", headers=headers).status_code == 403


def register(client, label="test"):
    suffix = uuid.uuid4().hex
    response = client.post("/api/v1/auth/register", json={
        "organization_name": f"{label} Organization",
        "organization_slug": f"{label}-{suffix}",
        "full_name": "Test Administrator",
        "email": f"admin-{suffix}@example.org",
        "password": "A-secure-password-123",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def test_missing_admin_workspaces_are_tenant_scoped(client):
    owner, auth = register(client, "phase10-admin")
    _, foreign = register(client, "phase10-admin-foreign")
    created = client.post("/api/v1/admin/users", headers=auth, json={
        "full_name": "Synthetic Viewer",
        "email": f"phase10-{uuid.uuid4().hex}@example.org",
        "password": "A-secure-password-123",
        "role": "viewer",
    })
    assert created.status_code == 201, created.text
    viewer_id = created.json()["id"]
    assert len(client.get("/api/v1/admin/users", headers=auth).json()) == 2
    foreign_users = client.get("/api/v1/admin/users", headers=foreign)
    assert foreign_users.status_code == 200
    assert len(foreign_users.json()) == 1
    assert foreign_users.json()[0]["id"] != viewer_id
    assert client.put(f"/api/v1/admin/users/{owner['user']['id']}", headers=auth,
                      json={"is_active": False}).status_code == 409
    assert client.put(f"/api/v1/admin/users/{viewer_id}", headers=auth,
                      json={"is_active": False}).status_code == 200
    assert client.get("/api/v1/admin/audit", headers=auth).status_code == 200
    assert client.get("/api/v1/admin/notifications", headers=auth).status_code == 200
    assert client.get("/api/v1/admin/threat-intelligence", headers=auth).json()["entities"] == []
    assert client.get("/api/v1/admin/integrations", headers=auth).json() == []
    platform = client.get("/api/v1/admin/platform", headers=auth)
    assert platform.status_code == 200
    assert platform.json()["organization"]["id"] == owner["organization"]["id"]
    assert platform.json()["scope"] == "organization"


def test_organization_configuration_and_role_matrix(client):
    _, auth = register(client, "phase10-settings")
    _, foreign = register(client, "phase10-settings-foreign")
    settings = client.get("/api/v1/admin/organization", headers=auth)
    assert settings.status_code == 200
    assert settings.json()["timezone"] == "UTC"
    updated = client.put("/api/v1/admin/organization", headers=auth, json={
        "name": "Synthetic configured organization",
        "timezone": "Asia/Kolkata",
        "currency": "inr",
        "industry": "Financial services",
        "branding": {"wordmark": "Synthetic"},
        "settings": {"notifications": True},
        "onboarding": {"profileComplete": True, "teamReady": False, "securityReady": False},
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["currency"] == "INR"
    assert updated.json()["onboarding"]["profileComplete"] is True
    assert client.get("/api/v1/admin/organization", headers=foreign).status_code == 200
    foreign_org = client.get("/api/v1/admin/organization", headers=foreign).json()
    assert foreign_org["name"] != "Synthetic configured organization"
    assert client.get("/api/v1/admin/role-matrix", headers=auth).status_code == 200
    assert client.get("/api/v1/admin/role-matrix", headers=foreign).status_code == 200


def create_source(client, auth, name, kind):
    response = client.post("/api/v1/data-sources", headers=auth, json={"name": name, "kind": kind})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_batch_receipts_source_key_scope_and_partial_results(client):
    _, owner = register(client, "intake")
    _, foreign = register(client, "intake-foreign")
    source = create_source(client, owner, "Device inventory", "assets")
    other = create_source(client, foreign, "Foreign inventory", "assets")
    path = f"/api/v1/data-sources/{source}/batches"
    assert client.get(path, headers=foreign).status_code == 404
    assert client.post(path, headers={"Idempotency-Key": "assets-001"}, json={"version": 1, "records": [{}]}).status_code == 401
    headers = owner | {"Idempotency-Key": "assets-001"}
    asset = {"record_type": "asset", "external_id": "device-a", "name": "Synthetic device",
             "asset_type": "workstation", "occurred_at": "2026-11-25T10:00:00Z"}
    payload = {"version": 1, "records": [asset, asset, asset | {"external_id": "invalid", "unexpected": "do-not-echo"}]}
    first = client.post(path, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    batch = first.json()
    assert (batch["accepted"], batch["duplicate"], batch["rejected"], batch["status"]) == (1, 1, 1, "partial")
    assert "do-not-echo" not in first.text
    assert client.post(path, headers=headers, json=payload).json()["id"] == batch["id"]
    assert client.post(path, headers=headers, json={"version": 1, "records": [asset]}).status_code == 409
    assert len(client.get("/api/v1/assets", headers=owner).json()) == 1
    assert client.get(f"{path}/{batch['id']}", headers=foreign).status_code == 404
    assert client.post(path, headers=headers | {"Content-Type": "text/csv"}, content=b"x" * (512 * 1024 + 1)).status_code == 413
    assert client.post(path, headers=headers | {"Content-Type": "text/csv"}, content="schema_version,schema_version\n1,1").status_code == 422

    api_keys = f"/api/v1/data-sources/{source}/keys"
    key = client.post(api_keys, headers=owner, json={"label": "Local synthetic test", "expires_in_days": 1}).json()
    assert "key" not in client.get(api_keys, headers=owner).json()[0]
    assert client.get(api_keys, headers=foreign).status_code == 404
    webhook_headers = {"X-Ingestion-Key": key["key"], "Idempotency-Key": "webhook-batch-001"}
    assert client.post(f"/api/v1/ingestion/webhooks/{other}", headers=webhook_headers, json=payload).status_code == 401
    assert client.post(f"/api/v1/ingestion/webhooks/{source}", headers=webhook_headers, json=payload).json()["duplicate"] == 2
    assert client.get("/api/v1/data-sources", headers={"Authorization": f"Bearer {key['key']}"}).status_code == 401
    assert client.post(f"{api_keys}/{key['id']}/revoke", headers=owner).status_code == 200
    assert client.post(f"/api/v1/ingestion/webhooks/{source}", headers=webhook_headers, json=payload).status_code == 401


def test_batch_rate_limit_keeps_prior_replies_available(client, monkeypatch):
    from app import ingestion

    monkeypatch.setattr(ingestion, "MAX_BATCHES_PER_MINUTE", 2)
    _, auth = register(client, "batch-rate")
    source = create_source(client, auth, "Rate limit test source", "assets")
    other = create_source(client, auth, "Independent source", "assets")
    path = f"/api/v1/data-sources/{source}/batches"
    payload = {"version": 1, "records": [
        {"record_type": "asset", "external_id": "one", "name": "Synthetic asset", "asset_type": "server",
         "occurred_at": "2026-11-25T10:00:00Z"},
    ]}
    first = client.post(path, headers=auth | {"Idempotency-Key": "rate-test-01"}, json=payload)
    assert first.status_code == 200
    assert client.post(path, headers=auth | {"Idempotency-Key": "rate-test-02"}, json=payload).status_code == 200
    denied = client.post(path, headers=auth | {"Idempotency-Key": "rate-test-03"}, json=payload)
    assert denied.status_code == 429 and denied.headers["retry-after"] == "60"
    assert client.post(path, headers=auth | {"Idempotency-Key": "rate-test-01"}, json=payload).json()["id"] == first.json()["id"]
    assert client.post(f"/api/v1/data-sources/{other}/batches",
                       headers=auth | {"Idempotency-Key": "rate-test-03"}, json=payload).status_code == 200


def test_refunds_match_authentication_and_create_one_tenant_incident(client):
    principal, auth = register(client, "commerce")
    _, foreign = register(client, "commerce-foreign")
    security = create_source(client, auth, "Synthetic authentication feed", "security")
    commerce = create_source(client, auth, "Synthetic refund feed", "commerce")
    evidence_id = client.post("/api/v1/evidence", headers=auth, params={
        "organization_id": principal["organization"]["id"], "name": "synthetic evidence.json",
    }, files={"file": ("evidence.json", b"{}", "application/json")}).json()["id"]
    assert client.put("/api/v1/commerce/policy", headers=auth, json={"window_minutes": 20}).status_code == 200
    samples = [(0, "success", "prior"), (1, "failure", "new"), (2, "failure", "new"),
               (3, "failure", "new"), (4, "success", "new")]
    events = [{
        "record_type": "security", "external_id": f"auth-{i}", "event_type": "authentication",
        "title": "Synthetic sign-in observation", "account": "ACCT-9", "device": device, "outcome": outcome,
        "occurred_at": f"2026-11-25T10:0{i}:00Z",
    } for i, outcome, device in samples]
    ingestion = client.post(f"/api/v1/data-sources/{security}/batches",
                            headers=auth | {"Idempotency-Key": "synthetic-auth-001"}, json={"version": 1, "records": events})
    assert ingestion.status_code == 200 and ingestion.json()["accepted"] == 5, ingestion.text
    path = f"/api/v1/data-sources/{commerce}/batches"
    content = "schema_version,record_type,external_id,occurred_at,account,device,currency,amount_minor,evidence_id\n"
    content += "\n".join(f"1,refund,refund-{i},2026-11-25T10:0{i}:00Z,acct-9,new,usd,1250,{evidence_id if i == 7 else ''}" for i in range(5, 8))
    receipt = client.post(path, headers=auth | {"Idempotency-Key": "synthetic-refunds-001", "Content-Type": "text/csv"}, content=content)
    assert receipt.status_code == 200 and receipt.json()["accepted"] == 3, receipt.text
    refund_id = receipt.json()["results"][2]["record_id"]
    assert client.get("/api/v1/commerce/totals", headers=auth).json() == [
        {"currency": "USD", "count": 3, "kind": "refund", "amount_minor": "3750"},
    ]
    assert client.get("/api/v1/commerce/findings", headers=foreign).json() == []
    assert client.post(f"/api/v1/commerce/refunds/{refund_id}/evaluate", headers=foreign).status_code == 404
    finding = next(row for row in client.get("/api/v1/commerce/findings", headers=auth).json() if row["refund_id"] == refund_id)
    assert finding["score"] == 100 and len(finding["factors"]) == 3
    base = f"/api/v1/commerce/findings/{finding['id']}"
    assert client.get(f"{base}/sources", headers=foreign).status_code == 404
    assert client.post(f"{base}/incident", headers=foreign).status_code == 404
    report = client.get(f"{base}/sources", headers=auth).json()
    assert len(report["refunds"]) == 3 and len(report["security_events"]) == 5
    assert report["evidence"][0]["id"] == evidence_id
    scenarios = f"{base}/scenarios"
    assert client.get(scenarios, headers=foreign).status_code == 404
    assert client.post(scenarios, headers=foreign, json={"scenario": "exclude_device"}).status_code == 404
    assert client.post(scenarios, headers=auth, json={"scenario": "exclude_event", "event_id": "nonexistent"}).status_code == 404
    failed_signin = ingestion.json()["results"][1]["record_id"]
    for value, score, removed in [
        ({"scenario": "exclude_device"}, 65, {"unfamiliar_refund_device"}),
        ({"scenario": "legitimate_refund"}, 30, {"unfamiliar_refund_device", "refund_frequency"}),
        ({"scenario": "exclude_event", "event_id": failed_signin}, 70, {"failed_signins"}),
        ({"scenario": "adjust_thresholds", "policy": {"window_minutes": 20, "refund_threshold": 4, "failure_threshold": 4}},
         35, {"refund_frequency", "failed_signins"}),
    ]:
        response = client.post(scenarios, headers=auth, json=value)
        assert response.status_code == 201, response.text
        scenario = response.json()
        assert scenario["hypothetical"] and scenario["current_baseline"]["score"] == scenario["original"]["score"] == 100
        assert scenario["adjusted"]["score"] == score
        assert set(scenario["removed_factors"]) == removed
    assert len(client.get(scenarios, headers=auth).json()) == 4
    assert client.get(f"{base}/sources", headers=auth).json() == report
    assert client.get("/api/v1/incidents", headers=auth).json() == []
    confirmed = client.post(f"{base}/incident", headers=auth)
    assert confirmed.status_code == 200, confirmed.text
    incident = confirmed.json()["incident_id"]
    assert client.post(f"{base}/incident", headers=auth).json()["incident_id"] == incident
    assert len(client.get("/api/v1/incidents", headers=auth).json()) == 1
    graph = client.get("/api/v1/intelligence/graph", headers=auth, params={"focus_id": confirmed.json()["graph_entity_id"]})
    assert graph.status_code == 200
    assert {row["relationship_type"] for row in graph.json()["relationships"]} == {"supported_by", "references_evidence"}
    assert client.get("/api/v1/intelligence/graph", headers=foreign,
                      params={"focus_id": confirmed.json()["graph_entity_id"]}).status_code == 404
    assert len(client.get(f"/api/v1/incidents/{incident}/security-events", headers=auth).json()) == 5
    mercury = client.post("/api/v1/agents/executions", headers=auth, json={"agent": "MERCURY", "incident_id": incident})
    assert mercury.status_code == 200 and f"commerce_finding:{finding['id']}" in mercury.json()["evidence"]
    veritas = client.post("/api/v1/agents/executions", headers=auth, json={"agent": "VERITAS", "incident_id": incident})
    assert veritas.status_code == 200 and "1 verified" in veritas.json()["finding"]
    with client.app.state.test_session_factory() as db:
        db.get(User, principal["user"]["id"]).role = "viewer"
        db.commit()
    assert client.post(path, headers=auth | {"Idempotency-Key": "viewer-001"}, json={"version": 1, "records": events}).status_code == 403
    assert client.post(f"{base}/incident", headers=auth).status_code == 403
    assert client.post(scenarios, headers=auth, json={"scenario": "exclude_device"}).status_code == 403


def test_health_and_protected_routes_require_authentication(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

    for path in (
        "/api/v1/auth/me",
        "/api/v1/dashboard",
        "/api/v1/incidents",
        "/api/v1/assets",
        "/api/v1/security-events",
        "/api/v1/intelligence/entities",
        "/api/v1/intelligence/graph",
        "/api/v1/intelligence/graph/bookmarks",
        "/api/v1/workflows",
        "/api/v1/evidence",
    ):
        assert client.get(path).status_code == 401

    assert client.post("/api/v1/intelligence/correlate").status_code == 401


def test_registration_login_and_tenant_intelligence(client):
    registered, auth = register(client)
    organization_id = registered["organization"]["id"]
    assert registered["user"]["role"] == "owner"

    login = client.post("/api/v1/auth/login", json={
        "email": registered["user"]["email"],
        "password": "A-secure-password-123",
    })
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert login.json()["refresh_token"]

    entity = client.post("/api/v1/intelligence/entities", headers=auth, json={
        "organization_id": organization_id,
        "entity_type": "user",
        "external_id": "USR-001",
        "display_name": "Test User",
        "properties": {"role": "analyst"},
    })
    assert entity.status_code == 200

    dashboard = client.get("/api/v1/dashboard", headers=auth)
    assert dashboard.status_code == 200
    assert dashboard.json()["intelligence_entities"] == 1
    assert dashboard.json()["organization"]["id"] == organization_id


def test_dashboard_activity_uses_utc_receipt_date_and_tenant_scope(client, monkeypatch):
    owner, auth = register(client, "activity")
    foreign, foreign_auth = register(client, "activity-foreign")
    org = owner["organization"]["id"]
    other_org = foreign["organization"]["id"]
    now = datetime(2026, 11, 26, 15)
    monkeypatch.setattr("app.main.utc_now_naive", lambda: now)

    with client.app.state.test_session_factory() as db:
        for organization_id, received in (
            (org, datetime(2026, 11, 25, 23, 59)), (org, datetime(2026, 11, 26)),
            (org, datetime(2026, 10, 27, 23, 59)), (other_org, now),
        ):
            db.add(SecurityEvent(organization_id=organization_id, source="Synthetic fixture",
                                 event_type="test", title="Fixture event", occurred_at=datetime(2026, 10, 1),
                                 received_at=received))
        rule = DetectionRule(organization_id=org, kind="failed_signins", severity="high",
                             window_minutes=15, threshold=3, enabled=True)
        db.add(rule)
        db.flush()
        db.add(DetectionAlert(organization_id=org, rule_id=rule.id, group_key="fixture", title="Fixture alert",
                              explanation="Synthetic rule fixture", severity="high", created_at=now))
        db.add(Incident(organization_id=org, title="Closed historical fixture", status="closed",
                        severity="medium", created_at=now))
        db.commit()

    response = client.get("/api/v1/dashboard", headers=auth)
    assert response.status_code == 200
    data = response.json()
    days = data["activity"]
    assert data["database"] == "sqlite" and data["active_incidents"] == 0
    assert len(days) == 30 and days[0]["date"] == "2026-10-28"
    assert days[-2:] == [
        {"date": "2026-11-25", "events": 1, "alerts": 0, "incidents": 0},
        {"date": "2026-11-26", "events": 1, "alerts": 1, "incidents": 1},
    ]
    assert not any(day["events"] or day["alerts"] or day["incidents"] for day in days[:-2])
    other_day = client.get("/api/v1/dashboard", headers=foreign_auth).json()["activity"][-1]
    assert other_day == {"date": "2026-11-26", "events": 1, "alerts": 0, "incidents": 0}


def test_cross_tenant_reads_and_writes_are_denied(client):
    tenant_a, auth_a = register(client, "alpha")
    tenant_b, auth_b = register(client, "bravo")
    org_a = tenant_a["organization"]["id"]
    org_b = tenant_b["organization"]["id"]

    # A token for tenant A cannot request tenant B by changing a query or body ID.
    assert client.get("/api/v1/dashboard", headers=auth_a, params={"organization_id": org_b}).status_code == 404
    assert client.get("/api/v1/incidents", headers=auth_a, params={"organization_id": org_b}).status_code == 404
    assert client.get("/api/v1/intelligence/entities", headers=auth_a, params={"organization_id": org_b}).status_code == 404
    assert client.get("/api/v1/workflows", headers=auth_a, params={"organization_id": org_b}).status_code == 404

    foreign_entity = client.post("/api/v1/intelligence/entities", headers=auth_b, json={
        "organization_id": org_b,
        "entity_type": "device",
        "external_id": "FOREIGN-1",
        "display_name": "Tenant B device",
    })
    assert foreign_entity.status_code == 200
    assert client.post("/api/v1/intelligence/entities", headers=auth_a, json={
        "organization_id": org_b,
        "entity_type": "device",
        "external_id": "INJECTED-1",
        "display_name": "Attempted cross-tenant write",
    }).status_code == 404
    assert client.post("/api/v1/incidents", headers=auth_a, json={
        "organization_id": org_b,
        "title": "Attempted cross-tenant incident",
    }).status_code == 404
    assert client.post("/api/v1/workflows", headers=auth_a, json={
        "organization_id": org_b,
        "name": "Attempted cross-tenant workflow",
    }).status_code == 404
    foreign_incident = client.post("/api/v1/incidents", headers=auth_b, json={
        "organization_id": org_b,
        "title": "Tenant B investigation",
    })
    assert foreign_incident.status_code == 200
    assert client.post(
        "/api/v1/evidence",
        headers=auth_a,
        params={
            "organization_id": org_a,
            "investigation_id": foreign_incident.json()["id"],
            "name": "cross-tenant-attachment.log",
        },
        files={"file": ("note.log", b"test", "text/plain")},
    ).status_code == 404
    foreign_evidence = client.post(
        "/api/v1/evidence",
        headers=auth_b,
        params={"organization_id": org_b, "name": "tenant-b.log"},
        files={"file": ("tenant-b.log", b"tenant b evidence", "text/plain")},
    ).json()
    assert client.get(f"/api/v1/evidence/{foreign_evidence['id']}/download", headers=auth_a).status_code == 404
    assert client.post(f"/api/v1/evidence/{foreign_evidence['id']}/verify", headers=auth_a).status_code == 404
    assert client.get(f"/api/v1/evidence/{foreign_evidence['id']}/activity", headers=auth_a).status_code == 404

    # A relationship cannot smuggle a tenant B entity into tenant A's graph.
    own_entity = client.post("/api/v1/intelligence/entities", headers=auth_a, json={
        "organization_id": org_a,
        "entity_type": "device",
        "external_id": "OWN-1",
        "display_name": "Tenant A device",
    }).json()
    assert client.post("/api/v1/intelligence/relationships", headers=auth_a, json={
        "organization_id": org_a,
        "source_id": foreign_entity.json()["id"],
        "target_id": own_entity["id"],
        "relationship_type": "cross_tenant_injection",
        "confidence": 0.9,
    }).status_code == 404


def test_viewer_cannot_write_and_successful_changes_are_audited(client):
    registered, auth = register(client)
    created = client.post("/api/v1/incidents", headers=auth, json={
        "organization_id": registered["organization"]["id"],
        "title": "Authorized owner incident",
    })
    assert created.status_code == 200
    with client.app.state.test_session_factory() as db:
        user = db.scalar(select(User).where(User.id == registered["user"]["id"]))
        user.role = "viewer"
        db.commit()

    denied = client.post("/api/v1/incidents", headers=auth, json={
        "organization_id": registered["organization"]["id"],
        "title": "Viewer write should fail",
    })
    assert denied.status_code == 403
    assert client.post("/api/v1/agents/executions", headers=auth, json={
        "agent": "SENTINEL",
    }).status_code == 403

    # The owner registration already records both account and session creation.
    with client.app.state.test_session_factory() as db:
        actions = set(db.scalars(select(AuditLog.action)).all())
    assert "organization.register" in actions
    assert "auth.session.create" in actions
    assert "incident.create" in actions


def test_asset_inventory_is_persistent_tenant_scoped_and_role_checked(client):
    tenant_a, auth_a = register(client, "asset-alpha")
    tenant_b, auth_b = register(client, "asset-bravo")
    org_a = tenant_a["organization"]["id"]
    org_b = tenant_b["organization"]["id"]

    first = client.post("/api/v1/assets", headers=auth_a, json={
        "organization_id": org_a,
        "name": "Finance API cluster",
        "asset_type": "application",
        "identifier": "CMDB-104",
        "criticality": "high",
    })
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "active"

    foreign = client.post("/api/v1/assets", headers=auth_b, json={
        "organization_id": org_b,
        "name": "Tenant B workstation",
        "asset_type": "workstation",
        "identifier": "WS-22",
    })
    assert foreign.status_code == 200
    assert client.get("/api/v1/assets", headers=auth_a).json()[0]["id"] == first.json()["id"]
    assert client.get("/api/v1/assets", headers=auth_a, params={"search": "CMDB-104"}).json()[0]["id"] == first.json()["id"]
    assert client.get("/api/v1/assets", headers=auth_a, params={"status": "retired"}).json() == []
    assert client.get("/api/v1/assets", headers=auth_a, params={"organization_id": org_b}).status_code == 404
    assert client.post("/api/v1/assets", headers=auth_a, json={
        "organization_id": org_b,
        "name": "Cross-tenant asset",
        "asset_type": "server",
    }).status_code == 404
    asset_id = first.json()["id"]
    assigned = client.put(f"/api/v1/assets/{asset_id}/assignment", headers=auth_a, json={
        "assignee_id": tenant_a["user"]["id"], "team": "Finance operations",
    })
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignment"]["team"] == "Finance operations"
    lifecycle = client.put(f"/api/v1/assets/{asset_id}", headers=auth_a, json={"status": "maintenance"})
    assert lifecycle.status_code == 200
    assert lifecycle.json()["status"] == "maintenance"
    vulnerability = client.post(f"/api/v1/assets/{asset_id}/vulnerabilities", headers=auth_a, json={
        "title": "Synthetic outdated library", "cve": "CVE-2026-0001",
        "severity": "high", "status": "open",
    })
    assert vulnerability.status_code == 201, vulnerability.text
    remediated = client.put(
        f"/api/v1/assets/{asset_id}/vulnerabilities/{vulnerability.json()['id']}",
        headers=auth_a, json={"status": "mitigated"},
    )
    assert remediated.status_code == 200
    detail = client.get(f"/api/v1/assets/{asset_id}", headers=auth_a)
    assert detail.status_code == 200
    assert len(detail.json()["history"]) >= 3
    assert detail.json()["vulnerabilities"][0]["status"] == "mitigated"
    assert client.get(f"/api/v1/assets/{asset_id}", headers=auth_b).status_code == 404

    with client.app.state.test_session_factory() as db:
        user = db.scalar(select(User).where(User.id == tenant_a["user"]["id"]))
        user.role = "viewer"
        db.commit()
    assert client.post("/api/v1/assets", headers=auth_a, json={
        "organization_id": org_a,
        "name": "Viewer write attempt",
        "asset_type": "server",
    }).status_code == 403
    with client.app.state.test_session_factory() as db:
        assert "asset.create" in set(db.scalars(select(AuditLog.action)).all())


def test_incident_assignment_is_tenant_scoped_and_audited(client):
    tenant, auth = register(client, "incident-assignment")
    _, foreign = register(client, "incident-assignment-foreign")
    org = tenant["organization"]["id"]
    created = client.post("/api/v1/incidents", headers=auth, json={
        "organization_id": org, "title": "Assignment regression", "severity": "high",
        "description": "Synthetic assignment test",
    })
    assert created.status_code == 200, created.text
    incident_id = created.json()["id"]
    assigned = client.put(f"/api/v1/incidents/{incident_id}/assignment", headers=auth, json={
        "assignee_id": tenant["user"]["id"], "team": "Security operations",
    })
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignee_name"] == "Test Administrator"
    assert assigned.json()["team"] == "Security operations"
    assert client.put(f"/api/v1/incidents/{incident_id}/assignment", headers=foreign, json={
        "assignee_id": tenant["user"]["id"], "team": "Foreign",
    }).status_code == 404
    listed = client.get("/api/v1/incidents", headers=auth).json()
    assert listed[0]["assignee_id"] == tenant["user"]["id"]


def test_threat_indicators_are_persisted_tenant_scoped_and_matched(client):
    tenant, auth = register(client, "threat-indicators")
    _, foreign = register(client, "threat-indicators-foreign")
    created = client.post("/api/v1/threat-indicators", headers=auth, json={
        "indicator_type": "ip", "value": "203.0.113.42",
        "classification": "suspicious", "confidence": 72,
        "provenance": "Synthetic analyst feed", "notes": "Tenant-owned training indicator",
    })
    assert created.status_code == 201, created.text
    indicator_id = created.json()["id"]
    assert client.get("/api/v1/threat-indicators", headers=auth).json()[0]["id"] == indicator_id
    assert client.get(f"/api/v1/threat-indicators/{indicator_id}", headers=foreign).status_code == 404
    inspected = client.get(f"/api/v1/threat-indicators/{indicator_id}", headers=auth)
    assert inspected.status_code == 200
    assert inspected.json()["matches"]["security_events"] == []
    duplicate = client.post("/api/v1/threat-indicators", headers=auth, json={
        "indicator_type": "ip", "value": "203.0.113.42",
        "classification": "unknown", "confidence": 10,
    })
    assert duplicate.status_code == 409
    updated = client.patch(f"/api/v1/threat-indicators/{indicator_id}", headers=auth, json={
        "indicator_type": "ip", "value": "203.0.113.42",
        "classification": "benign", "confidence": 80,
        "provenance": "Analyst review", "notes": "Reclassified as benign",
    })
    assert updated.status_code == 200
    assert updated.json()["classification"] == "benign"


def test_report_center_generates_versions_previews_and_exports(client):
    owner, auth = register(client, "reports")
    _, foreign = register(client, "reports-foreign")
    created = client.post("/api/v1/reports", headers=auth, json={
        "title": "Synthetic security briefing",
        "category": "security",
        "source_module": "security",
    })
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]
    assert created.json()["version"] == 1
    repeat = client.post("/api/v1/reports", headers=auth, json={
        "title": "Synthetic security briefing",
        "category": "security",
        "source_module": "security",
    })
    assert repeat.status_code == 201
    assert repeat.json()["version"] == 2
    listing = client.get("/api/v1/reports?category=security&search=Synthetic", headers=auth)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert client.get(f"/api/v1/reports/{report_id}", headers=foreign).status_code == 404
    preview = client.get(f"/api/v1/reports/{report_id}", headers=auth)
    assert preview.status_code == 200
    assert preview.json()["snapshot"]["count"] == 0
    assert len(preview.json()["integrity_hash"]) == 64
    export = client.get(f"/api/v1/reports/{report_id}/export?format=json", headers=auth)
    assert export.status_code == 200
    assert export.json()["count"] == 0
    csv_export = client.get(f"/api/v1/reports/{report_id}/export?format=csv", headers=auth)
    assert csv_export.status_code == 200
    assert "field,value" in csv_export.text


def test_notifications_are_account_isolated_deduplicated_and_readable(client):
    owner, auth = register(client, "notifications")
    _, foreign = register(client, "notifications-foreign")
    org = owner["organization"]["id"]
    from app.models import Notification
    with client.app.state.test_session_factory.begin() as db:
        db.add_all([
            Notification(organization_id=org, owner_id=owner["user"]["id"],
                         category="report", title="Synthetic report completed",
                         resource="report:fixture", href="/platform/reports",
                         dedupe_key="fixture-report-notification"),
            Notification(organization_id=org, owner_id=owner["user"]["id"],
                         category="incident_assignment", title="Synthetic incident assigned",
                         resource="incident:fixture", href="/platform/incidents",
                         dedupe_key="fixture-incident-notification"),
        ])
    rows = client.get("/api/v1/notifications", headers=auth)
    assert rows.status_code == 200
    assert len(rows.json()) == 2
    assert client.get("/api/v1/notifications/unread-count", headers=auth).json()["count"] == 2
    assert client.get("/api/v1/notifications", headers=foreign).json() == []
    notification_id = rows.json()[0]["id"]
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=auth).status_code == 200
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=foreign).status_code == 404
    assert client.post("/api/v1/notifications/read-all", headers=auth).status_code == 200


def test_observability_status_is_owner_only_and_measured(client):
    _, owner = register(client, "observability")
    tenant, foreign = register(client, "observability-foreign")
    status = client.get("/api/v1/observability/status", headers=owner)
    assert status.status_code == 200
    body = status.json()
    assert body["database"]["status"] == "connected"
    assert isinstance(body["api"]["database_probe_latency_ms"], (int, float))
    assert client.get("/api/v1/observability/status", headers=foreign).status_code == 200
    with client.app.state.test_session_factory.begin() as db:
        user = db.query(User).filter(User.organization_id == tenant["organization"]["id"]).first()
        user.role = "viewer"
        db.commit()
    assert client.get("/api/v1/observability/status", headers=foreign).status_code == 403


def test_developer_api_credentials_are_scoped_expiring_and_revocable(client):
    _, auth = register(client, "developer-api")
    created = client.post("/api/v1/developer/credentials", headers=auth, json={
        "name": "Synthetic read integration",
        "scopes": ["dashboard.read"],
        "expires_at": "2027-10-31T00:00:00Z",
    })
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    credential_id = created.json()["id"]
    assert "vyrn_" in secret
    assert "secret" not in client.get("/api/v1/developer/credentials", headers=auth).text
    key_headers = {"Authorization": "Bearer " + secret}
    dashboard = client.get("/api/v1/dashboard", headers=key_headers)
    assert dashboard.status_code == 200
    assert client.get("/api/v1/reports", headers=key_headers).status_code == 403
    assert client.post("/api/v1/incidents", headers=key_headers, json={
        "organization_id": "foreign", "title": "Unauthorized", "severity": "high",
    }).status_code == 403
    revoked = client.post(f"/api/v1/developer/credentials/{credential_id}/revoke", headers=auth)
    assert revoked.status_code == 200
    assert client.get("/api/v1/dashboard", headers=key_headers).status_code == 401


def test_security_event_ingestion_stream_is_tenant_scoped_and_audited(client):
    tenant_a, auth_a = register(client, "events-alpha")
    tenant_b, auth_b = register(client, "events-bravo")
    org_a = tenant_a["organization"]["id"]
    org_b = tenant_b["organization"]["id"]

    own = client.post("/api/v1/security-events", headers=auth_a, json={
        "organization_id": org_a,
        "source": "authorized-auth-log",
        "event_type": "authentication_anomaly",
        "severity": "high",
        "title": "Unusual sign-in sequence",
        "description": "Recorded for analyst review.",
        "source_reference": "AUTH-LOCAL-7",
        "occurred_at": "2026-11-25T08:00:00+05:30",
    })
    assert own.status_code == 200, own.text
    assert own.json()["status"] == "new"
    assert own.json()["occurred_at"] == "2026-11-25T02:30:00+00:00"

    foreign = client.post("/api/v1/security-events", headers=auth_b, json={
        "organization_id": org_b,
        "source": "tenant-b-log",
        "event_type": "login",
        "title": "Tenant B sign-in",
    })
    assert foreign.status_code == 200
    assert [row["id"] for row in client.get("/api/v1/security-events", headers=auth_a).json()] == [own.json()["id"]]
    assert client.get("/api/v1/security-events", headers=auth_a, params={"search": "AUTH-LOCAL-7"}).json()[0]["id"] == own.json()["id"]
    assert client.get("/api/v1/security-events", headers=auth_a, params={"severity": "critical"}).json() == []
    assert client.get("/api/v1/security-events", headers=auth_a, params={"search": "%"}).json() == []
    assert client.get("/api/v1/security-events", headers=auth_a, params={"organization_id": org_b}).status_code == 404
    assert client.post("/api/v1/security-events", headers=auth_a, json={
        "organization_id": org_b,
        "source": "foreign",
        "event_type": "injection",
        "title": "Cross-tenant event",
    }).status_code == 404

    own_status = f"/api/v1/security-events/{own.json()['id']}/status"
    foreign_status = f"/api/v1/security-events/{foreign.json()['id']}/status"
    assert client.patch(own_status, json={"status": "reviewed"}).status_code == 401
    assert client.patch(foreign_status, headers=auth_a, json={"status": "reviewed"}).status_code == 404
    assert client.patch(own_status, headers=auth_a, json={"status": "reviewed"}).json()["status"] == "reviewed"
    assert client.patch(own_status, headers=auth_a, json={"status": "reviewed"}).status_code == 200
    assert client.patch(own_status, headers=auth_a, json={"status": "dismissed"}).status_code == 409
    assert client.get("/api/v1/security-events", headers=auth_a, params={"status": "new"}).json() == []
    assert client.get("/api/v1/security-events", headers=auth_a, params={"status": "reviewed"}).json()[0]["id"] == own.json()["id"]

    with client.app.state.test_session_factory() as db:
        user = db.scalar(select(User).where(User.id == tenant_a["user"]["id"]))
        user.role = "viewer"
        db.commit()
    assert client.post("/api/v1/security-events", headers=auth_a, json={
        "organization_id": org_a,
        "source": "viewer",
        "event_type": "login",
        "title": "Viewer ingestion denied",
    }).status_code == 403
    assert client.patch(own_status, headers=auth_a, json={"status": "reviewed"}).status_code == 403
    with client.app.state.test_session_factory() as db:
        actions = db.scalars(select(AuditLog.action).where(AuditLog.organization_id == org_a)).all()
        assert "security_event.ingest" in actions
        assert actions.count("security_event.review") == 1


def test_graph_traversal_and_bookmarks_are_tenant_scoped(client):
    registered_a, auth_a = register(client, "graph-alpha")
    registered_b, auth_b = register(client, "graph-bravo")
    org_a = registered_a["organization"]["id"]
    org_b = registered_b["organization"]["id"]
    first = client.post("/api/v1/intelligence/entities", headers=auth_a, json={
        "organization_id": org_a,
        "entity_type": "user",
        "external_id": "GRAPH-A-1",
        "display_name": "Analyst account",
    }).json()
    second = client.post("/api/v1/intelligence/entities", headers=auth_a, json={
        "organization_id": org_a,
        "entity_type": "device",
        "external_id": "GRAPH-A-2",
        "display_name": "Workstation",
    }).json()
    relation = client.post("/api/v1/intelligence/relationships", headers=auth_a, json={
        "organization_id": org_a,
        "source_id": first["id"],
        "target_id": second["id"],
        "relationship_type": "signed_in_from",
        "confidence": 0.84,
        "source_reference": "demo-event-1",
    })
    assert relation.status_code == 200

    foreign = client.post("/api/v1/intelligence/entities", headers=auth_b, json={
        "organization_id": org_b,
        "entity_type": "asset",
        "external_id": "GRAPH-B-1",
        "display_name": "Tenant B asset",
    }).json()
    graph = client.get("/api/v1/intelligence/graph", headers=auth_a, params={"focus_id": first["id"]})
    assert graph.status_code == 200
    assert {item["id"] for item in graph.json()["entities"]} == {first["id"], second["id"]}
    assert graph.json()["relationships"][0]["source_reference"] == "demo-event-1"
    assert client.get("/api/v1/intelligence/graph", headers=auth_a, params={"focus_id": foreign["id"]}).status_code == 404

    saved = client.post("/api/v1/intelligence/graph/bookmarks", headers=auth_a, json={
        "name": "Refund investigation",
        "entity_ids": [first["id"], second["id"]],
        "filters": {"relationship_type": "signed_in_from"},
    })
    assert saved.status_code == 200
    assert client.post("/api/v1/intelligence/graph/bookmarks", headers=auth_a, json={
        "name": "Invalid cross-tenant bookmark",
        "entity_ids": [foreign["id"]],
    }).status_code == 404
    assert client.get("/api/v1/intelligence/graph/bookmarks", headers=auth_a).json()[0]["id"] == saved.json()["id"]


def test_refresh_rotation_revocation_and_evidence_integrity(client, tmp_path):
    registered, auth = register(client, "evidence")
    original_refresh = registered["refresh_token"]

    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert rotated.status_code == 200
    tokens = rotated.json()
    assert tokens["refresh_token"] != original_refresh
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh}).status_code == 401

    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200
    evidence = client.post(
        "/api/v1/evidence",
        headers=auth,
        params={"organization_id": registered["organization"]["id"], "name": "authorized.log"},
        files={"file": ("authorized.log", b"authorized test evidence", "text/plain")},
    )
    assert evidence.status_code == 200
    assert evidence.json()["sha256"] == hashlib.sha256(b"authorized test evidence").hexdigest()
    assert len(evidence.json()["sha512"]) == 128
    assert evidence.json()["stored"] is True
    downloaded = client.get(f"/api/v1/evidence/{evidence.json()['id']}/download", headers=auth)
    evidence_path = f"/api/v1/evidence/{evidence.json()['id']}"
    verified = client.post(f"{evidence_path}/verify", headers=auth)
    assert verified.status_code == 200 and verified.json()["integrity"] == "match"
    assert {item["action"] for item in client.get(f"{evidence_path}/activity", headers=auth).json()} == {
        "evidence.upload", "evidence.verify",
    }
    assert downloaded.status_code == 200
    assert downloaded.content == b"authorized test evidence"
    key = hashlib.sha256(registered["organization"]["id"].encode()).hexdigest()
    blob = tmp_path / "evidence-storage" / key / f"{evidence.json()['id']}.blob"
    blob.write_bytes(b"changed bytes")
    assert client.post(f"{evidence_path}/verify", headers=auth).json()["integrity"] == "mismatch"
    assert client.get(f"{evidence_path}/download", headers=auth).status_code == 409
    assert client.get("/api/v1/evidence", headers=auth).json()[0]["id"] == evidence.json()["id"]

    logout = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401


def test_tenant_scoped_agent_execution_and_history(client):
    owner, owner_auth = register(client, "agents")
    other, other_auth = register(client, "agent-other")
    org_id = owner["organization"]["id"]
    foreign_incident = client.post("/api/v1/incidents", headers=other_auth, json={
        "organization_id": other["organization"]["id"], "title": "foreign record",
    }).json()

    assert client.get("/api/v1/agents").status_code == 401
    registry = client.get("/api/v1/agents", headers=owner_auth)
    assert registry.status_code == 200
    assert len(registry.json()) == 7
    assert all(agent["status"] == "deterministic_local" for agent in registry.json())
    assert client.post("/api/v1/agents/executions", headers=owner_auth, json={
        "agent": "sentinel", "incident_id": foreign_incident["id"],
    }).status_code == 404

    incident = client.post("/api/v1/incidents", headers=owner_auth, json={
        "organization_id": org_id, "title": "Suspicious sign-in", "severity": "high",
    }).json()
    run = client.post("/api/v1/agents/executions", headers=owner_auth, json={
        "agent": "sentinel", "incident_id": incident["id"],
    })
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "completed"
    assert run.json()["requires_approval"] is True
    assert f"incident:{incident['id']}" in run.json()["evidence"]
    assert run.json()["confidence"] is None
    assert "deterministic" in run.json()["limitations"][0].lower()
    history = client.get("/api/v1/agents/executions", headers=owner_auth)
    assert history.status_code == 200
    assert history.json()[0]["id"] == run.json()["id"]
    assert client.get("/api/v1/agents/executions", headers=other_auth).json() == []
    assert client.post("/api/v1/agents/executions", headers=owner_auth, json={
        "agent": "UNLISTED",
    }).status_code == 422


def test_incident_status_transitions_are_audited_and_tenant_scoped(client):
    owner, owner_auth = register(client, "incident-state")
    other, other_auth = register(client, "incident-state-other")
    incident = client.post("/api/v1/incidents", headers=owner_auth, json={
        "organization_id": owner["organization"]["id"], "title": "State transition test",
    }).json()
    foreign = client.post("/api/v1/incidents", headers=other_auth, json={
        "organization_id": other["organization"]["id"], "title": "Other tenant case",
    }).json()
    path = f"/api/v1/incidents/{incident['id']}/status"
    assert client.patch(path, json={"status": "investigating"}).status_code == 401
    assert client.patch(f"/api/v1/incidents/{foreign['id']}/status", headers=owner_auth,
                        json={"status": "investigating"}).status_code == 404
    moved = client.patch(path, headers=owner_auth, json={"status": "investigating", "note": "Analyst started review"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "investigating"
    assert client.patch(path, headers=owner_auth, json={"status": "open"}).status_code == 409
    assert client.patch(path, headers=owner_auth, json={"status": "closed"}).status_code == 200
    assert client.patch(path, headers=owner_auth, json={"status": "investigating"}).status_code == 409
    history = client.get(f"/api/v1/incidents/{incident['id']}/history", headers=owner_auth)
    assert [event["to_status"] for event in history.json()] == ["open", "investigating", "closed"]
    assert client.get(f"/api/v1/incidents/{incident['id']}/history", headers=other_auth).status_code == 404
