import csv
import json

import pyarrow.parquet as pq
import pytest

from honeycomb_studio.models import Axis, BatchSpec, ModelSpec
from honeycomb_studio.store import Store
from honeycomb_studio.training_collection import build_collection


def export(tmp_path, spec):
    store = Store(tmp_path / "store")
    batch = store.create(spec)
    runs = store.list("runs", batch["id"])
    for run in runs:
        run.update(status="completed", quality={"ml_eligible": True}, summary={"SEA_J_kg": 50})
    out = tmp_path / "collection"
    build_collection([{"job_id": "fixture", "runs": runs}], out)
    training = out / "01_training"
    rows = pq.read_table(training / "samples.parquet").to_pylist()
    meta = json.loads((training / "dataset.json").read_text())
    return training, rows, meta


def test_angle_range_is_exported_directly_with_units_and_metadata(tmp_path):
    spec = BatchSpec(model=ModelSpec(core_topology="reentrant_0", reentrant_geometry="angle"),
                     axes=[Axis(parameter="reentrant_delta_deg", start=25, stop=45, step=1)])
    training, rows, meta = export(tmp_path, spec)
    assert sorted(r["input.reentrant_delta_deg"] for r in rows) == pytest.approx(list(range(25, 46)))
    assert "input.reentrant_delta_deg" in meta["features"]
    assert "input.reentrant_delta_deg" in meta["varying_features"]
    csv_rows = list(csv.DictReader((training / "samples.csv").open(encoding="utf-8-sig")))
    assert sorted(float(r["input.reentrant_delta_deg"]) for r in csv_rows) == pytest.approx(list(range(25, 46)))
    dictionary = json.loads((training / "data-dictionary.json").read_text(encoding="utf-8-sig"))
    assert "reentrant_delta_deg" in json.dumps(dictionary)


@pytest.mark.parametrize("parameter,values", [("duration", [0.006, 0.012]), ("cpus", [1, 2]),
                                            ("history_intervals", [1200, 2400])])
def test_other_swept_parameters_are_not_silently_dropped(tmp_path, parameter, values):
    _, rows, meta = export(tmp_path, BatchSpec(axes=[Axis(parameter=parameter, values=values)]))
    key = "input." + parameter
    assert sorted(r[key] for r in rows) == values
    assert key in meta["varying_features"]


def test_indent_mode_exports_effective_angle_not_inactive_angle_setting(tmp_path):
    _, rows, _ = export(tmp_path, BatchSpec(
        model=ModelSpec(core_topology="reentrant_0", reentrant_geometry="indent", reentrant_delta_deg=30),
        axes=[Axis(parameter="reentrant_indent", values=[1.25, 2.5])]))
    angles = {r["input.reentrant_indent"]: r["input.reentrant_delta_deg"] for r in rows}
    assert angles[1.25] == pytest.approx(26.565051177)
    assert angles[2.5] == pytest.approx(45)
