import json
import zipfile

import numpy as np
import pyarrow.parquet as pq
import pytest

from honeycomb_studio.backup import DriveBackup
from honeycomb_studio.data import archive, consume_spool, dataset, manifest, quality, verify_export
from honeycomb_studio.models import Axis, BatchSpec
from honeycomb_studio.store import Store, write_json


def test_chunk_roundtrip_preserves_section_and_vector(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    np.savez(
        spool / "00000000.npz",
        data=np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        section_point=np.array([1, 5]),
        element_label=np.array([99, 99]),
        integration_point=np.array([1, 1]),
    )
    write_json(
        spool / "00000000.ready",
        {
            "npz": "00000000.npz",
            "sequence": 0,
            "kind": "field",
            "step": "Impact",
            "field": "S",
            "frame": 1,
            "time_s": 0.001,
            "components": ["S11", "S22", "S12"],
        },
    )
    assert consume_spool(tmp_path) == 1
    path = next((tmp_path / "fields").rglob("*.parquet"))
    pf = pq.ParquetFile(path)
    rows = pf.read().to_pylist()
    pf.close()
    assert rows[1]["data"] == [4, 5, 6]
    assert [r["section_point"] for r in rows] == [1, 5]
    write_json(
        tmp_path / "inventory.json", {"fields": [{"step": "Impact", "frame": 1, "field": "S", "rows": 2}]}
    )
    assert verify_export(tmp_path)["passed"]
    write_json(
        tmp_path / "inventory.json", {"fields": [{"step": "Impact", "frame": 1, "field": "S", "rows": 3}]}
    )
    with pytest.raises(ValueError):
        verify_export(tmp_path)


def test_quality_is_separate_from_physical_validation():
    summary = {
        "solver_completed": True,
        "initial_kinetic_energy_J": 7,
        "maximum_energy_balance_drift_percent": 0.08,
        "artificial_energy_over_max_internal_percent": 4.52,
    }
    result = quality(summary)
    assert result["ml_eligible"] and result["physical_validation"] == "not_established"
    assert not quality({**summary, "artificial_energy_over_max_internal_percent": 6})["ml_eligible"]
    assert not quality({**summary, "end_contact_force_N": 100})["ml_eligible"]


def test_dataset_groups_design_and_excludes_failed_duplicate(tmp_path):
    store = Store(tmp_path)
    b = store.create(
        BatchSpec(
            axes=[Axis(parameter="energy_J", values=[1, 2, 3]), Axis(parameter="skin", values=[0.5, 0.75, 1])]
        )
    )
    runs = store.list("runs", b["id"])
    for r in runs:
        r.update(
            status="completed",
            summary={"peak_raw_contact_force_N": 1000, "SEA_J_kg": 12},
            quality={"ml_eligible": True},
        )
        store.save("runs", r)
    runs[-1].update(status="failed")
    store.save("runs", runs[-1])
    out = dataset(
        store,
        [r["id"] for r in runs] + [runs[0]["id"]],
        "Test",
        42,
        features=["input.skin"],
        targets=["SEA_J_kg"],
    )
    rows = pq.read_table(out["path"] + "/samples.parquet").to_pylist()
    assert len(rows) == 8
    dictionary = json.loads(
        (__import__("pathlib").Path(out["path"]) / "data-dictionary.json").read_text(encoding="utf-8")
    )
    assert dictionary["input.skin"]["unit"] == "mm"
    assert dictionary["SEA_J_kg"]["unit"] == "J/kg"
    import csv
    from pathlib import Path

    description_rows = list(
        csv.DictReader((Path(out["path"]) / "data-dictionary.csv").open(encoding="utf-8-sig"))
    )
    assert [r["Tên trường"] for r in description_rows] == list(rows[0])
    assert "Chiều dày" in dictionary["input.skin"]["definition"]
    assert "physical_dissipation_J/panel_mass_kg" in dictionary["SEA_J_kg"]["definition"]
    assert (Path(out["path"]) / "FIELD_DESCRIPTIONS.md").exists()
    assert "input.energy_J" not in rows[0]
    assert all(
        len({r["split"] for r in rows if r["design_id"] == g}) == 1 for g in {r["design_id"] for r in rows}
    )


def test_default_training_columns_have_descriptions_and_correct_velocity_unit():
    from honeycomb_studio.quantities import describe_column
    from honeycomb_studio.research import FEATURES, PROVENANCE, TARGETS

    for key in [*("input." + k for k in FEATURES), *PROVENANCE, *TARGETS]:
        item = describe_column(key)
        assert item["title"] != key
        assert item["definition"] != key.replace("_", " ")
    assert describe_column("end_impactor_velocity_m_s")["unit"] == "m/s"
    assert "chỉ dùng với bilinear" in describe_column("input.core_material.tangent_ratio")["definition"]


def test_archive_and_verified_restore(tmp_path):
    store = Store(tmp_path / "data")
    b = store.create(BatchSpec())
    r = store.list("runs", b["id"])[0]
    attempt = __import__("pathlib").Path(r["path"]) / "attempts/001"
    (attempt / "raw").mkdir(parents=True)
    (attempt / "raw/a.inp").write_text("*Heading\n")
    r.update(
        status="completed",
        attempts=[{"number": 1, "path": str(attempt), "job_name": "a"}],
        summary={},
        quality={},
    )
    store.save("runs", r)
    archive_path = tmp_path / "job.zip"
    archive(__import__("pathlib").Path(b["path"]), archive_path)
    backup = DriveBackup(store, tmp_path / "config")
    restored = backup.restore_local(archive_path)
    assert restored["verified"]
    assert restored["batch_id"] != b["id"]
    assert store.list("runs", restored["batch_id"])[0]["status"] == "completed"


def test_restore_rejects_zip_slip(tmp_path):
    store = Store(tmp_path / "data")
    backup = DriveBackup(store, tmp_path / "config")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError):
        backup.restore_local(bad)


def test_nested_manifest_is_checksums_included(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/artifact-manifest.json").write_text("{}")
    m = manifest(tmp_path)
    assert m["files"][0]["path"] == "nested/artifact-manifest.json"


def test_archive_never_certifies_a_file_changed_after_snapshot(tmp_path, monkeypatch):
    import honeycomb_studio.data as data

    root = tmp_path / "source"
    root.mkdir()
    file = root / "value.csv"
    file.write_text("original")
    original = data.manifest

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        file.write_text("changed")
        return result

    monkeypatch.setattr(data, "manifest", mutate)
    with pytest.raises(ValueError, match="File thay đổi"):
        archive(root, tmp_path / "result.zip")
