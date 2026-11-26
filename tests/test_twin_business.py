from datetime import datetime

from app.models import CommerceFinding, CommerceRecord, DataSource
from test_api import register


def test_commerce_transactions_are_searchable_paged_and_exported(client):
    owner, auth = register(client, "commerce-e2e")
    _, foreign = register(client, "commerce-e2e-foreign")
    org = owner["organization"]["id"]
    with client.app.state.test_session_factory.begin() as db:
        source = DataSource(organization_id=org, kind="commerce", name="Synthetic commerce workspace")
        db.add(source)
        db.flush()
        payment = CommerceRecord(organization_id=org, source_id=source.id, external_id="pay-001",
                                 kind="payment", account="customer-a", device="device-a",
                                 order_reference="order-100", currency="USD", amount_minor=5000,
                                 occurred_at=datetime(2026, 11, 25, 12, 0))
        refund = CommerceRecord(organization_id=org, source_id=source.id, external_id="refund-001",
                                kind="refund", account="customer-a", device="device-a",
                                order_reference="order-100", currency="USD", amount_minor=1250,
                                occurred_at=datetime(2026, 11, 25, 12, 5))
        db.add_all([payment, refund])
        db.flush()
        db.add(CommerceFinding(organization_id=org, refund_id=refund.id, score=65,
                               report='{"factors":[]}', status="open"))
    paged = client.get("/api/v1/commerce/transactions?kind=payment&currency=USD&search=customer-a",
                       headers=auth)
    assert paged.status_code == 200
    assert paged.json()["total"] == 1
    assert paged.json()["items"][0]["external_id"] == "pay-001"
    detail = client.get(f"/api/v1/commerce/records/{paged.json()['items'][0]['id']}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["account"] == "customer-a"
    refund_id = client.get("/api/v1/commerce/transactions?kind=refund", headers=auth).json()["items"][0]["id"]
    refund_detail = client.get(f"/api/v1/commerce/records/{refund_id}", headers=auth)
    assert refund_detail.status_code == 200
    assert refund_detail.json()["finding"]["status"] == "open"
    assert client.get(f"/api/v1/commerce/records/{refund_id}", headers=foreign).status_code == 404
    assert client.get("/api/v1/commerce/transactions", headers=foreign).json()["total"] == 0
    export = client.get("/api/v1/commerce/export?format=csv&currency=USD", headers=auth)
    assert export.status_code == 200
    assert "pay-001" in export.text and "refund-001" in export.text


def test_twin_propagation_mitigation_cycles_and_tenant_scope(client):
    owner, auth = register(client, "twin")
    other, foreign = register(client, "twin-foreign")
    root = "/api/v1/digital-twin"

    def entity(name, kind, account=owner, headers=auth):
        result = client.post("/api/v1/intelligence/entities", headers=headers, json={
            "organization_id": account["organization"]["id"], "display_name": name,
            "entity_type": kind, "external_id": name.lower().replace(" ", "-"),
        })
        assert result.status_code == 200, result.text
        return result.json()["id"]

    device = entity("Synthetic host", "device")
    api = entity("Synthetic application", "application")
    process = entity("Synthetic fulfillment", "business_process")
    foreign_device = entity("Foreign host", "device", other, foreign)

    def dependency(dependent, prerequisite):
        return client.post(root + "/dependencies", headers=auth, json={
            "dependent_id": dependent, "prerequisite_id": prerequisite, "kind": "depends_on",
            "reason": "Synthetic documented dependency", "confidence": .9,
        })

    assert dependency(api, foreign_device).status_code == 404
    alternate_edge = dependency(api, device)
    assert alternate_edge.status_code == 201, alternate_edge.text
    assert dependency(process, api).status_code == 201
    assert dependency(device, process).status_code == 201
    before = client.get(root + "/topology", headers=auth).json()
    inputs = {"title": "Synthetic host failure", "scenario_type": "outage", "target_id": device, "depth": 4,
              "assumption": "The synthetic host is unavailable.", "request_key": "synthetic-twin-01",
              "excluded_dependencies": [alternate_edge.json()["id"]]}
    response = client.post(root + "/simulations", headers=auth, json=inputs)
    assert response.status_code == 201, response.text
    simulation = response.json()
    result = simulation["result"]
    assert result["hypothetical"] and result["baseline"]["direct"] == result["baseline"]["indirect"] == 1
    assert next(item["path"] for item in result["baseline"]["affected"] if item["id"] == process) == [device, api, process]
    assert {api, process} == set(result["avoided_entities"])
    assert simulation["topology_digest"] == before["digest"]
    assert client.get(root + "/topology", headers=auth).json() == before
    assert client.post(root + "/simulations", headers=auth, json=inputs).json()["id"] == simulation["id"]
    assert client.post(root + "/simulations", headers=auth, json=inputs | {"depth": 1}).status_code == 409
    assert client.get(f"{root}/simulations/{simulation['id']}/export", headers=foreign).status_code == 404
    assert client.get(f"{root}/simulations/{simulation['id']}/export", headers=auth).json() == simulation


def test_business_report_preserves_currencies_and_period_boundaries(client):
    owner, auth = register(client, "business")
    _, other = register(client, "business-foreign")
    org = owner["organization"]["id"]
    with client.app.state.test_session_factory.begin() as db:
        source = DataSource(organization_id=org, kind="commerce", name="Synthetic finance fixture")
        db.add(source)
        db.flush()
        rows = []
        for index, (kind, account, code, amount, day) in enumerate([
            ("payment", "a", "USD", 1000, 24), ("payment", "a", "USD", 2000, 25),
            ("refund", "b", "USD", 300, 25), ("refund", "eur", "EUR", 500, 25),
            ("payment", "a", "USD", 700, 22), ("payment", "later", "USD", 999, 26),
        ]):
            rows.append(CommerceRecord(organization_id=org, source_id=source.id, external_id=f"business-{index}",
                                       kind=kind, account=account, currency=code, amount_minor=amount,
                                       occurred_at=datetime(2026, 11, day, 23, 59)))
        db.add_all(rows)
        db.flush()
        db.add(CommerceFinding(organization_id=org, refund_id=rows[2].id, score=30, report="{}", status="confirmed"))
    base = "/api/v1/business-intelligence"
    query = "?start=2026-11-24&end=2026-11-25"
    report = client.get(base + "/report" + query, headers=auth).json()
    assert report["comparison"] == {"start": "2026-11-22", "end": "2026-11-23"}
    data = {item["currency"]: item for item in report["summary"]}
    assert data["USD"]["paid_minor"] == "3000" and data["USD"]["net_recorded_minor"] == "2700"
    assert data["USD"]["refund_count_per_100_payments"] == "50.00" and data["USD"]["previous"]["paid_minor"] == "700"
    assert data["EUR"]["paid_minor"] == "0" and data["EUR"]["refund_count_per_100_payments"] is None
    assert report["finding_statuses"] == [{"currency": "USD", "status": "confirmed", "count": 1}]
    assert client.get(base + "/report" + query, headers=other).json()["summary"] == []
    export = client.get(base + "/export" + query + "&format=csv&currency=USD", headers=auth)
    assert export.status_code == 200 and "2026-11-25,USD,1,1,2000,300" in export.text and "EUR" not in export.text
    assert client.get(base + "/report?start=2020-01-01&end=2026-11-25", headers=auth).status_code == 422
