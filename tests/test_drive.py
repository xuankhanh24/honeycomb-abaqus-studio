import hashlib
import json

from honeycomb_studio.backup import DriveBackup
from honeycomb_studio.models import BatchSpec
from honeycomb_studio.store import Store, write_json


def test_backup_queue_survives_before_archive_is_prepared(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec())
    config = tmp_path / "config"
    backup = DriveBackup(store, config)
    (config / "drive-token.dpapi").write_bytes(b"test-only-never-decrypted")
    monkeypatch.setattr(backup, "start", lambda: None)
    result = backup.enqueue(batch["id"])
    state = json.loads((backup.states / (result["id"] + ".json")).read_text())
    assert state["status"] == "queued"
    recovered = DriveBackup(store, config)
    monkeypatch.setattr(recovered, "start", lambda: None)
    recovered.resume(result["id"])
    action, request = recovered.tasks.get_nowait()
    assert action == "backup" and request["batch_id"] == batch["id"] and request["id"] == result["id"]


class Response:
    def __init__(self, code, body=None, headers=None):
        self.status_code = code
        self.body = body or {}
        self.headers = headers or {}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP " + str(self.status_code))


def test_upload_lost_ack_probes_offset_and_verified_resume_is_noop(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    backup = DriveBackup(store, tmp_path / "config")
    file = tmp_path / "x.zip"
    file.write_bytes(b"0123456789" * 100)
    raw = file.read_bytes()
    md5 = hashlib.md5(raw).hexdigest()
    sha = hashlib.sha256(raw).hexdigest()
    state = backup.states / "bk0123456789abcdef.json"
    write_json(
        state,
        {
            "id": "bk0123456789abcdef",
            "batch_id": "b1",
            "file": str(file),
            "bytes": len(raw),
            "sha256": sha,
            "md5": md5,
            "offset": 0,
            "status": "prepared",
        },
    )

    class Session:
        def __init__(self, creds):
            self.committed = False

        def post(self, *args, **kw):
            return Response(200, headers={"Location": "https://upload.example/session"})

        def put(self, url, **kw):
            if kw.get("data"):
                self.committed = True
                raise TimeoutError("Response lost after commit")
            return Response(200, {"id": "drive-file"}) if self.committed else Response(308)

        def get(self, *args, **kw):
            return Response(200, {"id": "drive-file", "size": str(len(raw)), "md5Checksum": md5})

        def close(self):
            pass

    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Session)
    monkeypatch.setattr("honeycomb_studio.backup.time.sleep", lambda _: None)
    monkeypatch.setattr(backup, "credentials", lambda: type("Creds", (), {"to_json": lambda _: "{}"})())
    monkeypatch.setattr(backup, "_folder", lambda *args: "owned-folder")
    monkeypatch.setattr(backup, "_save_token", lambda _: None)
    result = backup.upload(state)
    assert result["status"] == "verified" and result["offset"] == len(raw)
    assert "session_url" not in json.loads(state.read_text())
    assert backup.upload(state)["status"] == "verified"
