"""Regression cases from the 26 October project review; no native solver is used."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from honeycomb_studio.api import make_app
from honeycomb_studio.cloud_api import create_app
from honeycomb_studio.contracts import QualityReport
from honeycomb_studio.data import dataset, history_summary, quality
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec, ModelSpec, expand
from honeycomb_studio.store import Store, write_json


@pytest.mark.parametrize("model,changes", [
    ({"loading": "velocity"}, {"energy_J": 5}),
    ({}, {"velocity_m_s": 3}),
    ({"core_topology": "reentrant_0", "reentrant_geometry": "angle"}, {"reentrant_indent": 1}),
    ({"core_topology": "reentrant_0"}, {"reentrant_delta_deg": 20}),
    ({}, {"hex_b": 4}),
    ({"hex_geometry": "parametric"}, {"cell_size": 7}),
    ({"core_topology": "reentrant_0"}, {"hex_l": 4}),
    ({}, {"reentrant_indent": 1}),
    ({}, {"ball_radius": 8}),
    ({"ball_size_mode": "radius"}, {"ball_diameter": 16}),
    ({"clamp_mode": "perimeter"}, {"clamp_diameter": 70}),
    ({}, {"core_centre_seed": .5}),
    ({"core_topology": "reentrant_0"}, {"reentrant_depth_seed": .5}),
])
def test_table_rejects_inactive_overrides_with_row_number(model, changes):
    spec = BatchSpec(model=ModelSpec(**model), sampling="table", designs=[{}, changes])
    with pytest.raises(ValueError, match="Dòng bảng 2:"):
        expand(spec)


def test_table_uses_each_rows_modes_and_preserves_requested_physics():
    spec = BatchSpec(sampling="table", designs=[
        {"energy_J": 5},
        {"loading": "velocity", "velocity_m_s": 3},
        {"core_topology": "reentrant_0", "reentrant_geometry": "angle", "reentrant_delta_deg": 20},
        {"hex_geometry": "parametric", "hex_b": 4},
        {"ball_size_mode": "radius", "ball_radius": 8},
        {"mesh_preset": "custom", "core_centre_seed": .5},
    ])
    before = spec.model_dump()
    runs = expand(spec)
    assert len(runs) == 6
    assert runs[0]["resolved"]["energy_J"] == 5
    assert runs[1]["resolved"]["energy_J"] == pytest.approx(.5 * 2.65 * 3**2)
    assert runs[2]["resolved"]["reentrant_delta_deg"] == pytest.approx(20)
    assert runs[3]["resolved"]["hex_b"] == 4
    assert runs[4]["resolved"]["ball_diameter"] == 16
    assert runs[5]["resolved"]["core_centre_seed"] == .5
    assert spec.model_dump() == before
    duplicates = BatchSpec(sampling="table", designs=[{"energy_J": e} for e in (5, 5, 7, 9)])
    assert [r["resolved"]["energy_J"] for r in expand(duplicates)] == [5, 7, 9]


def test_invalid_table_fails_preview_and_creation_before_persisting(tmp_path):
    spec = BatchSpec(model=ModelSpec(loading="velocity", cpus=4), sampling="table",
                     designs=[{}, {"energy_J": 5}]).model_dump()
    with TestClient(create_app()) as cloud:
        response = cloud.post("/api/preview", json=spec)
        assert response.status_code == 422
        assert "Dòng bảng 2:" in response.json()["detail"]
    store = Store(tmp_path / "library")
    try:
        with TestClient(make_app(store, Engine(store, fake=True), "test", tmp_path / "config",
                                 start_worker=False)) as local:
            for endpoint in ("/v1/preview", "/v1/batches"):
                response = local.post(endpoint, headers={"X-Honeycomb-Token": "test"}, json=spec)
                assert response.status_code == 400
                assert "Dòng bảng 2:" in response.json()["detail"]
            assert not store.list("batches") and not store.list("runs")
            assert not (store.root / "projects").exists()
    finally:
        store.db.close()


@pytest.mark.parametrize("key", [
    "maximum_energy_balance_drift_percent",
    "artificial_energy_over_max_internal_percent",
    "contact_force_check_max_relative_percent",
    "end_contact_force_N",
])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf")])
def test_missing_or_nonfinite_required_check_is_never_ml_eligible(key, invalid):
    summary = {"solver_completed": True, "initial_kinetic_energy_J": 7, "end_contact_force_N": 0,
               "maximum_energy_balance_drift_percent": .08,
               "artificial_energy_over_max_internal_percent": 4.52,
               "contact_force_check_max_relative_percent": .1}
    summary[key] = invalid
    result = quality(summary)
    assert result["numerical_quality"] == "review" and result["ml_eligible"] is False
    assert any(key in finding for finding in result["findings"])
    del summary[key]
    assert quality(summary)["ml_eligible"] is False


def test_missing_force_field_is_detected_after_extraction_and_excluded_from_dataset(tmp_path):
    # Synthetic histories test the extraction/quality/dataset boundary, not physics.
    extracted = tmp_path / "extracted"
    times = [0, .003, .006]
    series = []
    values = {"A3": [-9810, 400000, -9810], "V3": [-2298.48, 0, 1000], "U3": [0, -3, -2],
              "ALLKE": [7000, 1000, 1000], "ALLIE": [0, 6000, 6000], "ALLAE": [0, 20, 20],
              "ALLPD": [0, 5000, 5000], "ALLSE": [0, 980, 980], "ALLVD": [0, 0, 0],
              "ALLWK": [0, 0, 0], "ETOTAL": [7000, 7000, 7000]}
    for variable, data in values.items():
        series.append({"step": "Impact", "region": "IMPACTOR" if variable in ("A3", "V3", "U3") else "Assembly",
                       "variable": variable, "description": variable, "data": list(zip(times, data, strict=True))})
    write_json(extracted / "histories.json", series)
    write_json(extracted / "inventory.json", {"frames": 3, "fields": []})
    model = ModelSpec(field_variables=["U", "S", "PEEQ"])
    summary, _ = history_summary(extracted, model.resolved())
    assert summary["contact_force_check_max_relative_percent"] is None
    result = quality(summary)
    assert result["numerical_quality"] == "review" and result["ml_eligible"] is False
    store = Store(tmp_path / "library")
    try:
        batch = store.create(BatchSpec(model=model))
        run = store.list("runs", batch["id"])[0]
        # Even a legacy completed status must not override the quality gate.
        run.update(status="completed", summary=summary, quality=result)
        store.save("runs", run)
        with pytest.raises(ValueError, match="Không có lượt đủ chất lượng"):
            dataset(store, [run["id"]], "Missing force verification")
    finally:
        store.db.close()


def test_published_quality_schema_accepts_environment_smoke():
    schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/QualityReport.schema.json")
                        .read_text(encoding="utf-8"))
    assert "environment_smoke_only" in schema["properties"]["physical_validation"]["enum"]
    assert schema == QualityReport.model_json_schema()
