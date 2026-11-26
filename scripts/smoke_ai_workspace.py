"""Exercise the local AI workspace without sending any provider requests."""
import base64
from http.cookies import SimpleCookie
import json
import time

from smoke_forensics import api, create_case, exchange, tenant
from smoke_postgres import compose


def verify_stack(port):
    owner, credentials = tenant(port)
    foreign, _ = tenant(port)
    token, other = owner["access_token"], foreign["access_token"]
    assert api("/ai/availability", token=token, port=port)["available"] is False
    stored = api("/knowledge/documents", "POST", {
        "title": "Synthetic evidence export policy", "filename": "policy.md", "visibility": "private",
        "content_base64": base64.b64encode(b"## Cobalt evidence policy\nCobalt exports require a recorded review.").decode(),
    }, token, expected=201, port=port)
    search = "/knowledge/search?query=cobalt"
    assert api(search, token=other, port=port)["sources"] == []
    document_id = stored["id"]
    assert api(search, token=token, port=port)["sources"][0]["document_id"] == document_id
    convo = api("/copilot/conversations", "POST", {"title": "Synthetic policy review"}, token, expected=201, port=port)
    path = f"/copilot/conversations/{convo['id']}"
    result = api(path + "/turns", "POST", {"text": "Cobalt exports", "request_key": "smoke-first-question"},
                 token, port=port)
    assert result["status"] == "completed" and result["mode"] == "record_search"
    assert result["sources"][0]["document_id"] == document_id
    assert api(path + "/export", token=token, port=port)["turns"][0]["id"] == result["id"]
    api(path, token=other, expected=404, port=port)
    return credentials, path


def verify():
    assert "(head)" in compose("exec", "-T", "api", "python", "-m", "alembic", "current")
    compose("exec", "-T", "api", "python", "-m", "alembic", "check")
    verify_stack(8001)
    credentials, path = verify_stack(8002)
    proxy = "/api/workspace" + path
    assert exchange(proxy, port=3001)[0] == 401
    status, _, headers = exchange("/api/auth/login", "POST", credentials, port=3001)
    assert status == 200
    cookies = SimpleCookie()
    for name, value in headers:
        if name.lower() == "set-cookie":
            cookies.load(value)
    session = cookies["vyrnexis_access"]
    assert session["httponly"]
    signed = {"Cookie": f"vyrnexis_access={session.value}"}
    status, body, _ = exchange(proxy, port=3001, headers=signed)
    assert status == 200 and json.loads(body)["turns"][0]["sources"]
    assert exchange(proxy, "DELETE", port=3001, headers=signed | {"Origin": "https://foreign.example"})[0] == 403
    print("Migration head, keyword retrieval, private documents, persistent Copilot exports, and authenticated proxy verified.")
    verify_replay()


def verify_replay():
    owner, _ = tenant(8002)
    token = owner["access_token"]
    case = create_case(token)
    compose("stop", "worker")
    try:
        run = api("/investigations", "POST", {
            "case_id": case["id"], "agents": ["SENTINEL"], "request_key": "synthetic-replay-parent",
        }, token, expected=201)
        path = f"/investigations/{run['id']}"
        expire = """
import sys
from datetime import timedelta
from app.database import SessionLocal
from app.models import InvestigationTask, utc_now_naive
from app.nexus import claim, fail_claim
for index in range(3):
    job = claim(sys.argv[1])
    assert isinstance(job, tuple)
    fail_claim(job, "Synthetic deadline fixture", timed_out=True)
    with SessionLocal.begin() as db:
        task = db.get(InvestigationTask, job[1])
        if task.status == "queued":
            task.available_at = utc_now_naive() - timedelta(seconds=10)
"""
        compose("exec", "-T", "api", "python", "-c", expire, run["id"])
        failed = api(path, token=token)
        assert failed["status"] == "failed" and failed["tasks"][0]["attempts"] == 3
        submission = {"request_key": "synthetic-replay-child", "agents": ["SENTINEL"]}
        replay = api(path + "/replay", "POST", submission, token, expected=201)
        assert replay["replay"]["source_run_id"] == run["id"] and replay["status"] == "queued"
        assert api(path + "/replay", "POST", submission, token, expected=201)["id"] == replay["id"]
    finally:
        compose("start", "worker")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = api(f"/investigations/{replay['id']}", token=token)
        if result["status"] == "awaiting_approval":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Replay did not complete after the worker restarted")
    assert result["tasks"][0]["status"] == "completed"
    assert api(path, token=token)["tasks"][0]["history"] == failed["tasks"][0]["history"]
    print("PostgreSQL authorized selective replay preserved the original timed-out attempts.")


if __name__ == "__main__":
    verify()
