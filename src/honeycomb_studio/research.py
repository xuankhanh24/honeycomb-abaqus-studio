"""Small, auditable research products; the ODB remains the source archive."""

import math

import numpy as np

FEATURES = [
    "clamp_mode",
    "core_topology",
    "hex_geometry",
    "hex_b",
    "hex_l",
    "hex_theta_deg",
    "reentrant_cell_height",
    "reentrant_indent",
    "phase_z",
    "panel",
    "skin",
    "bottom_skin",
    "core_height",
    "cell_size",
    "foil",
    "core_angle",
    "phase_x",
    "phase_y",
    "energy_J",
    "velocity_m_s",
    "mass_kg",
    "ball_diameter",
    "ball_radius",
    "impact_x",
    "impact_y",
    "gap",
    "gravity",
    "clamp_diameter",
    "friction",
    *[
        f"{material}.{key}"
        for material in ("face_material", "core_material")
        for key in (
            "density",
            "young",
            "poisson",
            "yield_stress",
            "hardening",
            "alpha",
            "exponent",
            "tangent_ratio",
        )
    ],
]
TARGETS = [
    "panel_mass_kg",
    "peak_raw_contact_force_N",
    "max_top_centre_downward_mm",
    "max_bottom_centre_downward_mm",
    "max_indentation_from_contact_mm",
    "physical_dissipation_J",
    "SEA_J_kg",
    "contact_duration_ms",
    "peak_force_time_ms",
    "max_displacement_time_ms",
    "end_impactor_velocity_m_s",
    "PEEQ_max",
    "mises_max_MPa",
    "maximum_energy_balance_drift_percent",
    "artificial_energy_over_max_internal_percent",
]
PROVENANCE = {
    "run_id",
    "batch_id",
    "design_id",
    "input_hash",
    "split",
    "physical_validation",
    "numerical_quality",
    "attempt_number",
    "extractor_version",
}


def field_reduction(arrays, meta):
    """Exact all-sample extrema and contact sums, without a permanent field copy."""
    data = arrays["data"]
    matrix = data.reshape((len(data), -1))
    valid = np.isfinite(matrix)

    def finite(values):
        return [float(x) if math.isfinite(x) else None for x in values]

    result = {
        **meta,
        "reduction": "all_sample_statistics_and_extrema",
        "rows": len(matrix),
        "statistics": {
            "rows": len(matrix),
            "finite_count": valid.sum(axis=0).tolist(),
            "min": finite(np.where(valid, matrix, np.inf).min(axis=0)),
            "max": finite(np.where(valid, matrix, -np.inf).max(axis=0)),
            "sum": finite(np.where(valid, matrix, 0.0).sum(axis=0)),
        },
    }
    field = meta["field"]
    if field in ("S", "U", "PEEQ"):
        values = (
            arrays["mises"]
            if field == "S"
            else np.linalg.norm(matrix, axis=1)
            if field == "U"
            else matrix[:, 0]
        )
        candidates = np.flatnonzero(np.isfinite(values))
        if len(candidates):
            value = np.max(values[candidates])
            index = int(np.flatnonzero(values == value)[-1])
            result["extremum_key"] = {
                "S": "mises_max_MPa",
                "U": "displacement_magnitude_max_mm",
                "PEEQ": "PEEQ_max",
            }[field]
            result["extremum"] = {
                "value": float(value),
                "step": meta["step"],
                "frame": meta["frame"],
                "time_s": meta["time_s"],
                "instance": meta["instances"][int(arrays["instance_index"][index])],
                **{
                    key: int(arrays[key][index])
                    for key in ("node_label", "element_label", "integration_point", "section_point")
                },
            }
    if field.startswith(("CNORMF", "CSHEARF")):
        index = next((i for i, name in enumerate(meta["instances"]) if "IMPACTOR" in name.upper()), None)
        if index is not None and matrix.shape[1] >= 3:
            result["impactor_force_z_N"] = float(matrix[arrays["instance_index"] == index, 2].sum())
    return result


def merge_statistics(target, field, stats, components):
    item = target.setdefault(
        field,
        {
            "components": components or ["value"],
            "count": [0] * len(stats["sum"]),
            "sum": [0.0] * len(stats["sum"]),
            "min": [None] * len(stats["sum"]),
            "max": [None] * len(stats["sum"]),
            "rows": 0,
        },
    )
    item["rows"] += stats["rows"]
    for i, count in enumerate(stats["finite_count"]):
        if count:
            item["count"][i] += count
            item["sum"][i] += stats["sum"][i]
            item["min"][i] = (
                stats["min"][i] if item["min"][i] is None else min(item["min"][i], stats["min"][i])
            )
            item["max"][i] = (
                stats["max"][i] if item["max"][i] is None else max(item["max"][i], stats["max"][i])
            )
