from pathlib import Path
from types import SimpleNamespace

from honeycomb_studio.engine import Engine, LicenseUnavailable
from honeycomb_studio.estimates import predict
from honeycomb_studio.models import BatchSpec, ModelSpec
from honeycomb_studio.store import Store, write_json


def test_license_failure_is_waiting_not_physics_failure(tmp_path, monkeypatch):
    store = Store(tmp_path)
    engine = Engine(store)
    b = store.create(BatchSpec())
    r = store.list("runs", b["id"])[0]
    monkeypatch.setattr(
        "honeycomb_studio.engine.psutil.virtual_memory", lambda: SimpleNamespace(available=8 * 1024**3)
    )

    def unavailable(*args, **kw):
        raise LicenseUnavailable("Unable to checkout license")

    monkeypatch.setattr(engine, "_monitor", unavailable)
    engine._execute(r, b)
    run = store.get("runs", r["id"])
    assert run["status"] == "waiting_license" and run["license_retry_count"] == 1
    assert run["retry_after"] > 0


def test_orphan_recovery_requires_restart_only_after_owned_process_finishes(tmp_path):
    store = Store(tmp_path)
    b = store.create(BatchSpec())
    r = store.list("runs", b["id"])[0]
    r.update(
        status="solving",
        attempts=[
            {
                "number": 1,
                "path": str(Path(r["path"]) / "attempts/001"),
                "job_name": "hc",
                "process": {"pid": 99999999, "created": 1},
            }
        ],
    )
    store.save("runs", r)
    engine = Engine(store, fake=True)
    recovered = store.get("runs", r["id"])
    assert recovered["status"] == "recovering"
    engine._execute(recovered, store.get("batches", b["id"]))
    assert store.get("runs", r["id"])["status"] == "interrupted"
    assert len(store.get("runs", r["id"])["attempts"]) == 1


def test_failed_postprocess_does_not_relaunch_solver(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b = store.create(BatchSpec())
    r = store.list("runs", b["id"])[0]
    path = Path(r["path"]) / "attempts/001"
    write_json(path / "solver-complete.json", {"complete": True})
    r.update(status="failed", attempts=[{"number": 1, "path": str(path), "job_name": "hc"}])
    store.save("runs", r)
    engine = Engine(store, fake=True)
    called = []
    monkeypatch.setattr(engine, "_postprocess", lambda run, a, batch: called.append(a["number"]))
    engine._execute(r, b)
    assert called == [1] and len(r["attempts"]) == 1


def test_cold_estimate_is_mesh_sensitive_and_measured_history_can_calibrate():
    reference = ModelSpec().resolved()
    quick = ModelSpec(mesh_preset="quick").resolved()
    fine = ModelSpec(mesh_preset="fine").resolved()
    assert (
        predict(quick)["solver_minutes"]
        < predict(reference)["solver_minutes"]
        < predict(fine)["solver_minutes"]
    )
    measured = predict(reference, [{"model": reference, "durations": {"solving": 1200, "extracting": 300}}])
    assert measured["solver_minutes"] == 20 and measured["other_phase_minutes"]["extracting"] == 5
    assert predict(fine, [{"model": reference, "durations": {"solving": 1200}}])["solver_minutes"] > 20


def test_backup_failure_cannot_turn_success_into_solver_failure(tmp_path, monkeypatch):
    store = Store(tmp_path)
    b = store.create(BatchSpec(render_images=False, backup_after_run=True))
    r = store.list("runs", b["id"])[0]
    path = Path(r["path"]) / "attempts/001"
    (path / "extracted").mkdir(parents=True)
    (path / "raw").mkdir()
    write_json(path / "extracted/complete.json", {"complete": True})
    write_json(path / "extracted/inventory.json", {"fields": []})
    a = {"number": 1, "path": str(path), "job_name": "hc"}
    r["attempts"] = [a]
    engine = Engine(store)

    def fail(*args):
        raise ValueError("OAuth not connected")

    engine.backup = SimpleNamespace(enqueue=fail)
    summary = {
        "initial_kinetic_energy_J": 7,
        "solver_completed": True,
        "maximum_energy_balance_drift_percent": 0.1,
        "artificial_energy_over_max_internal_percent": 1,
    }
    monkeypatch.setattr("honeycomb_studio.engine.history_summary", lambda *args, **kwargs: (summary, []))
    monkeypatch.setattr(
        "honeycomb_studio.engine.run_report", lambda *args, **kwargs: str(path / "report.pdf")
    )
    monkeypatch.setattr("honeycomb_studio.engine.batch_report", lambda *args: None)
    engine._postprocess(r, a, b)
    saved = store.get("runs", r["id"])
    assert saved["status"] == "completed" and saved["backup_status"] == "waiting_connection"


def test_native_smoke_scope_applies_before_reports_viewer_and_completion_event(tmp_path, monkeypatch):
    import json

    store = Store(tmp_path)
    batch = store.create(BatchSpec(data_profile="smoke", render_images=False))
    run = store.list("runs", batch["id"])[0]
    path = Path(run["path"]) / "attempts/001"
    (path / "extracted").mkdir(parents=True)
    (path / "raw").mkdir()
    # Clearly labelled transport fixture: no Abaqus or actual ODB is used here.
    (path / "raw/hc.odb").write_bytes(b"test-only ODB placeholder")
    write_json(path / "extracted/complete.json", {"complete": True})
    write_json(path / "extracted/inventory.json", {"fields": []})
    attempt = {"number": 1, "path": str(path), "job_name": "hc"}
    run["attempts"] = [attempt]
    engine = Engine(store)
    summary = {"initial_kinetic_energy_J": 7, "solver_completed": True,
               "maximum_energy_balance_drift_percent": .01, "artificial_energy_over_max_internal_percent": 1}
    monkeypatch.setattr("honeycomb_studio.engine.history_summary", lambda *a, **kw: (summary, []))
    checked = []

    def report(r, *args, **kwargs):
        assert r["quality"]["ml_eligible"] is False
        assert r["quality"]["physical_validation"] == "environment_smoke_only"
        assert r["summary"]["data_profile"] == "smoke"
        checked.append("report")
        return str(path / "report.pdf")

    def monitor(r, attempt, phase, args):
        config = json.loads((path / "viewer-config.json").read_text(encoding="utf-8"))
        assert config["source"]["data_profile"] == "smoke"
        assert config["source"]["test_only"] is False  # Native producer, environment-only dataset.
        write_json(path / "extracted/field-view.json", {"test_fixture": True})
        checked.append("viewer")

    def batch_report(batch, runs):
        assert runs[0]["quality"]["ml_eligible"] is False
        checked.append("batch_report")

    events = []
    monkeypatch.setattr(engine, "_monitor", monitor)
    monkeypatch.setattr("honeycomb_studio.engine.run_report", report)
    monkeypatch.setattr("honeycomb_studio.engine.batch_report", batch_report)
    monkeypatch.setattr(store, "event", lambda bid, rid, data: events.append(data))
    engine._postprocess(run, attempt, batch)
    assert checked == ["viewer", "report", "batch_report"]
    assert store.get("runs", run["id"])["status"] == "review"
    completed = next(e for e in events if e["type"] == "completed")
    assert completed["quality"]["ml_eligible"] is False
    assert completed["quality"]["physical_validation"] == "environment_smoke_only"
    store.db.close()
