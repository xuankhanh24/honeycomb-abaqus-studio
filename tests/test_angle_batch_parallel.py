import math
import threading

import pytest
from fastapi.testclient import TestClient

from honeycomb_studio.cloud_api import create_app
from honeycomb_studio.engine import Engine
from honeycomb_studio.execution import execution_plan
from honeycomb_studio.models import Axis, BatchSpec, ModelSpec, expand
from honeycomb_studio.store import Store


def test_delta_resolves_actual_geometry_density_and_keeps_legacy_input():
    old = ModelSpec(core_topology="reentrant_0").resolved()
    new = ModelSpec(core_topology="reentrant_0", reentrant_geometry="angle").resolved()
    assert new["reentrant_indent"] == pytest.approx(1.25)
    assert new["periodic_density_kg_m3"] == pytest.approx(old["periodic_density_kg_m3"])
    altered = ModelSpec(core_topology="reentrant_0", reentrant_geometry="angle", reentrant_delta_deg=40).resolved()
    assert altered["reentrant_indent"] == pytest.approx(2.5 * math.tan(math.radians(40)))
    assert altered["periodic_density_kg_m3"] != pytest.approx(old["periodic_density_kg_m3"])
    assert new["duration"] == old["duration"] == .006


@pytest.mark.parametrize("delta", [0, 60, 90])
def test_delta_rejects_degenerate_closed_or_out_of_range_cell(delta):
    with pytest.raises(ValueError):
        ModelSpec(core_topology="reentrant_0", reentrant_geometry="angle", reentrant_delta_deg=delta)


def test_multi_axis_grid_and_preview_use_resolved_delta():
    model = ModelSpec(core_topology="reentrant_0", reentrant_geometry="angle", cpus=2)
    spec = BatchSpec(model=model, execution_mode="parallel", max_parallel_runs=2,
                     axes=[Axis(parameter="reentrant_delta_deg", start=20, stop=30, step=5),
                           Axis(parameter="energy_J", start=5, stop=7, step=2)])
    runs = expand(spec)
    assert len(runs) == 6 and len({r["input_hash"] for r in runs}) == 6
    assert sorted({round(r["resolved"]["reentrant_delta_deg"], 8) for r in runs}) == [20, 25, 30]
    with TestClient(create_app()) as client:
        response = client.post("/api/preview", json=spec.model_dump())
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 6 and data["execution"]["effective_parallel_runs"] == 2
        geometry = client.post("/api/geometry", json=model.model_dump()).json()
        assert geometry["reentrant_indent_mm"] == pytest.approx(1.25)
        assert geometry["delta_deg"] == pytest.approx(26.565051177)
    with pytest.raises(ValueError, match="độ lõm/góc"):
        expand(spec.model_copy(update={"axes": [Axis(parameter="reentrant_indent", values=[1, 2])]}))


def test_admission_never_oversubscribes_or_changes_requested_cpus():
    model = ModelSpec(cpus=4).resolved()
    spec = BatchSpec(execution_mode="parallel", max_parallel_runs=2).model_dump()
    assert execution_plan(spec, [model, model], 4, 16, 100)["effective_parallel_runs"] == 1
    assert model["cpus"] == 4
    assert execution_plan(spec, [model, model], 8, 16, 100)["effective_parallel_runs"] == 2
    assert execution_plan(spec, [model], 8, 3, 100)["effective_parallel_runs"] == 0
    assert execution_plan(spec, [model], 8, 16, 21)["effective_parallel_runs"] == 0
    varying = [ModelSpec(cpus=n).resolved() for n in (1, 1, 8)]
    assert execution_plan(spec, varying, 4, 16, 100)["effective_parallel_runs"] == 2
    assert execution_plan(spec, varying[2:], 4, 16, 100)["effective_parallel_runs"] == 0


def test_parallel_wave_reaches_two_independent_tasks_before_either_finishes(tmp_path, monkeypatch):
    store = Store(tmp_path)
    batch = store.create(BatchSpec(model=ModelSpec(cpus=2), execution_mode="parallel", max_parallel_runs=2,
                                   axes=[Axis(parameter="energy_J", values=[5, 7])]))
    engine = Engine(store, fake=True)
    barrier = threading.Barrier(2)
    entered = []

    def observed(run, batch):
        entered.append(run["id"])
        barrier.wait(timeout=3)
        run.update(status="completed", test_only=True)
        store.save("runs", run)

    monkeypatch.setattr(engine, "_execute", observed)
    result = engine.execute_wave(store.list("runs", batch["id"]), batch)
    assert len(entered) == len(result) == 2
    assert len(set(entered)) == 2 and engine.current_runs == set()
    assert all(r["resolved"]["cpus"] == 2 and r["test_only"] for r in result)
    store.db.close()


def test_live_process_adoption_ignores_budget_for_new_launches(tmp_path, monkeypatch):
    store = Store(tmp_path)
    batch = store.create(BatchSpec())
    run = store.list("runs", batch["id"])[0]
    run.update(status="recovering", attempts=[{"number": 1, "process": {"pid": 1}}])
    store.save("runs", run)
    engine = Engine(store)
    monkeypatch.setattr("honeycomb_studio.engine.solver.owned_tree_alive", lambda record: bool(record))

    def no_new_admission():
        raise AssertionError("Owned processes must be adopted even if no free launch RAM remains")

    monkeypatch.setattr("honeycomb_studio.engine.psutil.virtual_memory", no_new_admission)
    called = []
    monkeypatch.setattr(engine, "_execute", lambda run, batch: called.append(run["id"]))
    engine.execute_wave([run], batch)
    assert called == [run["id"]]
    store.db.close()


def test_shutdown_does_not_start_reserved_tasks_and_preserves_live_process(tmp_path, monkeypatch):
    store = Store(tmp_path)
    batch = store.create(BatchSpec())
    run = store.list("runs", batch["id"])[0]
    engine = Engine(store, fake=True)
    engine.shutdown.set()
    result = engine.execute_wave([run], batch)
    assert result[0]["status"] == "interrupted" and not result[0]["attempts"]
    process = {"pid": 1}
    run.update(status="recovering", attempts=[{"number": 1, "process": process,
               "path": str(tmp_path / "attempt"), "process_phase": "solving"}])
    store.save("runs", run)
    monkeypatch.setattr("honeycomb_studio.engine.solver.owned_tree_alive", lambda record: bool(record))
    monkeypatch.setattr("honeycomb_studio.engine.solver.terminate_owned",
                        lambda *_: pytest.fail("Shutdown must not kill the detached native process"))
    engine._execute(run, batch)
    assert store.get("runs", run["id"])["attempts"][0]["process"] == process
    store.db.close()
