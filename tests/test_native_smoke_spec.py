"""Validate acceptance inputs before downloading media or joining a license network."""

import importlib.util
import json
from pathlib import Path

from honeycomb_studio.models import BatchSpec, expand


def test_parallel_smoke_expands_real_single_run_example_without_changing_reference(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    directory = root / "scripts/linux_media"
    monkeypatch.syspath_prepend(str(directory))
    module_spec = importlib.util.spec_from_file_location("native_impact_acceptance_fixture", directory / "impact_test.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    original = json.loads((root / "examples/reentrant-perimeter-7J.json").read_text(encoding="utf-8"))
    before = json.dumps(original, sort_keys=True)
    effective = module.parallel_smoke_input(original)
    runs = expand(BatchSpec.model_validate(effective))
    assert len(runs) == effective["max_runs"] == 2
    assert sorted(round(r["resolved"]["reentrant_delta_deg"]) for r in runs) == [20, 30]
    assert all(r["resolved"]["cpus"] == 2 and r["resolved"]["duration"] == .00002 for r in runs)
    assert effective["data_profile"] == "smoke" and effective["execution_mode"] == "parallel"
    assert effective["runtime_budget_minutes"] == 30
    assert before == json.dumps(original, sort_keys=True)
    assert original["model"]["duration"] == .006
