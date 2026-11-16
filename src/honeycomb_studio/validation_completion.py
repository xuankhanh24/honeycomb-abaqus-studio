"""Completion of a frozen FEA verification is independent of an intact-bottom outcome."""

import math

from .models import BatchSpec, digest, expand


def verification_completion(parent):
    context = parent.get("validation_context") or {}
    if context.get("kind") != "locked-surrogate-fea-verification-v1":
        raise ValueError("Not a locked surrogate verification job")
    if digest(parent["spec"]) != parent["input_hash"]:
        raise ValueError("Frozen verification input changed")
    designs = expand(BatchSpec.model_validate(parent["spec"]))
    expected = len(designs)
    names = context["candidate_ids"]
    shards = parent.get("shards", [])
    if (
        len(names) != expected
        or len(set(names)) != expected
        or len(shards) != expected
        or {s["index"] for s in shards} != set(range(expected))
    ):
        raise ValueError("Verification matrix is incomplete")
    if any(d["resolved"]["duration"] != context["simulation_duration_s"] for d in designs):
        raise ValueError("Verification duration differs from frozen inputs")
    complete, intact, deleted, missing = [], [], [], []
    for shard in shards:
        name = names[shard["index"]]
        runs = shard.get("runs", [])
        run = runs[0] if len(runs) == 1 else {}
        summary = run.get("summary") or {}
        horizon = run.get("research_horizon") or {}
        earlier = horizon.get("summary") or {}
        sea, mass, energy = (earlier.get(k) for k in ("SEA_core_J_kg", "core_mass_kg", "core_dissipation_J"))
        scalar_valid = (
            all(type(v) in (int, float) and math.isfinite(v) for v in (sea, mass, energy))
            and sea >= 0
            and mass > 0
            and energy >= 0
            and math.isclose(sea, energy / mass, rel_tol=1e-8)
        )
        valid = (
            shard.get("archive_verified") is True
            and run.get("status") in ("completed", "review")
            and summary.get("solver_completed") is True
            and summary.get("history_integrity_passed") is True
            and summary.get("damage_fields_complete") is True
            and (run.get("quality") or {}).get("numerical_quality") == "passed"
            and math.isclose(summary.get("last_time_s", -1), context["simulation_duration_s"], abs_tol=1e-8)
            and horizon.get("available") is True
            and horizon.get("input_hash") == shard["input_hash"]
            and horizon.get("horizon_s") == context["prediction_horizon_s"]
            and horizon.get("interpolated_deletion_label") is False
            and abs(earlier.get("last_time_s", -1) - context["prediction_horizon_s"]) <= 1e-7
            and scalar_valid
            and type(earlier.get("rear_skin_deleted")) is bool
        )
        if valid:
            complete.append(name)
            (deleted if horizon["summary"]["rear_skin_deleted"] else intact).append(name)
        else:
            missing.append(name)
    result = {
        "expected": expected,
        "numerically_complete": complete,
        "intact_at_prediction_horizon": intact,
        "deleted_at_prediction_horizon": deleted,
        "missing_or_invalid": missing,
        "physical_safety_certified": False,
        "training_eligibility_overridden": False,
    }
    if missing:
        raise ValueError("Verification evidence missing or invalid: " + ", ".join(missing))
    return result
