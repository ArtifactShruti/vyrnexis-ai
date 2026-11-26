import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from threading import Event
from zipfile import ZipFile

from argon2 import PasswordHasher
import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.ai_providers import Connection, request_provider
from app.models import User
from test_api import register
from test_forensics_nexus import new_case


@pytest.mark.parametrize(("provider", "endpoint", "response"), [
    ("openai", "/v1/chat/completions", {
        "choices": [{"message": {"content": '{"answer":"record","citations":["sample"]}'}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4},
    }),
    ("anthropic", "/v1/messages", {
        "content": [{"type": "text", "text": '{"answer":"record","citations":["sample"]}'}],
        "usage": {"input_tokens": 8, "output_tokens": 4},
    }),
    ("gemini", "/v1/models/fixture:generateContent", {
        "candidates": [{"content": {"parts": [{"text": '{"answer":"record","citations":["sample"]}'}]}}],
        "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 4},
    }),
    ("ollama", "/v1/api/chat", {
        "message": {"content": '{"answer":"record","citations":["sample"]}'}, "prompt_eval_count": 8, "eval_count": 4,
    }),
])
def test_mocked_adapter_protocols(provider, endpoint, response):
    calls = []

    def mock(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "synthetic rate limit"})
        return httpx.Response(200, json=response)

    connection = Connection(provider, "https://provider.example/v1", {"x-test": "test-token"})
    reply, input_count, output_count = asyncio.run(request_provider(
        connection, "fixture", timeout=3, prompt=("test system instruction", '{"test":true}'), limit=80,
        transport=httpx.MockTransport(mock),
    ))
    assert (reply, input_count, output_count) == ({"answer": "record", "citations": ["sample"]}, 8, 4)
    assert len(calls) == 2 and calls[-1].url.path == endpoint
    assert calls[-1].headers["x-test"] == "test-token"
    assert "test system instruction" in calls[-1].content.decode()


def upload(client, auth, title, payload, filename="policy.txt", visibility="private"):
    return client.post("/api/v1/knowledge/documents", headers=auth, json={
        "title": title, "filename": filename, "content_base64": base64.b64encode(payload).decode(),
        "visibility": visibility, "retention_days": 90,
    })


def conversation(client, auth, **scope):
    response = client.post("/api/v1/copilot/conversations", headers=auth, json={"title": "Synthetic discussion", **scope})
    assert response.status_code == 201, response.text
    return "/api/v1/copilot/conversations/" + response.json()["id"]


def ask(client, auth, uri, key, *, mode="record_search", consent=False):
    return client.post(f"{uri}/turns", headers=auth, json={
        "text": "Scope of the zephyrian review", "request_key": key, "mode": mode,
        "acknowledge_model_context": consent,
    })


def same_tenant_viewer(client, owner):
    password = "synthetic-workspace-test-password"
    email = "workspace-viewer@example.org"
    with client.app.state.test_session_factory.begin() as db:
        db.add(User(organization_id=owner["organization"]["id"], email=email, full_name="Synthetic viewer",
                    password_hash=PasswordHasher().hash(password), role="viewer"))
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def test_knowledge_and_copilot_enforce_scope_and_revoke_citations(client):
    owner, auth = register(client, "knowledge")
    _, foreign = register(client, "knowledge-other")
    viewer = same_tenant_viewer(client, owner)
    data = b"The zephyrian review requires an approved evidence export."
    private = upload(client, auth, "Synthetic policy", data)
    assert private.status_code == 201, private.text
    doc_id = private.json()["id"]
    doc_path = "/api/v1/knowledge/documents/" + doc_id
    assert upload(client, auth, "Duplicate", data).status_code == 409
    search_path = "/api/v1/knowledge/search?query=zephyrian"
    assert client.get(search_path, headers=foreign).json()["sources"] == []
    assert client.get(search_path, headers=viewer).json()["sources"] == []
    assert client.get(doc_path, headers=viewer).status_code == 404
    assert client.get("/api/v1/ai/settings", headers=viewer).status_code == 403
    assert client.put(doc_path + "/policy", headers=auth, json={"visibility": "organization", "retention_days": 2}).status_code == 200
    assert client.get(search_path, headers=viewer).json()["sources"][0]["version"] == 1
    assert client.delete(doc_path, headers=viewer).status_code == 403
    uri = conversation(client, viewer)
    result = ask(client, viewer, uri, "initial-local-query")
    assert result.status_code == 200, result.text
    turn = result.json()
    assert turn["mode"] == "record_search" and turn["sources"][0]["kind"] == "document"
    assert ask(client, viewer, uri, "initial-local-query").json()["id"] == turn["id"]
    assert client.get(uri, headers=auth).status_code == 404
    assert client.get(uri + "/export", headers=foreign).status_code == 404
    assert client.put(doc_path + "/policy", headers=auth, json={"visibility": "private", "retention_days": 2}).status_code == 200
    assert client.get(uri, headers=viewer).json()["turns"][0]["sources"] == []
    assert upload(client, auth, "Malformed", b"broken docx", "broken.docx").status_code == 422
    assert client.post(doc_path + "/versions", headers=auth, json={
        "filename": "policy.txt", "content_base64": base64.b64encode(b"Updated zephyrian procedure.").decode(),
    }).status_code == 201
    assert client.get(search_path, headers=auth).json()["sources"][0]["version"] == 2
    versioned_history = client.get(uri, headers=viewer)
    assert versioned_history.status_code == 200
    assert versioned_history.json()["turns"][0]["sources"] == []
    assert "unavailable" in versioned_history.json()["turns"][0]["answer"]
    assert client.delete(doc_path, headers=auth).status_code == 204
    assert client.get(search_path, headers=auth).json()["sources"] == []
    assert client.delete(uri, headers=viewer).status_code == 204


def test_pdf_docx_text_extraction(client):
    _, auth = register(client, "documents")
    pdf = BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(40, 700, "Saffron archive policy")
    canvas.save()
    word = BytesIO()
    with ZipFile(word, "w") as bundle:
        bundle.writestr("word/document.xml",
                        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        '<w:body><w:p><w:r><w:t>Violet archive policy</w:t></w:r></w:p></w:body></w:document>')
    assert upload(client, auth, "PDF policy", pdf.getvalue(), "policy.pdf").status_code == 201
    assert upload(client, auth, "Word policy", word.getvalue(), "policy.docx").status_code == 201
    assert client.get("/api/v1/knowledge/search?query=saffron", headers=auth).json()["sources"][0]["location"] == "page 1"
    assert client.get("/api/v1/knowledge/search?query=violet", headers=auth).json()["sources"][0]["filename"] == "policy.docx"


def test_model_policy_budget_validation_and_cancellation(client, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_AI_ENABLE_EXTERNAL", "1")
    monkeypatch.setenv("VYRNEXIS_AI_OPENAI_KEY", "synthetic-gateway-key")
    monkeypatch.setenv("VYRNEXIS_AI_OPENAI_INPUT_MICROS_PER_1K", "100")
    monkeypatch.setenv("VYRNEXIS_AI_OPENAI_OUTPUT_MICROS_PER_1K", "200")
    _, auth = register(client, "model")
    settings_url = "/api/v1/ai/settings"
    settings = {"mode": "assisted", "provider": "openai", "model": "fixture", "allow_model_context": True,
                "daily_budget_micros": 10_000}
    assert client.put(settings_url, headers=auth, json=settings).status_code == 200
    assert "synthetic-gateway-key" not in client.get(settings_url, headers=auth).text
    assert upload(client, auth, "Synthetic policy", b"Review zephyrian authorization.").status_code == 201
    uri = conversation(client, auth)
    started = Event()
    calls = []

    async def mock(connection, model, **kwargs):
        calls.append(model)
        if len(calls) == 3:
            started.set()
            await asyncio.sleep(8)
        sources = json.loads(kwargs["prompt"][1])["sources"]
        return {"answer": "Recorded policy", "citations": [
            sources[0]["key"] if len(calls) == 1 else "invented-source",
        ]}, 15, 8

    monkeypatch.setattr("app.ai_gateway.request_provider", mock)
    assert ask(client, auth, uri, "no-consent-key", mode="model_assisted").status_code == 403
    assert not calls
    first = ask(client, auth, uri, "approved-model-key", mode="model_assisted", consent=True)
    assert first.status_code == 200 and first.json()["model"]["model"] == "fixture", first.text
    assert ask(client, auth, uri, "approved-model-key", mode="model_assisted", consent=True).json()["id"] == first.json()["id"]
    wrong = ask(client, auth, uri, "invalid-citation-key", mode="model_assisted", consent=True)
    assert wrong.json()["status"] == "failed" and "invalid_citations" in wrong.json()["answer"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(ask, client, auth, uri, "cancel-model-key", mode="model_assisted", consent=True)
        assert started.wait(4)
        assert client.post(uri + "/cancel/cancel-model-key", headers=auth).status_code == 200
        assert running.result(timeout=4).json()["status"] == "cancelled"
    status = client.get(settings_url, headers=auth).json()
    assert {item["status"] for item in status["recent_usage"]} == {"completed", "failed", "cancelled"}
    assert status["recent_usage"][-1]["input_tokens"] == 15
    assert client.put(settings_url, headers=auth, json=settings | {"daily_budget_micros": 1}).status_code == 200
    capped = ask(client, auth, uri, "budget-exceeded-key", mode="model_assisted", consent=True)
    assert capped.json()["status"] == "failed" and "budget" in capped.json()["answer"]
    assert len(calls) == 3


def test_case_copilot_and_mocked_nexus_interpretation(client, monkeypatch):
    _, auth = register(client, "hybrid")
    _, other = register(client, "hybrid-foreign")
    case = new_case(client, auth)
    uri = conversation(client, auth, case_id=case["id"])
    assert ask(client, auth, uri, "scoped-case-query").json()["sources"][0]["kind"] == "case"
    assert client.post("/api/v1/copilot/conversations", headers=other, json={
        "title": "Foreign case test", "case_id": case["id"],
    }).status_code == 404
    started = client.post("/api/v1/investigations", headers=auth, json={
        "case_id": case["id"], "request_key": "hybrid-selection", "agents": ["TRACE"],
    })
    assert started.status_code == 201, started.text
    run = started.json()
    task = run["tasks"][0]
    assert len(run["tasks"]) == 1 and task["agent"] == "TRACE"
    path = f"/api/v1/investigations/{run['id']}/tasks/{task['id']}/interpretations"
    assert client.get(path, headers=other).status_code == 404
    submission = {"request_key": "task-interpretation-1", "acknowledge_model_context": True}
    assert client.post(path, headers=auth, json=submission).status_code == 409
    monkeypatch.setenv("VYRNEXIS_AI_ENABLE_LOCAL", "1")
    monkeypatch.setenv("VYRNEXIS_AI_OLLAMA_URL", "http://127.0.0.1:11434")
    assert client.put("/api/v1/ai/settings", headers=auth, json={
        "mode": "hybrid", "provider": "ollama", "model": "fixture", "allow_model_context": True,
    }).status_code == 200
    calls = []

    async def mock(connection, model, **kwargs):
        calls.append(model)
        selected = json.loads(kwargs["prompt"][1])["sources"][0]
        assert selected["key"] == f"task:{task['id']}"
        assert "insufficient_evidence" in selected["excerpt"]
        return {"answer": "Review the recorded limitations.", "citations": [selected["key"]]}, 15, 8

    monkeypatch.setattr("app.ai_gateway.request_provider", mock)
    first = client.post(path, headers=auth, json=submission)
    assert first.status_code == 200, first.text
    interpretation = first.json()
    assert interpretation["status"] == "completed" and interpretation["usage"]["input_tokens"] == 15
    assert interpretation["review_status"] == "pending"
    assert client.post(path, headers=auth, json=submission).json()["id"] == interpretation["id"]
    assert calls == ["fixture"]
    reviewed = client.post(path + "/" + interpretation["id"] + "/review", headers=auth, json={
        "decision": "approved", "note": "Confirmed it describes limitations.",
    })
    assert reviewed.status_code == 200 and reviewed.json()["review_status"] == "approved"
    original = client.get(f"/api/v1/investigations/{run['id']}", headers=auth).json()
    assert original["tasks"][0]["result"] == task["result"]
