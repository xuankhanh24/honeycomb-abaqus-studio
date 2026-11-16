from copy import deepcopy

import pytest

from honeycomb_studio.models import BatchSpec, digest
from honeycomb_studio.validation_completion import verification_completion


def parent():
    spec = BatchSpec(
        name="Frozen verification",
        model={"core_topology": "reentrant_0", "reentrant_geometry": "angle", "duration": 0.012},
        sampling="table",
        designs=[{"reentrant_delta_deg": 30.0}, {"reentrant_delta_deg": 31.0}],
        max_runs=2,
    ).model_dump()
    shards = []
    for i, deleted in enumerate([False, True]):
        input_hash = str(i) * 64
        shards.append(
            {
                "index": i,
                "input_hash": input_hash,
                "archive_verified": True,
                "runs": [
                    {
                        "status": "review" if deleted else "completed",
                        "summary": {
                            "solver_completed": True,
                            "history_integrity_passed": True,
                            "damage_fields_complete": True,
                            "last_time_s": 0.012,
                        },
                        "quality": {"numerical_quality": "passed", "ml_eligible": not deleted},
                        "research_horizon": {
                            "available": True,
                            "horizon_s": 0.008,
                            "input_hash": input_hash,
                            "interpolated_deletion_label": False,
                            "summary": {
                                "rear_skin_deleted": deleted,
                                "last_time_s": 0.008,
                                "SEA_core_J_kg": 1000.0,
                                "core_mass_kg": 0.025,
                                "core_dissipation_J": 25.0,
                            },
                        },
                    }
                ],
            }
        )
    return {
        "spec": spec,
        "input_hash": digest(spec),
        "validation_context": {
            "kind": "locked-surrogate-fea-verification-v1",
            "candidate_ids": ["A", "B"],
            "prediction_horizon_s": 0.008,
            "simulation_duration_s": 0.012,
        },
        "shards": shards,
    }


def test_completed_deleted_case_is_valid_evidence_without_changing_training_gate():
    value = parent()
    original = deepcopy(value)
    result = verification_completion(value)
    assert result["numerically_complete"] == ["A", "B"]
    assert result["deleted_at_prediction_horizon"] == ["B"]
    assert result["training_eligibility_overridden"] is False
    assert value == original and value["shards"][1]["runs"][0]["quality"]["ml_eligible"] is False


@pytest.mark.parametrize("problem", ["archive", "horizon", "quality", "input", "scalar", "time"])
def test_verification_still_fails_on_incomplete_or_invalid_evidence(problem):
    value = parent()
    shard = value["shards"][1]
    if problem == "archive":
        shard["archive_verified"] = False
    elif problem == "horizon":
        shard["runs"][0]["research_horizon"]["available"] = False
    elif problem == "quality":
        shard["runs"][0]["quality"]["numerical_quality"] = "review"
    elif problem == "input":
        shard["runs"][0]["research_horizon"]["input_hash"] = "f" * 64
    elif problem == "scalar":
        shard["runs"][0]["research_horizon"]["summary"]["SEA_core_J_kg"] = 999.0
    else:
        shard["runs"][0]["research_horizon"]["summary"]["last_time_s"] = 0.012
    with pytest.raises(ValueError, match="missing or invalid"):
        verification_completion(value)
