"""Never reset the impact or reuse a stale/foreign native checkpoint."""

import hashlib
import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from honeycomb_studio.models import digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/continuation12"))
from contract import CASES, FAMILIES, RUNTIME_SHA, claim_segment, verify_plan  # noqa: E402


def archive(names, *, complete=True):
    sha = hashlib.sha256(b"x").hexdigest()
    return {
        "schema_version": "1",
        "kind": "honeycomb-release-archive",
        "complete": complete,
        "files": [
            {
                "path": "raw/" + name,
                "bytes": 1,
                "sha256": sha,
                "parts": [
                    {
                        "index": 0,
                        "offset": 0,
                        "bytes": 1,
                        "sha256": sha,
                        "digest": "sha256:" + sha,
                        "url": "https://github.com/owner/repo/releases/download/tag/" + name,
                    }
                ],
            }
            for name in names
        ],
    }


def plan():
    runtime = {"release": "2020"}
    manifest = archive(["hc." + f for f in FAMILIES])
    return {
        "design_id": "V14-03",
        "repository": "owner/repo",
        "expected_task_sha": "a" * 40,
        "runtime_source_sha": RUNTIME_SHA,
        "automatic_training": False,
        "job_name": "hc",
        "status": "ready",
        "physics_sha256": {"physics.py": hashlib.sha256(b"x").hexdigest()},
        "original_restart_receipt": {
            "complete": True,
            "step_end": True,
            "step": 1,
            "simulation_time_s": 0.008,
            "cpus": 4,
            "precision": "double",
            "job_name": "hc",
            "runtime_hash": digest(runtime),
            "runtime": runtime,
            "files": {
                Path(f["path"]).name: {k: f[k] for k in ("bytes", "sha256")} for f in manifest["files"]
            },
        },
        "original_resolved": {"duration": 0.008, "velocity_m_s": 6.5},
        "original_8ms_manifest": manifest,
        "core_mass_kg": 0.025,
    }


def test_completed_source_hashes_and_native_inventory_are_pinned(tmp_path):
    p = plan()
    (tmp_path / "physics.py").write_bytes(b"x")
    verify_plan(p, "a" * 40, tmp_path)
    (tmp_path / "physics.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Scientific source"):
        verify_plan(p, "a" * 40, tmp_path)


@pytest.mark.parametrize("case", CASES)
def test_all_five_candidates_and_control_can_use_the_same_verified_contract(tmp_path, case):
    p = plan()
    p["design_id"] = case
    (tmp_path / "physics.py").write_bytes(b"x")
    verify_plan(p, "a" * 40, tmp_path)
    assert claim_segment(p, segment=0, workflow=123, attempt=1)["design_id"] == case


@pytest.mark.parametrize(
    "field,value", [("simulation_time_s", 0.007), ("cpus", 2), ("step_end", False), ("precision", "single")]
)
def test_unfinished_or_incompatible_source_is_rejected(tmp_path, field, value):
    p = plan()
    p["original_restart_receipt"][field] = value
    with pytest.raises(ValueError, match="restart identity"):
        verify_plan(p, "a" * 40, tmp_path)


def test_each_checkpoint_is_consumed_once_and_only_by_its_workflow():
    source = plan()
    first = claim_segment(source, segment=0, workflow=123, attempt=1)
    assert source["status"] == "ready"
    with pytest.raises(ValueError, match="already claimed"):
        claim_segment(first, segment=0, workflow=123, attempt=1)
    first.update(
        status="checkpoint",
        current_job="hcto12",
        archive=archive(["hcto12." + f for f in FAMILIES], complete=False),
    )
    resumed = claim_segment(first, segment=1, workflow=123, attempt=1)
    assert resumed["resume_job"] == "hcto12" and resumed["continuation_attempt"] == 1
    assert resumed["restart_source"]["manifest"] == first["archive"]
    assert resumed["original_8ms_manifest"] == source["original_8ms_manifest"]
    for kwargs in (
        {"segment": 2, "workflow": 123, "attempt": 1},
        {"segment": 1, "workflow": 999, "attempt": 1},
        {"segment": 1, "workflow": 123, "attempt": 2},
    ):
        with pytest.raises(ValueError):
            claim_segment(first, **kwargs)


def test_incomplete_native_checkpoint_cannot_trigger_recover():
    first = claim_segment(plan(), segment=0, workflow=123, attempt=1)
    first.update(status="checkpoint", current_job="hcto12", archive=archive(["hcto12.odb"], complete=False))
    with pytest.raises(ValueError, match="families incomplete"):
        claim_segment(first, segment=1, workflow=123, attempt=1)


def test_completed_case_skips_every_further_solver_segment():
    p = claim_segment(plan(), segment=0, workflow=123, attempt=1)
    p["status"] = "completed"
    before = deepcopy(p)
    for segment in (1, 2, 3):
        assert claim_segment(p, segment=segment, workflow=123, attempt=1) == before


def test_publisher_retains_numbered_restart_files_but_excludes_datacheck(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts/continuation98"))
    spec = importlib.util.spec_from_file_location(
        "shared_native12_worker", ROOT / "scripts/continuation98/worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("hc.abq", "hc.odb", "hcto12.abq.1", "hcto12.odb", "hcto12_check.odb"):
        (raw / name).write_bytes(b"x")
    received = []

    class Publisher:
        def __init__(self, *args, **kwargs):
            pass

        def publish(self, stage, **kwargs):
            received.extend(p.name for p in (stage / "raw").iterdir())
            return {}

    class Github:
        def repo(self, method, path, *args, **kwargs):
            return {"id": 1, "html_url": "release"}

    monkeypatch.setattr(module, "ReleaseArchive", Publisher)
    monkeypatch.setattr(module.cloud_archive, "ALLOWED", set(module.cloud_archive.ALLOWED))
    monkeypatch.setenv("TASK_CODE_SHA", "a" * 40)
    module.publish(
        tmp_path,
        raw,
        {"job_name": "hc", "design_id": "V14-03"},
        Github(),
        "checkpoint",
        lambda changes: None,
        "hcto12",
    )
    assert set(received) == {"hc.abq", "hc.odb", "hcto12.abq.1", "hcto12.odb"}


def test_workflow_chains_four_bounded_stages_and_skips_completed_installs():
    workflow = (ROOT / ".github/workflows/continue-v14-12ms.yml").read_text()
    stage = (ROOT / ".github/workflows/continue-v14-stage.yml").read_text()
    assert workflow.count("uses: ./.github/workflows/continue-v14-stage.yml") == 4
    assert "needs: segment0" in workflow and "needs: segment2" in workflow
    assert "timeout-minutes: 330" in stage and "if: steps.claim.outputs.done != 'true'" in stage
    assert RUNTIME_SHA in stage
    assert "collect_cloud_training" not in workflow
    assert "design_id: ${{ fromJSON(inputs.design_ids) }}" in stage
    assert workflow.count("design_ids: ${{ inputs.design_ids }}") == 4
    for case in CASES:
        assert case in workflow
