"""Identity and single-owner handoff for the V14 native 8–12 ms study."""

from copy import deepcopy
from pathlib import Path

from honeycomb_studio.cloud_restore import validate_manifest
from honeycomb_studio.models import digest

KEY = "continuation-v14-12ms-20261117/"
CASES = ("V14-03", "CTRL-0245")
RUNTIME_SHA = "3b40ff65510518e9be6aca9efe53990f86beff82"
FAMILIES = ("abq", "res", "mdl", "stt", "pac", "prt", "sel", "odb")


def verify_plan(plan, source_sha, runtime_root):
    if not plan or plan.get("design_id") not in CASES or plan.get("expected_task_sha") != source_sha:
        raise ValueError("Unapproved case or task source")
    if plan.get("runtime_source_sha") != RUNTIME_SHA or plan.get("automatic_training") is not False:
        raise ValueError("Unexpected runtime or training policy")
    receipt = plan["original_restart_receipt"]
    if (
        receipt.get("complete") is not True
        or receipt.get("step_end") is not True
        or receipt.get("step") != 1
        or receipt.get("simulation_time_s") != 0.008
        or receipt.get("cpus") != 4
        or receipt.get("precision") != "double"
        or receipt.get("job_name") != plan["job_name"]
        or receipt.get("runtime_hash") != digest(receipt["runtime"])
    ):
        raise ValueError("Original completed restart identity differs")
    for path, expected in plan["physics_sha256"].items():
        import hashlib

        if hashlib.sha256((Path(runtime_root) / path).read_bytes()).hexdigest() != expected:
            raise ValueError("Scientific source differs: " + path)
    if plan["original_resolved"]["duration"] != 0.008 or plan["original_resolved"]["velocity_m_s"] != 6.5:
        raise ValueError("Original horizon or velocity differs")
    if plan["core_mass_kg"] <= 0:
        raise ValueError("Missing original core mass")
    manifest = plan["original_8ms_manifest"]
    validate_manifest(manifest, repository=plan["repository"])
    by_name = {Path(f["path"]).name: f for f in manifest["files"]}
    for name, record in receipt["files"].items():
        file = by_name.get(name, {})
        if any(file.get(k) != record[k] for k in ("sha256", "bytes")):
            raise ValueError("Original release differs from sealed state: " + name)
    if not all(plan["job_name"] + "." + family in receipt["files"] for family in FAMILIES):
        raise ValueError("Missing sealed native restart family")


def claim_segment(old, *, segment, workflow, attempt):
    """Only the next segment in the same workflow can consume a checkpoint."""
    if not 0 <= segment <= 3:
        raise ValueError("Unapproved segment")
    if old.get("workflow_run_id") and old["workflow_run_id"] != workflow:
        raise ValueError("Another workflow owns this continuation")
    if old.get("workflow_run_attempt", attempt) != attempt:
        raise ValueError("Workflow rerun requires reviewed recovery; duplicate solve blocked")
    if old["status"] == "completed":
        return old
    plan = deepcopy(old)
    if segment == 0:
        if old["status"] not in ("ready", "dispatching") or old.get("workflow_run_id"):
            raise ValueError("Initial continuation already claimed")
    else:
        if old["status"] != "checkpoint" or old.get("segment") != segment - 1:
            raise ValueError("No verified immediately preceding checkpoint")
        archive = old["archive"]
        validate_manifest(archive, allow_incomplete=True, repository=old["repository"])
        job = old["current_job"]
        if job != old["job_name"] + "to12":
            raise ValueError("Checkpoint is not the native extension job")
        names = {Path(f["path"]).name for f in archive["files"]}
        if not all(job + "." + family in names for family in FAMILIES):
            raise ValueError("Checkpoint native families incomplete")
        plan.update(restart_source={"kind": "release", "manifest": archive}, resume_job=job)
    plan.update(
        status="preparing",
        phase="preparing",
        segment=segment,
        continuation_attempt=segment,
        workflow_run_id=workflow,
        workflow_run_attempt=attempt,
    )
    return plan
