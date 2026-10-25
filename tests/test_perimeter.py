import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from honeycomb_studio.api import make_app
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import Axis, BatchSpec, ModelSpec, expand
from honeycomb_studio.store import Store


def test_adapter_selects_edges_only_and_keeps_legacy_circle():
    source = (Path(__file__).parents[1] / "src/honeycomb_studio/adapters/build.py").read_text()
    selection = source[source.index("if CLAMP_MODE=='perimeter':\n    labels="):source.index("skin.Set(name=CLAMP_SET")]
    nodes = [SimpleNamespace(label=i, coordinates=xy) for i, xy in enumerate([
        (50, 0), (-50, 20), (3, 50), (25, -50), (50, 50),
        (49, 49), (40, 0), (0, 0), (0, 38), (0, 38.3),
    ])]
    env = dict(skin=SimpleNamespace(nodes=nodes), P={"panel": 100, "clamp_diameter": 76.4}, math=math)
    exec(selection, dict(env, CLAMP_MODE="perimeter"), result := {})
    assert result["labels"] == [0, 1, 2, 3, 4]
    exec(selection, dict(env, CLAMP_MODE="circular"), result := {})
    assert result["labels"] == [0, 1, 2, 3, 4, 5, 6, 9]


def test_perimeter_validation_and_distinct_design():
    model = ModelSpec(clamp_mode="perimeter", clamp_diameter=200, impact_x=30)
    assert model.resolved()["clamp_mode"] == "perimeter"
    with pytest.raises(ValueError):
        ModelSpec(clamp_mode="perimeter", impact_x=39)
    with pytest.raises(ValueError, match="đường kính"):
        expand(BatchSpec(model=model, axes=[Axis(parameter="clamp_diameter", values=[70, 80])]))
    runs = expand(BatchSpec(sampling="table", designs=[{}, {"clamp_mode": "perimeter"}]))
    assert runs[0]["design_id"] != runs[1]["design_id"]
    assert ModelSpec().clamp_mode == "circular"  # Saved pre-existing jobs retain their boundary.


def test_fresh_studio_template_uses_perimeter(tmp_path):
    store = Store(tmp_path)
    with TestClient(make_app(store, Engine(store, fake=True), "test-token", tmp_path / "config", start_worker=False)) as client:
        response = client.get("/v1/template", headers={"X-Honeycomb-Token": "test-token"})
        assert response.status_code == 200
        assert response.json()["spec"]["model"]["clamp_mode"] == "perimeter"
