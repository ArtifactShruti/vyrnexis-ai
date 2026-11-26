"""Verify Phase 6 against the dedicated PostgreSQL Docker stack using synthetic records."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from io import BytesIO
import json
import secrets
import time
from uuid import uuid4

from PIL import Image

from smoke_postgres import compose


ARTIFACT = b"VYRNEXIS synthetic forensic integration evidence\n"
CASE_ROOT = "/forensic-cases"
RUN_ROOT = "/investigations"


def exchange(path, method="GET", body=None, token=None, port=8002, headers=None):
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = "Bearer " + token
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    connection = HTTPConnection("localhost" if port == 3001 else "127.0.0.1", port, timeout=15)
    try:
        connection.request(method, ("/api/v1" if port in (8001, 8002) else "") + path, body, request_headers)
        response = connection.getresponse()
        return response.status, response.read(), response.getheaders()
    finally:
        connection.close()


def api(path, method="GET", body=None, token=None, expected=200, port=8002):
    status, data, _ = exchange(path, method, body, token, port)
    if status != expected:
        raise RuntimeError(f"{method} {path} returned HTTP {status}, expected {expected}: {data[:300]!r}")
    return json.loads(data)


def tenant(port):
    slug = "phase6-smoke-" + uuid4().hex[:12]
    credentials = {"email": slug + "@example.org", "password": secrets.token_urlsafe(24)}
    account = api("/auth/register", "POST", {
        "organization_name": "Synthetic Phase 6 verification " + slug,
        "organization_slug": slug, "full_name": "Synthetic verification owner", **credentials,
    }, port=port)
    return account, credentials


def create_case(token, port=8002):
    return api(CASE_ROOT, "POST", {"title": "Synthetic forensic smoke case", "category": "fraud",
                                  "priority": "high", "description": "Synthetic laboratory verification."},
               token, expected=201, port=port)


def upload(owner, data, filename, content_type, port=8002):
    boundary = "vyrnexis-" + uuid4().hex
    start = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
             f"Content-Type: {content_type}\r\n\r\n").encode()
    form = start + data + f"\r\n--{boundary}--\r\n".encode()
    status, response, _ = exchange(
        f"/evidence?organization_id={owner['organization']['id']}&name={filename}",
        "POST", form, owner["access_token"], port=port, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert status == 200, status
    return json.loads(response)


def verify_image_upload(owner, port):
    buffer = BytesIO()
    fields = Image.Exif()
    fields[274] = 6
    fields[34665] = {36867: "2026:02:01 12:30:00", 40962: 7, 40963: 5}
    Image.new("RGB", (7, 5)).save(buffer, format="JPEG", exif=fields)
    original = buffer.getvalue()
    evidence = upload(owner, original, "synthetic-photo.jpg", "image/jpeg", port=port)
    meta = evidence["image_metadata"]
    assert meta["status"] == "extracted"
    assert meta["fields"] == {"width": 7, "height": 5, "orientation": 6, "capture_time": "2026-02-01T12:30:00"}
    assert evidence["sha256"] == hashlib.sha256(original).hexdigest()
    assert evidence["sha512"] == hashlib.sha512(original).hexdigest()
    status, stored, _ = exchange(f"/evidence/{evidence['id']}/download", token=owner["access_token"], port=port)
    assert status == 200 and stored == original
    return evidence["id"]


def concurrent_edit(path, method, body, token):
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: exchange(path, method, body, token), range(2)))
    assert sorted(reply[0] for reply in replies) == [200, 409], [reply[0] for reply in replies]


def checksum(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_web(credentials, case_id, report_id, image_id):
    path = f"/api/forensic{CASE_ROOT}/{case_id}"
    assert exchange(path, port=3001)[0] == 401
    status, _, headers = exchange("/api/auth/login", "POST", credentials, port=3001)
    assert status == 200
    cookies = SimpleCookie()
    for key, value in headers:
        if key.lower() == "set-cookie":
            cookies.load(value)
    access = cookies["vyrnexis_access"]
    assert access["httponly"]
    signed = {"Cookie": f"vyrnexis_access={access.value}"}
    status, data, _ = exchange("/api/evidence", port=3001, headers=signed)
    assert status == 200 and any(
        item["id"] == image_id and item["image_metadata"]["fields"]["orientation"] == 6 for item in json.loads(data)
    )
    status, data, _ = exchange(path, port=3001, headers=signed)
    assert status == 200 and json.loads(data)["id"] == case_id
    status, data, content_headers = exchange(f"{path}/reports/{report_id}/pdf", port=3001, headers=signed)
    assert status == 200 and data.startswith(b"%PDF-")
    assert "attachment" in dict((key.lower(), value) for key, value in content_headers)["content-disposition"]
    assert exchange(path + "/notes", "POST", {}, port=3001,
                    headers=signed | {"Origin": "http://foreign.example.org"})[0] == 403


def verify_worker(payload, token):
    compose("stop", "worker")
    try:
        run = api(RUN_ROOT, "POST", payload, token, expected=201)
        assert run["status"] == "queued"
        run_path = f"{RUN_ROOT}/{run['id']}"
        assert api(RUN_ROOT, "POST", payload, token, expected=201)["id"] == run["id"]
        api(f"{run_path}/review", "POST", {"decision": "approved", "note": "Premature review"}, token, expected=409)
        expire_lease = (
            "import sys; from datetime import timedelta; from app.nexus import claim; "
            "from app.database import SessionLocal; from app.models import InvestigationTask, utc_now_naive; "
            "_, task_id, _ = claim(sys.argv[1]); db = SessionLocal(); "
            "db.get(InvestigationTask, task_id).lease_until = utc_now_naive() - timedelta(seconds=1); "
            "db.commit(); db.close()"
        )
        compose("exec", "-T", "api", "python", "-c", expire_lease, run["id"])
    finally:
        compose("start", "worker")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = api(run_path, token=token)
        if run["status"] == "awaiting_approval":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Investigation did not reach human review after worker restart")
    assert len(run["tasks"]) == 7 and all(task["status"] == "completed" for task in run["tasks"])
    assert any(attempt["status"] == "timed_out" for task in run["tasks"] for attempt in task["history"])
    confirmed = api(f"{run_path}/review", "POST", {
        "decision": "approved", "note": "Synthetic test reviewer checked the recorded limitations.",
    }, token)
    assert confirmed["status"] == "approved"
    report = api(f"{run_path}/report", token=token)
    assert report["sha256"] == checksum(report["snapshot"])
    return run_path


def verify():
    assert "(head)" in compose("exec", "-T", "api", "python", "-m", "alembic", "current")
    compose("exec", "-T", "api", "python", "-m", "alembic", "check")
    owner, credentials = tenant(8002)
    other, _ = tenant(8002)
    token, foreign = owner["access_token"], other["access_token"]
    case = create_case(token)
    uri = f"{CASE_ROOT}/{case['id']}"
    api(uri, token=foreign, expected=404)
    concurrent_edit(f"{uri}/assignment", "PUT", {"expected_version": case["version"],
                    "investigator_id": owner["user"]["id"], "team": "Synthetic verification"}, token)
    evidence_id = upload(owner, ARTIFACT, "lab.txt", "text/plain")["id"]
    item = api(f"{uri}/evidence", "POST", {"evidence_id": evidence_id, "classification": "log",
               "purpose": "Register synthetic integration evidence."}, token, expected=201)
    assert item["size_bytes"] == len(ARTIFACT) and item["original_filename"] == "lab.txt"
    custody = f"{uri}/evidence/{evidence_id}/custody"
    concurrent_edit(custody, "POST", {"action": "verify", "expected_sequence": 1,
                                    "purpose": "Verify both digests of the synthetic fixture."}, token)
    assert [row["action"] for row in api(custody, token=token)["events"]] == ["registered", "verified"]
    api(custody, token=foreign, expected=404)
    exported = exchange(f"{uri}/evidence/{evidence_id}/export", "POST", {"purpose": "Verify download"}, token)
    assert exported[0] == 200 and exported[1] == ARTIFACT
    api(f"{uri}/notes", "POST", {"category": "observation", "body": "Artifact was recorded in the test ledger.",
                                "references": [{"kind": "evidence", "object_id": evidence_id}]}, token, expected=201)
    run_path = verify_worker({"case_id": case["id"], "request_key": "synthetic-worker-smoke"}, token)
    api(run_path, token=foreign, expected=404)
    assert [row["action"] for row in api(custody, token=token)["events"]] == [
        "registered", "verified", "exported", "examined",
    ]
    report = api(f"{uri}/reports", "POST", token=token, expected=201)
    snapshot = api(f"{uri}/reports/{report['id']}/json", token=token)
    assert snapshot["integrity_hash"] == checksum(snapshot["snapshot"])
    assert len(snapshot["snapshot"]["agent_findings"]) == 7
    image_id = verify_image_upload(owner, 8002)
    verify_web(credentials, case["id"], report["id"], image_id)

    local, _ = tenant(8001)
    local_token = local["access_token"]
    local_case = create_case(local_token, port=8001)
    local_run = api(RUN_ROOT, "POST", {"case_id": local_case["id"], "request_key": "synthetic-inline-smoke"},
                    local_token, expected=201, port=8001)
    assert local_run["status"] == "awaiting_approval" and len(local_run["tasks"]) == 7
    verify_image_upload(local, 8001)
    print("PostgreSQL migration head, concurrent writes, custody, worker recovery, seven agents, case reports, and EXIF on both stacks verified.")


if __name__ == "__main__":
    verify()
