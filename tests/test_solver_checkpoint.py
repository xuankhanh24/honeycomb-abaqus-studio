"""A completed solve must be durable before any fallible ODB postprocessing."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import REPOSITORY
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec
from honeycomb_studio.solver_checkpoint import (
    SavedSolverEngine,
    physics_hashes,
    publish_solver_checkpoint,
    restore_solver_checkpoint,
    snapshot_view,
)
from honeycomb_studio.store import Store, write_json


def completed_solver(root):
    store = Store(root)
    batch = store.create(BatchSpec(render_images=False))
    run = store.list("runs", batch["id"])[0]
    attempt = Path(run["path"]) / "attempts/001"
    (attempt / "raw").mkdir(parents=True)
    (attempt / "raw/hc.odb").write_bytes(b"native ODB transport fixture")
    (attempt / "raw/hc.sta").write_text(
        " 101338 6.000E-03 6.000E-03 00:23:48 5.704E-08 26813 3.013E+02 7.002E+03\n"
        " THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n"
    )
    write_json(attempt / "solver-complete.json", {"sta": {"solver_success": True}})
    run["attempts"] = [{"number": 1, "path": str(attempt), "job_name": "hc", "process": None}]
    store.save("runs", run)
    return store, batch, run


def test_solver_checkpoint_precedes_failed_extraction(tmp_path, monkeypatch):
    store, batch, run = completed_solver(tmp_path)
    engine = Engine(store, abaqus="must-not-launch-solver")
    events = []
    engine.solver_sink = lambda r, b: events.append("solver_saved")

    def extract(*args):
        events.append("extract")
        raise RuntimeError("extraction interrupted")

    monkeypatch.setattr(engine, "_postprocess", extract)
    engine._execute(run, batch)
    assert events == ["solver_saved", "extract"]
    assert store.get("runs", run["id"])["status"] == "failed"
    assert len(store.get("runs", run["id"])["attempts"]) == 1
    store.db.close()


def test_failed_solver_backup_blocks_extraction(tmp_path, monkeypatch):
    store, batch, run = completed_solver(tmp_path)
    engine = Engine(store, abaqus="must-not-launch-solver")

    def unavailable(*args):
        raise RuntimeError("checkpoint upload interrupted")

    engine.solver_sink = unavailable
    extracted = []
    monkeypatch.setattr(engine, "_postprocess", lambda *args: extracted.append(True))
    engine._execute(run, batch)
    assert extracted == []
    result = store.get("runs", run["id"])
    assert result["status"] == "failed" and "checkpoint upload" in result["error"]
    store.db.close()


@pytest.fixture
def archived_solver(tmp_path, monkeypatch):
    import hashlib

    from honeycomb_studio.models import digest

    store, batch, run = completed_solver(tmp_path / "original")
    raw = Path(run["attempts"][-1]["path"]) / "raw"
    (raw / "hc.inp").write_text("original INP transport fixture")
    (raw / "hc.odb").write_bytes(b"ODB transport fixture, not a native Abaqus result\n" * 100)
    (raw / "private.json").write_text("must not be published")
    (store.root / "credentials").mkdir()
    (store.root / "credentials/oauth.json").write_text("must not be published")
    run["attempts"][-1]["software"] = {"source_sha256": physics_hashes()}
    store.save("runs", run)
    payloads, assets, names = {}, {}, {}

    def upload(self, path, name):
        url = f"https://github.com/{REPOSITORY}/releases/download/snapshot/{name}"
        data = path.read_bytes()
        if url in payloads:
            assert payloads[url] == data, "Immutable checkpoint asset was rewritten"
        payloads[url] = data
        identity = names.setdefault(name, len(names) + 1)
        asset = {"id": identity, "browser_download_url": url, "size": len(data),
                 "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        assets[identity] = asset
        return {"url": url, "bytes": len(data), "asset_id": identity, "digest": asset["digest"]}

    monkeypatch.setattr(ReleaseArchive, "upload", upload)
    runtime = {"release": "2020", "python": "2.7 fixture"}
    job = {"spec": batch["spec"], "input_hash": digest(batch["spec"])}
    reference = publish_solver_checkpoint(
        store.root, run, batch, runtime, job, ReleaseArchive(None, 1, limit=1024), "workflow-123", "b" * 40
    )
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=payloads[str(request.url)]))) as client:
        github = SimpleNamespace(client=client, repo=lambda method, path: assets[int(path.rsplit("/", 1)[1])])
        yield SimpleNamespace(store=store, batch=batch, run=run, job={**job, "postprocess_source": reference},
                              runtime=runtime, reference=reference, assets=assets, payloads=payloads, github=github)
    store.db.close()


def test_verified_solver_roundtrip_reuses_odb_without_new_fe(tmp_path, monkeypatch, archived_solver):
    import json

    source = archived_solver
    manifest = json.loads(source.payloads[source.reference["manifest"]["url"]])
    assert manifest["complete"] is False
    paths = [f["path"] for f in manifest["files"]]
    assert "solver-snapshot.json" in paths
    assert not any("private" in name or "credentials" in name for name in paths)
    assert len(next(f for f in manifest["files"] if f["path"].endswith("hc.odb"))["parts"]) > 1
    restored = Store(tmp_path / "recovered")
    try:
        batch = restore_solver_checkpoint(restored, source.job, BatchSpec.model_validate(source.batch["spec"]),
                                          source.runtime, source.github)
        run = restored.list("runs")[0]
        original = Path(source.run["attempts"][0]["path"]) / "raw/hc.odb"
        odb = Path(run["attempts"][0]["path"]) / "raw/hc.odb"
        assert odb.read_bytes() == original.read_bytes()
        assert odb != original and len(run["attempts"]) == 1
        engine = SavedSolverEngine(restored, abaqus="must-not-start-FE")
        exports = []
        monkeypatch.setattr(engine, "_postprocess", lambda r, a, b: exports.append(a["path"]))
        engine._execute(run, batch)
        assert exports == [run["attempts"][0]["path"]]
        assert len(restored.get("runs", run["id"])["attempts"]) == 1
    finally:
        restored.db.close()


@pytest.mark.parametrize("problem", ["manifest_digest", "runtime", "input", "ODB_part", "physics"])
def test_checkpoint_damage_never_falls_back_to_a_new_solve(tmp_path, monkeypatch, archived_solver, problem):
    source = archived_solver
    runtime = dict(source.runtime)
    if problem == "manifest_digest":
        source.assets[source.reference["manifest"]["asset_id"]]["digest"] = "sha256:" + "0" * 64
    elif problem == "runtime":
        runtime["release"] = "different"
    elif problem == "input":
        source.job["input_hash"] = "0" * 64
    elif problem == "physics":
        monkeypatch.setattr("honeycomb_studio.solver_checkpoint.physics_hashes", lambda: {"models.py": "changed"})
    else:
        import json

        manifest = json.loads(source.payloads[source.reference["manifest"]["url"]])
        odb = next(f for f in manifest["files"] if f["path"].endswith("hc.odb"))
        source.payloads[odb["parts"][-1]["url"]] = b"corrupted native bytes"
    restored = Store(tmp_path / "rejected")
    try:
        with pytest.raises(ValueError):
            restore_solver_checkpoint(restored, source.job, BatchSpec.model_validate(source.batch["spec"]),
                                      runtime, source.github)
        assert restored.list("runs") == []
    finally:
        restored.db.close()


@pytest.mark.parametrize("phase", ["building", "checking", "solving"])
def test_postprocess_only_engine_refuses_every_fe_phase(tmp_path, phase):
    store = Store(tmp_path)
    try:
        with pytest.raises(ValueError, match="forbids a new FE"):
            SavedSolverEngine(store)._monitor({}, {}, phase, ["forbidden"])
    finally:
        store.db.close()


@pytest.mark.parametrize("problem", ["partial_STA", "locked", "live", "empty_ODB", "synthetic"])
def test_backup_rejects_unfinished_or_live_native_outputs(tmp_path, archived_solver, problem):
    source = archived_solver
    folder = Path(source.run["attempts"][0]["path"])
    if problem == "partial_STA":
        (folder / "raw/hc.sta").write_text(" THE ANALYSIS HAS NOT BEEN COMPLETED\n")
    elif problem == "locked":
        (folder / "raw/hc.lck").touch()
    elif problem == "live":
        source.run["attempts"][0]["process"] = {"pid": 123}
    elif problem == "empty_ODB":
        (folder / "raw/hc.odb").write_bytes(b"")
    else:
        source.run["test_only"] = True
    with pytest.raises(ValueError):
        snapshot_view(source.store.root, tmp_path / "rejected-view", source.run, source.batch,
                      source.runtime, source.job, "b" * 40)
    assert not list((tmp_path / "rejected-view").rglob("*.odb"))


@pytest.mark.parametrize("problem", [None, "runtime", "physics", "ODB_part", "unfinished_STA"])
def test_legacy_interrupted_archive_reopens_only_original_solver(tmp_path, monkeypatch, archived_solver, problem):
    """The old worker archived its closed ODB only after extraction was interrupted."""
    import copy
    import hashlib
    import json

    from honeycomb_studio.models import digest

    source = archived_solver
    reference = copy.deepcopy(source.reference)
    manifest = json.loads(source.payloads[reference["manifest"]["url"]])
    manifest["files"] = [f for f in manifest["files"] if f["path"] != "solver-snapshot.json"]
    for name, value in [("runtime-lock.json", source.runtime), ("cloud-request.json", {
        "spec": source.job["spec"], "input_hash": source.job["input_hash"],
        "workflow_run_id": 123,
    })]:
        data = json.dumps(value).encode()
        checksum = hashlib.sha256(data).hexdigest()
        url = f"https://github.com/{REPOSITORY}/releases/download/simulation-fixture/legacy-{checksum}.part"
        source.payloads[url] = data
        manifest["files"].append({"path": name, "bytes": len(data), "sha256": checksum,
            "parts": [{"index": 0, "offset": 0, "bytes": len(data), "sha256": checksum,
                       "digest": "sha256:" + checksum, "url": url}]})
    if problem == "unfinished_STA":
        record = next(file for file in manifest["files"] if file["path"].endswith("hc.sta"))
        data = b" THE ANALYSIS HAS NOT BEEN COMPLETED\n"
        checksum = hashlib.sha256(data).hexdigest()
        url = f"https://github.com/{REPOSITORY}/releases/download/simulation-fixture/legacy-{checksum}.part"
        source.payloads[url] = data
        record.update(bytes=len(data), sha256=checksum, parts=[{
            "index": 0, "offset": 0, "bytes": len(data), "sha256": checksum,
            "digest": "sha256:" + checksum, "url": url}])
    data = json.dumps(manifest).encode()
    source.payloads[reference["manifest"]["url"]] = data
    reference.update(kind="honeycomb-archived-solver-postprocess-v1",
                     runtime_hash=digest(source.runtime))
    reference["manifest"].update(bytes=len(data), digest="sha256:" + hashlib.sha256(data).hexdigest())
    source.assets[reference["manifest"]["asset_id"]].update(
        size=len(data), digest=reference["manifest"]["digest"])
    restored = Store(tmp_path / "legacy-recovered")
    try:
        runtime = dict(source.runtime)
        if problem == "runtime":
            runtime["release"] = "wrong"
        elif problem == "physics":
            monkeypatch.setattr("honeycomb_studio.solver_checkpoint.physics_hashes", lambda: {"models.py": "wrong"})
        elif problem == "ODB_part":
            record = next(file for file in manifest["files"] if file["path"].endswith("hc.odb"))
            source.payloads[record["parts"][-1]["url"]] = b"corrupted native ODB"
        if problem:
            with pytest.raises(ValueError):
                restore_solver_checkpoint(restored, {**source.job, "postprocess_source": reference},
                    BatchSpec.model_validate(source.batch["spec"]), runtime, source.github)
            assert restored.list("runs") == []
            return
        batch = restore_solver_checkpoint(restored, {**source.job, "postprocess_source": reference},
            BatchSpec.model_validate(source.batch["spec"]), runtime, source.github)
        run = restored.list("runs")[0]
        assert len(run["attempts"]) == 1
        original = Path(source.run["attempts"][0]["path"]) / "raw/hc.odb"
        recovered = Path(run["attempts"][0]["path"]) / "raw/hc.odb"
        assert recovered.read_bytes() == original.read_bytes()
        engine = SavedSolverEngine(restored, abaqus="must-not-start-FE")
        exports = []
        monkeypatch.setattr(engine, "_postprocess", lambda r, a, b: exports.append(a["path"]))
        engine._execute(run, batch)
        assert exports == [run["attempts"][0]["path"]]
        assert restored.get("runs", run["id"])["solver_recovery"]["new_FE_solve"] is False
    finally:
        restored.db.close()
