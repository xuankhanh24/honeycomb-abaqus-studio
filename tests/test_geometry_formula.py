import ast
import math
import textwrap
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from honeycomb_studio.adapters.hexagonal import network
from honeycomb_studio.api import make_app
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import Axis, BatchSpec, ModelSpec, expand
from honeycomb_studio.store import Store


def clip_for(panel):
    source = (Path(__file__).parents[1] / "src/honeycomb_studio/adapters/build.py").read_text()
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "clipped")
    env = {"P": {"panel": panel}, "math": math}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "adapter-clip", "exec"), env)
    return env["clipped"]


@pytest.mark.parametrize("angle,px,py", [(0, 0, 0), (27, 1, -2)])
def test_generalized_hex_matches_original_regular_network(angle, px, py):
    source = (Path(__file__).parents[1] / "src/honeycomb_studio/adapters/build.py").read_text()
    original = textwrap.dedent(source[source.index("    walls=set(); b=P['side']"):source.index("s=m.ConstrainedSketch(name='Reentrant")])
    b = 6.35/math.sqrt(3)
    clip = clip_for(100)
    env = dict(P={"panel": 100, "side": b, "cell_size": 6.35, "phase_x": px, "phase_y": py},
               math=math, clipped=clip, co=math.cos(math.radians(angle)), si=math.sin(math.radians(angle)))
    exec(original, env)
    assert network(100, b, b, 60, angle, px, py, clip) == env["walls"]


def test_custom_hex_tiles_without_interior_free_ends_and_matches_wall_density():
    b, length, theta = 4, 3, 50
    walls = network(100, b, length, theta, 0, 0, 0, clip_for(100))
    degree = Counter(p for wall in walls for p in wall)
    assert all(count == 3 for (x, y), count in degree.items() if max(abs(x), abs(y)) < 40)
    assert all(max(abs(x), abs(y)) <= 50 for (x, y) in degree)
    model = ModelSpec(hex_geometry="parametric", hex_b=b, hex_l=length, hex_theta_deg=theta)
    resolved = model.resolved()
    rad = math.radians(theta)
    # Polygon area of one complete cell, and shared wall volume (double vertical foil).
    half_width, rise = length*math.sin(rad), length*math.cos(rad)
    vertices = [(half_width,b/2), (0,b/2+rise), (-half_width,b/2),
                (-half_width,-b/2), (0,-b/2-rise), (half_width,-b/2)]
    area = abs(sum(x*vertices[(i+1)%6][1]-y*vertices[(i+1)%6][0] for i,(x,y) in enumerate(vertices)))/2
    expected = (2*b+2*length)*model.foil*model.core_material.density/area
    assert resolved["periodic_density_kg_m3"] == pytest.approx(expected)
    assert resolved["cell_size"] == pytest.approx(2*length*math.sin(rad))
    regular = ModelSpec().resolved()
    assert regular["periodic_density_kg_m3"] == pytest.approx(8*.0635*2700/(3*6.35))


def test_radius_velocity_propagate_to_solver_and_density_without_changing_mass():
    p = ModelSpec(loading="velocity", velocity_m_s=3, ball_size_mode="radius", ball_radius=8).resolved()
    assert p["energy_J"] == pytest.approx(.5*2.65*9)
    assert p["velocity"] == 3000
    assert p["ball_diameter"] == 16
    assert p["mass_kg"] == 2.65
    assert p["impactor_effective_density_tonne_mm3"] == pytest.approx(2.25e-6*(13.1/16)**3)
    assert ModelSpec(ball_diameter=20).resolved()["ball_radius"] == 10
    runs = expand(BatchSpec(model=ModelSpec(hex_geometry="parametric", loading="velocity", ball_size_mode="radius"), axes=[
        Axis(parameter="hex_b", values=[3,4]), Axis(parameter="velocity_m_s", values=[2,3]),
        Axis(parameter="ball_radius", values=[6,8]),
    ]))
    assert len(runs) == 8
    assert len({r["design_id"] for r in runs}) == 2
    assert {r["resolved"]["ball_diameter"] for r in runs} == {12,16}


@pytest.mark.parametrize("changes", [{"hex_theta_deg": 0}, {"hex_theta_deg": 90}, {"hex_b": 0}, {"hex_l": -1}, {"ball_radius": 0}])
def test_invalid_dimensions_rejected(changes):
    with pytest.raises(ValueError):
        ModelSpec(hex_geometry="parametric", **changes)


@pytest.mark.parametrize("model,key", [
    (ModelSpec(), "hex_b"), (ModelSpec(hex_geometry="parametric"), "cell_size"),
    (ModelSpec(core_topology="reentrant_0"), "hex_l"), (ModelSpec(), "ball_radius"),
    (ModelSpec(ball_size_mode="radius"), "ball_diameter"),
])
def test_inactive_axes_rejected(model, key):
    with pytest.raises(ValueError):
        expand(BatchSpec(model=model, axes=[Axis(parameter=key, values=[3])]))


def test_studio_template_preview_resolve_geometry_and_ball(tmp_path):
    store = Store(tmp_path)
    with TestClient(make_app(store, Engine(store, fake=True), "test", tmp_path/"config", start_worker=False)) as client:
        headers = {"X-Honeycomb-Token": "test"}
        spec = client.get("/v1/template", headers=headers).json()["spec"]
        spec["model"].update(hex_b=4, hex_l=3, hex_theta_deg=50, loading="velocity", velocity_m_s=3, ball_radius=8)
        resolved = client.post("/v1/resolve", headers=headers, json=spec["model"])
        assert resolved.status_code == 200
        assert resolved.json()["ball_diameter"] == 16
        response = client.post("/v1/preview", headers=headers, json=spec)
        assert response.status_code == 200
        row = response.json()["runs"][0]
        assert row["hex_b_mm"] == 4
        assert row["ball_radius_mm"] == 8
        assert row["energy_J"] == pytest.approx(11.925)
        assert not store.list("batches")  # Preview does not create a simulation.
