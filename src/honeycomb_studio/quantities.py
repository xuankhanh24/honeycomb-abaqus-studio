"""Portable column meanings and units for research datasets."""

from functools import cache

from .models import catalogue


@cache
def input_descriptors():
    return {item["key"]: item for item in catalogue()}


DERIVED_UNITS = {
    "impact_mass": "tonne",
    "velocity": "mm/s",
    "periodic_density_kg_m3": "kg/m³",
    "impactor_effective_density_tonne_mm3": "tonne/mm³",
}
MEANINGS = {
    "initial_kinetic_energy_J": "ALLKE at first history sample / 1000",
    "peak_raw_contact_force_N": "max m_tonne*(A3+g_mm_s2), guided rigid impactor; no smoothing",
    "peak_force_time_ms": "Time at maximum raw contact force",
    "max_impactor_displacement_mm": "max(-RP.U3) from step start; includes initial gap travel",
    "max_indentation_from_contact_mm": "Impactor travel relative to first contact force above 10 N",
    "max_top_centre_downward_mm": "max(-U3) of top node nearest impact location selected at build",
    "max_bottom_centre_downward_mm": "max(-U3) of bottom node nearest impact location selected at build",
    "contact_duration_ms": "Last minus first history time with contact force >10 N",
    "plastic_dissipation_J": "ALLPD at last history sample /1000",
    "physical_dissipation_J": "ALLPD plus recorded ALLFD/ALLDMD/ALLCD at last sample; excludes artificial and numerical viscosity energy",
    "transferred_energy_at_last_contact_J": "Initial impactor kinetic energy minus kinetic energy at last contact, plus gravity work on impactor",
    "panel_mass_kg": "Finite sandwich mass: two faces and honeycomb, excludes impactor",
    "SEA_J_kg": "Physical dissipation / finite sandwich mass",
    "maximum_energy_balance_drift_percent": "100*max(abs(ETOTAL-ETOTAL[0]))/initial ALLKE",
    "artificial_energy_over_max_internal_percent": "100*max(abs(ALLAE))/max(ALLIE)",
    "contact_force_check_max_relative_percent": "Maximum contact resultant versus m(A3+g) difference normalized by peak contact force",
    "PEEQ_max": "Largest recorded PEEQ across frames, instances, integration and shell section points; location retained in source summary",
    "mises_max_MPa": "Largest ODB von Mises invariant across recorded frames and section points; location retained in source summary",
    "displacement_magnitude_max_mm": "Largest recorded displacement magnitude across all instances, including impactor",
}
PROVENANCE = {
    "run_id",
    "batch_id",
    "design_id",
    "input_hash",
    "split",
    "schema_version",
    "validation_status",
    "numerical_quality",
    "physical_validation",
    "attempt_number",
    "extractor_version",
    "solver_completed",
    "frames",
    "force_method",
}


def describe_column(key: str) -> dict:
    input_key = key.removeprefix("input.")
    input_meta = input_descriptors().get(input_key, {}) if key.startswith("input.") else {}
    unit = input_meta.get("unit", DERIVED_UNITS.get(input_key, ""))
    if not unit:
        for suffix, value in (
            ("_mm_s", "mm/s"),
            ("_kg_m3", "kg/m³"),
            ("_J_kg", "J/kg"),
            ("_MPa", "MPa"),
            ("_percent", "%"),
            ("_mm", "mm"),
            ("_ms", "ms"),
            ("_kg", "kg"),
            ("_N", "N"),
            ("_J", "J"),
            ("_s", "s"),
        ):
            if key.endswith(suffix):
                unit = value
                break
    return {
        "role": "input" if key.startswith("input.") else "provenance" if key in PROVENANCE else "target",
        "title": input_meta.get("title", key),
        "unit": unit or "dimensionless / category / provenance",
        "definition": input_meta.get("description") or MEANINGS.get(key, key.replace("_", " ")),
        "source": input_meta.get(
            "source", "Resolved model / ODB histories or fields; input hash and attempt identify source"
        ),
        "missing": "null; never imputed",
    }
