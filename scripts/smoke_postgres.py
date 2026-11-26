"""Run a synthetic integration check against the dedicated PostgreSQL demo stack."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--env-file", ".env.postgres", "-f", "docker-compose.postgres.yml"]
API = "http://127.0.0.1:8002/api/v1"


def compose(*arguments: str) -> str:
    run = subprocess.run([*COMPOSE, *arguments], cwd=ROOT, check=True, text=True,
                         stdout=subprocess.PIPE, timeout=90)
    return run.stdout.strip()


def request(path: str, method="GET", body=None, token=None, expected=200):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    message = Request(API + path, method=method, headers=headers, data=json.dumps(body).encode() if body else None)
    try:
        response = urlopen(message, timeout=8)
    except HTTPError as error:
        response = error
    with response:
        if response.status != expected:
            raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status}")
        return json.load(response)


def wait_for_worker(token: str, expected_count: int):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        state = request("/detection-status", token=token)
        if state["failed"]:
            raise RuntimeError("Detection worker reported failed jobs")
        if state["worker_available"] and state["completed"] == expected_count:
            return
        time.sleep(1)
    raise RuntimeError("Persisted detection jobs did not complete before the deadline")


def verify():
    if "(head)" not in compose("exec", "-T", "api", "python", "-m", "alembic", "current"):
        raise RuntimeError("Expected the database at Alembic head")
    compose("exec", "-T", "api", "python", "-m", "alembic", "check")
    assert compose("exec", "-T", "redis", "redis-cli", "PING") == "PONG"
    marker = f"vyrnexis:smoke:{uuid4().hex}"
    assert compose("exec", "-T", "redis", "redis-cli", "SET", marker, "synthetic", "EX", "120") == "OK"

    name = "phase4-smoke-" + uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    session = request("/auth/register", "POST", {
        "organization_name": f"Synthetic Phase 4 verification {name}",
        "organization_slug": name, "full_name": "Synthetic Verification Owner",
        "email": f"{name}@example.org", "password": password,
    })
    token = session["access_token"]
    assert request("/detection-status", token=token)["mode"] == "worker"
    request("/detection-rules/failed_signins", "PUT", {"threshold": 3, "window_minutes": 15}, token)
    request("/detection-rules/unfamiliar_device", "PUT", {"window_minutes": 30}, token)
    compose("stop", "worker")
    events = []
    try:
        anchor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        for index, result, device in [(1, "success", "lab-a"), (2, "failure", "lab-b"),
                                      (3, "failure", "lab-b"), (4, "failure", "lab-b"), (5, "success", "lab-b")]:
            events.append(request("/security-events", "POST", {
                "organization_id": session["organization"]["id"], "event_type": "authentication",
                "source": "synthetic-smoke", "external_id": f"synthetic-{index}",
                "title": "Synthetic authentication observation", "outcome": result, "device": device,
                "account": "synthetic-account", "occurred_at": (anchor + timedelta(minutes=index)).isoformat(),
            }, token))
        assert request("/detection-status", token=token)["queued"] == 5
        assert request("/security-alerts", token=token) == []
        compose("restart", "redis", "postgres")
    finally:
        compose("start", "worker")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if compose("exec", "-T", "redis", "redis-cli", "GET", marker) == "synthetic":
                request("/auth/me", token=token)
                break
        except (RuntimeError, URLError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL session or Redis marker did not survive the restart")
    wait_for_worker(token, 5)
    alerts = request("/security-alerts", token=token)
    assert len(alerts) == 2
    rule_alert = next(alert for alert in alerts if "failed" in alert["title"])
    action = f"/security-alerts/{rule_alert['id']}/incident"
    incident = request(action, "POST", token=token)["incident_id"]
    assert request(action, "POST", token=token)["incident_id"] == incident
    links = request(f"/incidents/{incident}/security-events", token=token)
    assert {event["id"] for event in links} == {event["id"] for event in events[1:4]}
    assert len(request("/detection-runs", token=token)) == 10
    assert len(request("/incidents", token=token)) == 1
    request("/security-alerts", expected=401)
    print("PostgreSQL migrations, Redis persistence, queued detection recovery, two alerts and idempotent incident confirmation verified.")


if __name__ == "__main__":
    verify()
