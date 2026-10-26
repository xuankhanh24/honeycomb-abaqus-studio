"""Transparent estimates: geometric cold start, then comparable measured runs."""

import json
import math
from statistics import median
from typing import Any


def records(store):
    result = []
    for run in store.list("runs"):
        if run.get("test_only"):
            continue
        for attempt in run.get("attempts", []):
            durations = attempt.get("durations", {})
            if durations.get("solving", 0) > 1:
                result.append({"model": run["resolved"], "durations": durations})
    file = store.root / "calibration.json"
    if file.exists():
        try:
            known = json.loads(file.read_text(encoding="utf-8"))["records"]
            required = {
                "panel",
                "core_height",
                "skin",
                "cell_size",
                "foil",
                "core_centre_seed",
                "core_outer_seed",
                "skin_centre_seed",
                "skin_outer_seed",
                "core_z_divisions",
                "cpus",
                "duration",
            }
            result.extend(
                r
                for r in known
                if required <= r.get("model", {}).keys() and r.get("durations", {}).get("solving", 0) > 1
            )
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return result


def mesh_work(p):
    core = (
        (p["panel"] / 100) ** 2
        * (6.35 / p["cell_size"])
        * (p["core_z_divisions"] / 20)
        * (1.3 / p["core_outer_seed"])
    )
    reentrant = p.get("core_topology", "hexagonal") == "reentrant_0"
    if reentrant:
        core = (
            (105000 / 59160) * (p["panel"] / 100) ** 2 * (p["core_height"] / 20)
            * (6.35 / p["cell_size"]) * (5 / p["reentrant_cell_height"])
            * (1 / p["reentrant_depth_seed"]) * (1.3 / p["core_outer_seed"])
        )
    face = (p["panel"] / 100) ** 2 * (1.25 / p["skin_outer_seed"]) ** 2
    complexity = 0.75 * core + 0.25 * face
    stable = min(
        p["core_centre_seed"] / 0.7, p["skin_centre_seed"] / 0.75,
        p["reentrant_depth_seed"] if reentrant else p["core_height"] / p["core_z_divisions"]
    )
    return complexity, complexity / max(stable, 0.05)


def predict(model, calibration=()) -> dict[str, Any]:
    p = model
    complexity, work = mesh_work(p)
    cold = 25 * work * (p["duration"] / 0.006) * 8 / p["cpus"]
    weighted = []
    keys = (
        "panel",
        "core_height",
        "skin",
        "cell_size",
        "foil",
        "core_centre_seed",
        "core_outer_seed",
        "skin_centre_seed",
        "skin_outer_seed",
        "core_z_divisions",
    )
    for record in calibration:
        old = record["model"]
        if old.get("core_topology", "hexagonal") != p.get("core_topology", "hexagonal"):
            continue
        if p.get("core_topology") == "reentrant_0" and any(
            key not in old for key in ("reentrant_cell_height", "reentrant_indent", "reentrant_depth_seed")
        ):
            continue
        distance = sum(abs(math.log(p[k] / old[k])) for k in keys)
        if p.get("core_topology") == "reentrant_0":
            distance += sum(abs(math.log(p[k] / old[k])) for k in
                            ("reentrant_cell_height", "reentrant_indent", "reentrant_depth_seed"))
        if distance < 1.5:
            prediction = (
                record["durations"]["solving"]
                / 60
                * p["duration"]
                / old["duration"]
                * old["cpus"]
                / p["cpus"]
                * work
                / mesh_work(old)[1]
            )
            weighted.append((distance, prediction))
    closest = sorted(weighted)[:3]
    value = (
        sum(v / (d + 0.1) for d, v in closest) / sum(1 / (d + 0.1) for d, v in closest) if closest else cold
    )
    phases = {
        key: median([r["durations"][key] for r in calibration if key in r["durations"]]) / 60
        if any(key in r["durations"] for r in calibration)
        else fallback
        for key, fallback in (("building", 1.0), ("extracting", 10.0), ("rendering", 2.0), ("reporting", 0.5))
    }
    raw = 2.673 * complexity * p["field_intervals"] / 120 * len(p["field_variables"]) / 10
    return {
        "solver_minutes": value,
        "solver_range_minutes": [value * 0.65, value * 1.6],
        "range_is": "heuristic, not confidence interval",
        "method": "nearest measured comparable runs"
        if closest
        else "cold reference + mesh complexity heuristic",
        "calibration_runs": len(closest),
        "other_phase_minutes": phases,
        "raw_odb_gb": raw,
        "recommended_free_gb_above_reserve": max(8, raw * 3.5),
    }
