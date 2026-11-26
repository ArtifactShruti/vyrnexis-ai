from hashlib import sha256, sha512
from io import BytesIO
import struct
import subprocess

from PIL import Image

from app.image_metadata import PREFIX_LIMIT, inspect_image
from app.models import EvidenceImageMetadata
from test_api import register
from test_forensics_nexus import new_case


def photo(*, with_exif=True):
    buffer = BytesIO()
    fields = Image.Exif()
    if with_exif:
        fields[274] = 6
        fields[34853] = {1: "N"}
        fields[34665] = {36867: "2026:01:03 04:05:06", 40962: 7, 40963: 5, 42033: "fixture-device-serial"}
    Image.new("RGB", (7, 5)).save(buffer, format="JPEG", exif=fields)
    return buffer.getvalue()


def test_bounded_header_inspector():
    assert inspect_image(photo(with_exif=False)) == {"status": "no_supported_fields", "fields": {}}
    assert inspect_image(b"unrecognized bytes")["status"] == "unsupported"
    assert inspect_image(b"\xff\xd8\xff\xe1\x00\x20Exif\x00\x00")["status"] == "unreadable"
    oversized_ifd = b"II*\x00" + struct.pack("<I", PREFIX_LIMIT) + bytes(PREFIX_LIMIT - 8) + b"\x00" * 6
    assert inspect_image(oversized_ifd)["status"] == "limit_reached"
    for order, signature in ((">", b"MM\x00*"), ("<", b"II*\x00")):
        header = signature + struct.pack(order + "IH", 8, 2)
        width = struct.pack(order + "HHII", 256, 4, 1, 820)
        height = struct.pack(order + "HHIHH", 257, 3, 1, 215, 0)
        result = inspect_image(header + width + height + b"\x00" * 4)
        assert result == {"status": "extracted", "fields": {"width": 820, "height": 215}}


def test_inspector_timeout_is_recorded(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("fixture", kwargs["timeout"])

    monkeypatch.setattr("app.image_metadata.subprocess.run", timeout)
    assert inspect_image(photo()) == {"status": "unavailable", "fields": {}}


def test_metadata_is_scoped_derived_and_persisted_in_case_report(client):
    owner, auth = register(client, "image")
    _, foreign = register(client, "image-other")
    payload = photo()
    uploaded = client.post(
        "/api/v1/evidence", params={"organization_id": owner["organization"]["id"], "name": "Synthetic photo"},
        files={"file": ("fixture.jpg", payload, "application/octet-stream")}, headers=auth,
    )
    assert uploaded.status_code == 200, uploaded.text
    data = uploaded.json()
    metadata = data["image_metadata"]
    assert metadata["status"] == "extracted"
    assert metadata["fields"] == {"width": 7, "height": 5, "orientation": 6, "capture_time": "2026-01-03T04:05:06"}
    assert "fixture-device-serial" not in uploaded.text
    assert (data["sha256"], data["sha512"]) == (sha256(payload).hexdigest(), sha512(payload).hexdigest())
    assert client.get("/api/v1/evidence", headers=foreign).json() == []
    case = new_case(client, auth)
    case_url = f"/api/v1/forensic-cases/{case['id']}"
    enrolled = client.post(f"{case_url}/evidence", headers=auth, json={
        "evidence_id": data["id"], "classification": "image", "purpose": "Register original fixture",
    })
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.json()["image_metadata"] == metadata
    evidence_url = f"{case_url}/evidence/{data['id']}"
    assert client.get(f"{evidence_url}/custody", headers=foreign).status_code == 404
    assert [row["action"] for row in client.get(f"{evidence_url}/custody", headers=auth).json()["events"]] == ["registered"]
    report = client.post(f"{case_url}/reports", headers=auth).json()
    report_url = f"{case_url}/reports/{report['id']}"
    assert client.get(f"{report_url}/json", headers=auth).json()["snapshot"]["evidence"][0]["image_metadata"] == metadata
    assert client.get(f"{report_url}/pdf", headers=auth).content.startswith(b"%PDF-")
    downloaded = client.post(f"{evidence_url}/export", headers=auth, json={"purpose": "Check original bytes"})
    assert downloaded.status_code == 200 and downloaded.content == payload


def test_legacy_enrolled_image_is_inspected_after_verified_bytes(client):
    owner, auth = register(client, "image-legacy")
    recorded = client.post(
        "/api/v1/evidence", params={"organization_id": owner["organization"]["id"], "name": "Legacy photo"},
        files={"file": ("fixture.jpg", photo(), "image/jpeg")}, headers=auth,
    )
    evidence_id = recorded.json()["id"]
    with client.app.state.test_session_factory.begin() as db:
        db.delete(db.get(EvidenceImageMetadata, evidence_id))
    assert client.get("/api/v1/evidence", headers=auth).json()[0]["image_metadata"] is None
    case = new_case(client, auth)
    case_url = f"/api/v1/forensic-cases/{case['id']}"
    enrolled = client.post(f"{case_url}/evidence", headers=auth, json={
        "evidence_id": evidence_id, "classification": "image", "purpose": "Register legacy fixture",
    })
    assert enrolled.status_code == 201
    assert enrolled.json()["image_metadata"] is None
    assert client.post(f"/api/v1/evidence/{evidence_id}/verify", headers=auth).status_code == 409
    custody = f"{case_url}/evidence/{evidence_id}/custody"
    response = client.post(custody, headers=auth, json={
        "action": "verify", "purpose": "Compare both stored hashes and read metadata", "expected_sequence": 1,
    })
    assert response.status_code == 200 and response.json()["action"] == "verified"
    assert client.get(case_url, headers=auth).json()["evidence"][0]["image_metadata"]["status"] == "extracted"
    chain = client.get(custody, headers=auth).json()
    assert chain["chain_status"] == "valid" and [row["action"] for row in chain["events"]] == ["registered", "verified"]
