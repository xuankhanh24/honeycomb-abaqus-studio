import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from honeycomb_studio.cloud_api import create_app
from honeycomb_studio.cloud_archive import ReleaseArchive, parts
from honeycomb_studio.cloud_runtime import qualification


def test_public_contract_and_unauthorized_write():
    with TestClient(create_app()) as client:
        template = client.get("/api/template").json()
        spec = template["spec"]
        result = client.post("/api/preview", json=spec)
        assert result.status_code == 200
        assert result.json()["runs"][0]["index"] == 1
        assert result.json()["runs"][0]["resolved"]["clamp_mode"] == "perimeter"
        assert client.post("/api/jobs", json={"request_id": "a" * 32, "spec": spec}).status_code == 403
        assert client.post("/api/jobs/" + "a" * 32 + "/dispatch", json={}).status_code == 403
        assert client.get("/api/status").json()["qualified_linux_solver"] is False


def test_geometry_and_body_bounds():
    with TestClient(create_app()) as client:
        model = client.get("/api/template").json()["spec"]["model"]
        shape = client.post("/api/geometry", json=model)
        assert shape.status_code == 200
        assert len(shape.json()["walls"]) == 234
        model.update(phase_x=1e9)
        assert client.post("/api/geometry", json=model).status_code == 422
        assert client.post("/api/preview", content=b" " * 262145).status_code == 413


def test_fake_environment_receipt_is_insufficient(tmp_path, monkeypatch):
    monkeypatch.setenv("ABAQUS_RUNTIME_RECEIPT_URL", "https://example.com/fake")
    lock = tmp_path / "runtime-lock.json"
    lock.write_text(json.dumps({"smoke_receipt": {"solver_success": True}}))
    _, reasons = qualification(lock)
    assert {"blocked_environment", "blocked_license"} <= {r["status"] for r in reasons}


def test_bounded_archive_roundtrip_and_manifest_last(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    raw = b"actual ODB placeholder for transport testing only" * 4
    (source / "model.odb").write_bytes(raw)
    temporary = tmp_path / "temp"
    temporary.mkdir()
    chunks = []
    for part in parts(source / "model.odb", temporary, 17):
        chunks.append(part["path"].read_bytes())
        assert part["bytes"] <= 17
    assert b"".join(chunks) == raw
    assert list(temporary.iterdir()) == []

    class Recorder(ReleaseArchive):
        def __init__(self):
            self.limit = 17
            self.uploads = []

        def upload(self, path, name):
            self.uploads.append((name, path.read_bytes()))
            return {
                "url": "https://github.com/test/" + name,
                "bytes": path.stat().st_size,
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }

    archive = Recorder()
    manifest = archive.publish(source, attempt="test", complete=True)
    assert archive.uploads[-1][0] == "test-artifact-manifest.json"
    assert manifest["complete"] is True
    assert manifest["files"][0]["sha256"] == hashlib.sha256(raw).hexdigest()


def test_packaged_service_matches_canonical():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "web/service/source-manifest.json").read_text())
    for name, checksum in manifest.items():
        assert (root / "web/service" / name).read_bytes() == (
            root / "src/honeycomb_studio" / name
        ).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256((root / "web/service" / name).read_bytes()).hexdigest() == checksum


def test_owner_csrf_idempotency_and_qualification(monkeypatch):
    import base64

    from itsdangerous import TimestampSigner

    from honeycomb_studio import cloud_api

    class Memory:
        def __init__(self, github):
            self.data = {}

        def get(self, key):
            return self.data.get(key), None

        def update(self, key, transform):
            self.data[key] = transform(self.data.get(key))
            return self.data[key]

        def jobs(self):
            return self.data.get("index", {}).get("jobs", [])

    class Connected:
        configured = True

    monkeypatch.setattr(cloud_api, "Catalog", Memory)
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret-only")
    monkeypatch.setenv("WEB_LOCAL_HTTP", "1")
    session = base64.b64encode(json.dumps({"user_id": cloud_api.OWNER_ID, "csrf": "test-csrf"}).encode())
    with TestClient(create_app(Connected())) as client:
        client.cookies.set("session", TimestampSigner("test-secret-only").sign(session).decode())
        spec = client.get("/api/template").json()["spec"]
        body = {"request_id": "b" * 32, "profile": "research", "spec": spec}
        assert client.post("/api/jobs", json=body).status_code == 403
        headers = {"X-Honeycomb-CSRF": "test-csrf"}
        first = client.post("/api/jobs", json=body, headers=headers)
        assert first.status_code == 201
        assert client.post("/api/jobs", json=body, headers=headers).json() == first.json()
        body["spec"]["name"] = "Changed payload"
        assert client.post("/api/jobs", json=body, headers=headers).status_code == 409
        assert client.post("/api/jobs/" + "b" * 32 + "/dispatch", json={}, headers=headers).status_code == 409


def test_failed_upload_never_publishes_complete_manifest(tmp_path):
    import pytest

    (tmp_path / "data.odb").write_bytes(b"not a solver result: transport test fixture")

    class Broken(ReleaseArchive):
        limit = 4

        def __init__(self):
            self.names = []

        def upload(self, path, name):
            self.names.append(name)
            raise ConnectionError("interrupted upload")

    archive = Broken()
    with pytest.raises(ConnectionError):
        archive.publish(tmp_path, attempt="failed", complete=True)
    assert not any("manifest" in name for name in archive.names)


def test_production_entrypoint_starts_without_static_directory(tmp_path, monkeypatch):
    import runpy

    root = Path(__file__).resolve().parents[1]
    entrypoint = tmp_path / "app.py"
    entrypoint.write_bytes((root / "web/app.py").read_bytes())
    monkeypatch.syspath_prepend(str(root / "web"))
    monkeypatch.chdir(tmp_path)
    namespace = runpy.run_path(str(entrypoint))
    with TestClient(namespace["app"]) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["worker_started_in_web"] is False
