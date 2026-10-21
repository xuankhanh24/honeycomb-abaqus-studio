import math

import pytest
from pydantic import ValidationError

from honeycomb_studio.models import Axis, BatchSpec, Material, ModelSpec, expand


@pytest.mark.parametrize(
    "start,stop,step,include,expected",
    [
        (0, 1, 0.25, False, [0, 0.25, 0.5, 0.75, 1]),
        (0.85, 3, 1, False, [0.85, 1.85, 2.85]),
        (0.85, 3, 1, True, [0.85, 1.85, 2.85, 3]),
        (7, 7, 1, False, [7]),
    ],
)
def test_decimal_ranges(start, stop, step, include, expected):
    assert (
        Axis(parameter="energy_J", start=start, stop=stop, step=step, include_stop=include).points()
        == expected
    )


@pytest.mark.parametrize(
    "axis",
    [
        dict(start=0, stop=1, step=0),
        dict(start=2, stop=1, step=1),
        dict(values=[]),
        dict(start=0, stop=100000, step=0.001),
    ],
)
def test_invalid_ranges(axis):
    with pytest.raises(ValueError):
        Axis(parameter="energy_J", **axis).points()


def test_energy_velocity_units_and_mass():
    p = ModelSpec().resolved()
    assert p["impact_mass"] == 0.00265
    assert p["velocity"] == pytest.approx(2298.48186156)
    assert ModelSpec(loading="velocity", velocity_m_s=3, mass_kg=2).resolved()["energy_J"] == 9
    assert p["periodic_density_kg_m3"] == pytest.approx(72)


def test_grid_dedup_limit_and_immutable_base():
    b = BatchSpec(
        axes=[Axis(parameter="energy_J", values=[1, 1, 2]), Axis(parameter="skin", values=[0.5, 0.75])]
    )
    assert len(expand(b)) == 4
    assert b.model.energy_J == 7
    with pytest.raises(ValueError):
        expand(b.model_copy(update={"max_runs": 2}))


def test_no_dependent_loading_axes():
    with pytest.raises(ValueError):
        expand(
            BatchSpec(
                axes=[Axis(parameter="energy_J", values=[1]), Axis(parameter="velocity_m_s", values=[1])]
            )
        )
    with pytest.raises(ValueError):
        expand(BatchSpec(axes=[Axis(parameter="velocity_m_s", values=[1])]))


def test_lhs_reproducible_and_legal_geometry():
    b = BatchSpec(
        sampling="lhs",
        samples=8,
        axes=[
            Axis(parameter="core_height", start=15, stop=25),
            Axis(parameter="foil", start=0.05, stop=0.08),
        ],
    )
    assert expand(b) == expand(b)
    assert len(expand(b)) == 8
    assert all(15 < r["resolved"]["core_height"] < 25 for r in expand(b))


def test_same_design_group_across_load_and_numerical_settings():
    runs = expand(
        BatchSpec(
            axes=[Axis(parameter="energy_J", values=[1, 7]), Axis(parameter="shell_points", values=[5, 7])]
        )
    )
    assert len({r["design_id"] for r in runs}) == 1
    assert len({r["input_hash"] for r in runs}) == 4


def test_invalid_geometry_and_tables():
    with pytest.raises(ValidationError):
        ModelSpec(clamp_diameter=101)
    with pytest.raises(ValidationError):
        Material(hardening="table", plastic_table=[(100, 0.1)])
    with pytest.raises(ValidationError):
        Material(hardening="table", plastic_table=[(100, 0), (99, 0.1)])
    with pytest.raises(ValidationError):
        ModelSpec(energy_J=math.inf)
    table = Material().table()
    assert table[0] == [117, 0]
    assert all(b[0] > a[0] and b[1] > a[1] for a, b in zip(table, table[1:], strict=False))


def test_custom_mesh_required_for_seed_axis():
    with pytest.raises(ValueError):
        expand(BatchSpec(axes=[Axis(parameter="core_centre_seed", values=[0.5, 0.7])]))
    assert (
        len(
            expand(
                BatchSpec(
                    model=ModelSpec(mesh_preset="custom"),
                    axes=[Axis(parameter="core_centre_seed", values=[0.5, 0.7])],
                )
            )
        )
        == 2
    )


def test_categorical_material_axes_resolve_actual_plastic_tables():
    runs = expand(
        BatchSpec(axes=[Axis(parameter="face_material.hardening", values=["perfect_plastic", "bilinear"])])
    )
    assert len(runs) == 2
    assert len(runs[0]["resolved"]["face_plastic_table"]) == 1
    assert runs[1]["resolved"]["face_plastic_table"][-1][0] > runs[0]["resolved"]["face_plastic_table"][0][0]
