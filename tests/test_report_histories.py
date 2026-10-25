from pathlib import Path

from matplotlib.figure import Figure

from honeycomb_studio.data import dataset
from honeycomb_studio.history_sources import load_history
from honeycomb_studio.models import Axis, BatchSpec
from honeycomb_studio.reports import batch_report
from honeycomb_studio.store import Store, write_json


def test_batch_curves_use_retained_data_after_original_histories_are_removed(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec(axes=[Axis(parameter="energy_J", values=[1, 2])]))
    runs = store.list("runs", batch["id"])
    retained = tmp_path / "data-retained" / batch["id"] / "bk0000000000000000" / "training"
    for run in runs:
        run.update(
            status="completed",
            summary={"peak_raw_contact_force_N": 30, "max_top_centre_downward_mm": 2},
            attempts=[{"number": 1, "path": str(Path(run["path"]) / "attempts/001")}],
        )
        curve = retained / "curves" / run["id"] / "impact_history.csv"
        curve.parent.mkdir(parents=True)
        curve.write_text(
            "time_ms,contact_force_N,impactor_displacement_mm\n0,0,0\n1,30,2\n2,0,1\n", encoding="utf-8"
        )
    write_json(
        retained / "dataset.json",
        {
            "run_ids": [r["id"] for r in runs],
            "source_attempts": [{"run_id": r["id"], "attempt": 1} for r in runs],
        },
    )
    curves = []
    save = Figure.savefig

    def capture(figure, path, *args, **kwargs):
        if Path(path).name.startswith("curves-"):
            curves.append(sum(len(ax.lines) for ax in figure.axes))
        return save(figure, path, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture)
    batch_report(batch, runs)
    assert curves == [4], "Blank axes: both real histories must appear on both plots"


def test_wrong_attempt_is_not_used_and_missing_curves_do_not_create_empty_axes(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec())
    run = store.list("runs", batch["id"])[0]
    run.update(
        summary={"SEA_J_kg": 12}, attempts=[{"number": 2, "path": str(Path(run["path"]) / "attempts/002")}]
    )
    training = tmp_path / "data-retained" / batch["id"] / "bk0000000000000000" / "training"
    write_json(
        training / "dataset.json",
        {"run_ids": [run["id"]], "source_attempts": [{"run_id": run["id"], "attempt": 1}]},
    )
    curve = training / "curves" / run["id"] / "impact_history.csv"
    curve.parent.mkdir(parents=True)
    curve.write_text("time_ms,contact_force_N,impactor_displacement_mm\n1,300,2\n", encoding="utf-8")
    assert load_history(run) is None
    save = Figure.savefig
    curves = []

    def capture(figure, path, *args, **kwargs):
        if Path(path).name.startswith("curves-"):
            curves.append(path)
        return save(figure, path, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture)
    batch_report(batch, [run])
    assert curves == []


def test_dataset_keeps_original_curves_when_source_attempt_was_cleaned(tmp_path):
    store = Store(tmp_path / "data")
    batch = store.create(BatchSpec())
    run = store.list("runs", batch["id"])[0]
    run.update(
        status="completed",
        summary={"SEA_J_kg": 12},
        quality={"ml_eligible": True},
        attempts=[{"number": 1, "path": str(Path(run["path"]) / "attempts/001")}],
    )
    store.save("runs", run)
    training = tmp_path / "data-retained" / batch["id"] / "bk0000000000000000" / "training"
    write_json(
        training / "dataset.json",
        {"run_ids": [run["id"]], "source_attempts": [{"run_id": run["id"], "attempt": 1}]},
    )
    curve = training / "curves" / run["id"] / "impact_history.csv"
    curve.parent.mkdir(parents=True)
    curve.write_text("time_ms,contact_force_N,impactor_displacement_mm\n1,300,2\n", encoding="utf-8")
    result = dataset(store, [run["id"]], "Retained source")
    assert (Path(result["path"]) / "curves" / run["id"] / curve.name).read_bytes() == curve.read_bytes()
