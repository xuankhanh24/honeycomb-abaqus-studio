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
    assert recovered.status()["transfers"][0]["status"] == "waiting_resume"
    monkeypatch.setattr(recovered, "start", lambda: None)
    recovered.resume(result["id"])
    action, request = recovered.tasks.get_nowait()
    assert action == "backup" and request["batch_id"] == batch["id"] and request["id"] == result["id"]


def test_preparing_and_uploading_are_resumable_after_restart(tmp_path):
    store = Store(tmp_path / "data")
    backup = DriveBackup(store, tmp_path / "config")
    for index, status in enumerate(("preparing", "uploading")):
        write_json(
            backup.states / f"bk{index:016x}.json",
            {
                "id": f"bk{index:016x}",
                "status": status,
                "offset": 123,
                "session_url": "private-upload-capability",
            },
        )
    recovered = DriveBackup(store, tmp_path / "config")
    states = recovered.status()["transfers"]
    assert len(states) == 2
    assert all(s["status"] == "waiting_resume" and s["offset"] == 123 for s in states)
    assert all("session_url" not in s for s in states)


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


def test_direct_csv_upload_keeps_its_name_and_mime_type(tmp_path, monkeypatch):
    backup = DriveBackup(Store(tmp_path / "data"), tmp_path / "config")
    file = tmp_path / "samples.csv"
    file.write_bytes(b"energy_J,SEA_J_kg\n7,12\n")
    raw = file.read_bytes()
    md5 = hashlib.md5(raw).hexdigest()
    state = backup.states / "readable" / "bk0000000000000000.json"
    write_json(
        state,
        {
            "id": "bk0000000000000000",
            "batch_id": "b1",
            "file": str(file),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "md5": md5,
            "drive_name": "samples.csv",
            "mime_type": "text/csv",
            "parent_id": "training-folder",
            "status": "prepared",
            "offset": 0,
        },
    )

    class Session:
        def __init__(self, *_):
            pass

        def post(self, *args, **kw):
            assert kw["json"]["name"] == "samples.csv"
            assert kw["json"]["mimeType"] == "text/csv"
            assert kw["json"]["parents"] == ["training-folder"]
            assert kw["headers"]["X-Upload-Content-Type"] == "text/csv"
            return Response(200, headers={"Location": "https://upload.example/session"})

        def put(self, *args, **kw):
            return Response(200, {"id": "csv-file"}) if kw.get("data") else Response(308)

        def get(self, *args, **kw):
            return Response(200, {"id": "csv-file", "size": str(len(raw)), "md5Checksum": md5})

        def close(self):
            pass

    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Session)
    monkeypatch.setattr(backup, "credentials", lambda: type("Creds", (), {"to_json": lambda _: "{}"})())
    monkeypatch.setattr(backup, "_save_token", lambda _: None)
    assert backup._upload_file(state)["status"] == "verified"


def test_drive_folder_retry_repeats_stable_key_after_lost_response(tmp_path, monkeypatch):
    from requests.exceptions import ReadTimeout

    backup = DriveBackup(Store(tmp_path / "data"), tmp_path / "config")
    calls = []

    def create(session, name, key, parent):
        calls.append((name, key, parent))
        if len(calls) == 1:
            raise ReadTimeout("Folder creation response lost")
        return "existing-folder"

    monkeypatch.setattr(backup, "_folder_once", create)
    monkeypatch.setattr("honeycomb_studio.backup.time.sleep", lambda _: None)
    assert backup._folder(object(), "training", "stable-key", "parent") == "existing-folder"
    assert calls == [("training", "stable-key", "parent")] * 2
