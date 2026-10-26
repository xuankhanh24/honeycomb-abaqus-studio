import json
import shutil
from pathlib import Path

import pytest

from honeycomb_studio.backup import DriveBackup
from honeycomb_studio.data import checksum
from honeycomb_studio.models import Axis, BatchSpec
from honeycomb_studio.retained import prepare_readable, retained_root, verify_retained
from honeycomb_studio.store import Store, write_json


def study(tmp_path):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec(axes=[Axis(parameter="energy_J", values=[1, 2, 3])]))
    runs = store.list("runs", batch["id"])
    for run in runs:
        run.update(status="completed", summary={"SEA_J_kg": 12}, quality={"ml_eligible": True})
        store.save("runs", run)
    runs[-1]["quality"]["ml_eligible"] = False
    store.save("runs", runs[-1])
    return store, batch, runs


def test_reports_and_whole_job_training_survive_removing_simulation_library(tmp_path):
    store, batch, runs = study(tmp_path)
    original = Path(runs[0]["path"]) / "reports" / "existing.pdf"
    original.parent.mkdir()
    original.write_bytes(b"%PDF-retention-test")
    root = prepare_readable(store, batch["id"], "bk0000000000000001")
    assert root.is_relative_to(retained_root(store)) and not root.is_relative_to(store.root)
    assert (root / "reports/batch-report.pdf").read_bytes().startswith(b"%PDF")
    assert (root / "reports/batch-report.docx").read_bytes().startswith(b"PK")
    assert (root / "training/samples.csv").exists() and (root / "training/samples.parquet").exists()
    record = json.loads((root / "training/dataset.json").read_text(encoding="utf-8"))
    assert record["samples"] == 2 and set(record["run_ids"]) == {r["id"] for r in runs[:2]}
    assert len((root / "training/job-coverage.csv").read_text(encoding="utf-8-sig").splitlines()) == 4
    expected = checksum(root / "artifact-manifest.json")
    assert store.root.resolve().parent == tmp_path.resolve()
    store.db.close()
    shutil.rmtree(store.root.resolve())
    verify_retained(root, expected)
    assert list((root / "run-reports").rglob("existing.pdf"))[0].read_bytes() == b"%PDF-retention-test"


def test_backup_without_eligible_samples_keeps_reports_and_explains_empty_training(tmp_path):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec())
    root = prepare_readable(store, batch["id"], "bk0000000000000002")
    info = json.loads((root / "training/dataset.json").read_text(encoding="utf-8"))
    assert info["samples"] == 0
    assert "Không có lượt" in info["note"]
    assert not (root / "training/samples.csv").exists()
    assert (root / "reports/batch-report.pdf").exists()


def test_review_histories_and_settings_survive_without_becoming_training_samples(tmp_path):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec())
    run = store.list("runs", batch["id"])[0]
    attempt = Path(run["path"]) / "attempts/001"
    history = b"time_s,ALLPD_J\n0.006,5.98\n"
    (attempt / "extracted").mkdir(parents=True)
    (attempt / "extracted/impact_history.csv").write_bytes(history)
    run.update(status="review", quality={"ml_eligible": False},
               attempts=[{"number": 1, "path": str(attempt)}])
    store.save("runs", run)
    root = prepare_readable(store, batch["id"], "bk0000000000000009")
    assert (root / "run-data" / run["id"] / "attempt-001/extracted/impact_history.csv").read_bytes() == history
    assert (root / "run-data" / run["id"] / "requested-input.json").exists()
    assert json.loads((root / "training/dataset.json").read_text(encoding="utf-8"))["samples"] == 0


def test_partial_readable_failure_is_not_verified_and_resume_never_reuploads_archive(tmp_path, monkeypatch):
    store, batch, _ = study(tmp_path)
    identity = "bk0000000000000003"
    root = prepare_readable(store, batch["id"], identity)
    backup = DriveBackup(store, tmp_path / "config")
    state_path = backup.states / (identity + ".json")
    write_json(
        state_path,
        {
            "id": identity,
            "batch_id": batch["id"],
            "archive_verified": True,
            "status": "archive_verified",
            "readable_path": str(root),
            "readable_manifest_sha256": checksum(root / "artifact-manifest.json"),
        },
    )

    class Session:
        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Session)
    monkeypatch.setattr(backup, "credentials", lambda: object())
    monkeypatch.setattr(backup, "_folder", lambda session, name, key, parent=None: key)
    uploaded = []
    failures_left = [3]
    monkeypatch.setattr("honeycomb_studio.readable_backup.time.sleep", lambda _: None)

    def send(path):
        assert path != state_path, "Verified ZIP must not be uploaded again"
        child = json.loads(path.read_text(encoding="utf-8"))
        if child["status"] == "verified":
            return child
        if child["drive_name"] == "samples.csv" and failures_left[0]:
            failures_left[0] -= 1
            raise RuntimeError("Simulated network loss")
        uploaded.append(child["id"])
        child.update(
            status="verified",
            drive_file_id=child["id"],
            verified_at="test-time",
            web_url="https://drive.google.com/file/d/" + child["id"] + "/view",
        )
        write_json(path, child)
        return child

    monkeypatch.setattr(backup, "_upload_file", send)
    with pytest.raises(RuntimeError, match="network loss"):
        backup.upload(state_path)
    interrupted = json.loads(state_path.read_text(encoding="utf-8"))
    assert interrupted["status"] == "waiting_readable" and not interrupted.get("readable_verified")
    assert interrupted["archive_verified"]
    result = backup.upload(state_path)
    assert result["status"] == "verified" and result["readable_verified"]
    assert len(uploaded) == len(set(uploaded)) == result["readable_files_total"]
    assert {r["path"] for r in result["readable_files"]} >= {
        "reports/batch-report.pdf",
        "training/samples.csv",
    }
    assert (root / "drive-index.json").exists()
    assert "session_url" not in (root / "drive-index.json").read_text(encoding="utf-8")
    assert backup.upload(state_path)["readable_verified"]


def test_frozen_products_reject_modified_files_before_upload(tmp_path):
    store, batch, _ = study(tmp_path)
    root = prepare_readable(store, batch["id"], "bk0000000000000004")
    (root / "training/samples.csv").write_text("changed")
    with pytest.raises(ValueError, match="Checksum"):
        verify_retained(root)


def test_normal_backup_always_prepares_external_pdf_and_whole_job_training(tmp_path, monkeypatch):
    store, batch, _ = study(tmp_path)
    backup = DriveBackup(store, tmp_path / "config")
    monkeypatch.setattr(backup, "upload", lambda path: json.loads(path.read_text(encoding="utf-8")))
    state = backup.backup_batch(batch["id"])
    root = Path(state["readable_path"])
    assert not root.is_relative_to(store.root)
    assert Path(state["file"]).exists()
    assert state["status"] == "prepared" and not state.get("readable_verified")
    assert (root / "reports/batch-report.pdf").exists()
    assert json.loads((root / "training/dataset.json").read_text(encoding="utf-8"))["samples"] == 2
