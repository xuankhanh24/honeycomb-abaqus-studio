"""Durable, closed ODB snapshots for postprocessing recovery, never FE restart."""

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .cloud_restore import destination, restore, validate_manifest
from .data import checksum
from .engine import Engine
from .models import BatchSpec, digest, expand
from .solver import sta_progress
from .solver_checkpoint_ref import ARCHIVED_KIND, KIND, validate_reference
from .store import Store, write_json

PHYSICS = ("models.py", "adapters/build.py", "adapters/reentrant.py", "adapters/hexagonal.py",
           "adapters/damage_keywords.py", "adapters/damage_metrics.py")


def physics_hashes():
    source = Path(__file__).parent
    return {Path(name).name: checksum(source / name) for name in PHYSICS}


def _closed_solver(run, folder):
    attempt = run["attempts"][-1]
    if run.get("test_only") is True or attempt.get("process"):
        raise ValueError("Cannot snapshot a synthetic or live solver")
    name = attempt["job_name"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", name):
        raise ValueError("Invalid solver job name")
    raw = folder / "raw"
    for path in (folder, raw):
        if path.is_symlink():
            raise ValueError("Linked solver directories are not admitted")
    odb = raw / (name + ".odb")
    marker = folder / "solver-complete.json"
    if (not odb.is_file() or odb.is_symlink() or not odb.stat().st_size
            or not marker.is_file() or marker.is_symlink() or (raw / (name + ".lck")).exists()):
        raise ValueError("Missing complete, unlocked native ODB")
    complete = json.loads(marker.read_text(encoding="utf-8"))
    sta = sta_progress(raw / (name + ".sta"), run["resolved"]["duration"])
    if complete.get("sta", {}).get("solver_success") is not True or sta.get("solver_success") is not True:
        raise ValueError("Solver completion must be confirmed by the original STA")
    return sta


def snapshot_view(root, target, run, batch, runtime, job, source_sha):
    """Only this closed run is linked; concurrent runs and private files stay out."""
    root, target = root.resolve(), target.resolve()
    if digest(job["spec"]) != job["input_hash"]:
        raise ValueError("Cloud input digest changed before solver backup")
    expected = expand(BatchSpec.model_validate(job["spec"]))
    if len(expected) != 1 or any(run[k] != expected[0][k] for k in ("requested", "resolved", "input_hash")):
        raise ValueError("Solver checkpoint requires exactly one matching scientific input")
    folder = Path(run["attempts"][-1]["path"])
    relative = folder.resolve().relative_to(root)
    _closed_solver(run, folder)
    science = physics_hashes()
    original = run["attempts"][-1].get("software", {}).get("source_sha256", {})
    if any(original.get(name) != value for name, value in science.items()):
        raise ValueError("Solver scientific sources differ from the checkpoint writer")
    saved = copy.deepcopy(run)
    saved.update(status="queued", phase="queued", error=None, force_new_solver=False, explicit_recover=False)
    for key in ("summary", "quality", "report", "solver_checkpoint"):
        saved.pop(key, None)
    saved["attempts"] = [saved["attempts"][-1]]
    saved["attempts"][-1]["process"] = None
    run_relative = Path(run["path"]).resolve().relative_to(root) / "run.json"
    batch_relative = Path(batch["path"]).resolve().relative_to(root) / "batch.json"
    write_json(destination(target, run_relative.as_posix()), saved)
    write_json(destination(target, batch_relative.as_posix()), batch)
    name = run["attempts"][-1]["job_name"]
    sources = [folder / "solver-complete.json", folder / "raw/model_manifest.json"]
    sources += [folder / "raw" / (name + suffix) for suffix in (".odb", ".sta", ".inp", ".cae", ".dat", ".msg", ".log")]
    for source in sources:
        if not source.exists():
            if source.suffix in (".odb", ".sta", ".inp") or source.name == "solver-complete.json":
                raise ValueError("Required solver checkpoint file missing: " + source.name)
            continue
        source_relative = source.relative_to(root)
        destination(root, source_relative.as_posix())
        if not source.is_file():
            raise ValueError("Invalid solver checkpoint file")
        linked = destination(target, source_relative.as_posix())
        linked.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, linked)
    metadata = {
        "kind": KIND, "input_hash": job["input_hash"], "run_input_hash": run["input_hash"],
        "source_sha": source_sha, "runtime_hash": digest(runtime), "physics_sha256": science,
        "run_manifest": run_relative.as_posix(), "batch_manifest": batch_relative.as_posix(),
        "attempt_path": relative.as_posix(), "solver_completed": True,
        "postprocessing_complete": False, "physical_validation": "not_established",
        "scope": "completed ODB for postprocessing; native FE restart families are not included",
    }
    write_json(target / "solver-snapshot.json", metadata)
    return metadata


def publish_solver_checkpoint(root, run, batch, runtime, job, publisher, attempt, source_sha):
    """Return a recovery reference only after every part and manifest is verified."""
    with tempfile.TemporaryDirectory(prefix="solver-checkpoint-", dir=root.resolve().parent) as temp:
        view = Path(temp)
        metadata = snapshot_view(root, view, run, batch, runtime, job, source_sha)
        suffix = "solver-" + run["id"]
        manifest = publisher.publish(view, attempt=attempt, complete=False, checkpoint=suffix)
        path = view / "checkpoint-manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
        asset = publisher.upload(path, f"{attempt}-checkpoint-{suffix}-artifact-manifest.json")
    return {"kind": KIND, "available": True, "input_hash": job["input_hash"],
            "run_input_hash": run["input_hash"], "runtime_hash": digest(runtime),
            "source_sha": source_sha, "manifest": asset, "solver_completed": True,
            "postprocessing_complete": False, "physics_sha256": metadata["physics_sha256"]}


def restore_solver_checkpoint(store: Store, job, spec, runtime, github):
    """Verify the archive and original inputs, then queue the original ODB only."""
    reference = job["postprocess_source"]
    validate_reference(reference, job["input_hash"])
    if reference["runtime_hash"] != digest(runtime):
        raise ValueError("Checkpoint Abaqus runtime differs; new FE execution is forbidden")
    asset = reference["manifest"]
    remote = github.repo("GET", f"/releases/assets/{asset['asset_id']}")
    if (remote["digest"] != asset["digest"] or remote["size"] != asset["bytes"]
            or remote["browser_download_url"] != asset["url"]):
        raise ValueError("Completed-solver checkpoint manifest asset changed")
    response = github.client.get(asset["url"])
    response.raise_for_status()
    if len(response.content) != asset["bytes"] or "sha256:" + hashlib.sha256(response.content).hexdigest() != asset["digest"]:
        raise ValueError("Completed-solver checkpoint manifest checksum failed")
    manifest = response.json()
    validate_manifest(manifest, allow_incomplete=True)
    if reference["kind"] == ARCHIVED_KIND:
        return _restore_archived_solver(store, job, spec, runtime, github, manifest)
    if "solver-snapshot.json" not in {file["path"] for file in manifest["files"]}:
        raise ValueError("Archive is not a completed-solver snapshot")
    restore(manifest, store.root, client=github.client, allow_incomplete=True)
    metadata = json.loads((store.root / "solver-snapshot.json").read_text(encoding="utf-8"))
    for key in ("kind", "input_hash", "run_input_hash", "runtime_hash", "source_sha"):
        if metadata.get(key) != reference[key]:
            raise ValueError("Restored solver checkpoint identity differs: " + key)
    if metadata.get("solver_completed") is not True or metadata.get("physics_sha256") != physics_hashes():
        raise ValueError("Restored solver scientific source differs")
    store.reindex()
    runs, batches = store.list("runs"), store.list("batches")
    if len(runs) != 1 or len(batches) != 1 or batches[0]["spec"] != spec.model_dump():
        raise ValueError("Restored solver batch differs from the requested postprocessing")
    run, batch = runs[0], batches[0]
    expected = expand(spec)[0]
    if any(run[key] != expected[key] for key in ("input_hash", "requested", "resolved")):
        raise ValueError("Restored solver scientific inputs differ")
    if run["input_hash"] != reference["run_input_hash"]:
        raise ValueError("Restored solver input hash differs")
    folder = Path(run["attempts"][-1]["path"])
    folder.resolve().relative_to(store.root)
    _closed_solver(run, folder)
    run.update(status="queued", phase="queued", force_new_solver=False, explicit_recover=False, error=None)
    batch.update(status="running", pause_requested=False, stop_immediately=False)
    store.save("runs", run)
    store.save("batches", batch)
    return batch


def _restore_archived_solver(store, job, spec, runtime, github, manifest):
    """Admit a legacy closed ODB without certifying its interrupted extraction."""
    files = {file["path"]: file for file in manifest["files"]}
    run_paths = [path for path in files if path.endswith("/run.json")]
    batch_paths = [path for path in files if path.endswith("/batch.json")]
    if len(run_paths) != 1 or len(batch_paths) != 1:
        raise ValueError("Legacy recovery requires exactly one archived run and batch")
    metadata = [*run_paths, *batch_paths, "runtime-lock.json", "cloud-request.json"]
    if not set(metadata) <= files.keys():
        raise ValueError("Legacy recovery is missing native input or runtime evidence")
    restore(manifest, store.root, client=github.client, allow_incomplete=True, paths=metadata)
    def read(name):
        return json.loads(destination(store.root, name).read_text(encoding="utf-8"))
    run, batch = read(run_paths[0]), read(batch_paths[0])
    request = read("cloud-request.json")
    if (digest(read("runtime-lock.json")) != digest(runtime)
            or request.get("input_hash") != job["input_hash"]
            or digest(request.get("spec", {})) != job["input_hash"]
            or batch.get("spec") != spec.model_dump()):
        raise ValueError("Legacy runtime or scientific batch identity differs")
    expected = expand(spec)
    if (len(expected) != 1 or len(run.get("attempts", [])) != 1
            or any(run.get(key) != expected[0][key] for key in ("requested", "resolved", "input_hash"))
            or run["input_hash"] != job["postprocess_source"]["run_input_hash"]):
        raise ValueError("Legacy solver inputs or original attempt differ")
    attempt = run["attempts"][0]
    original = attempt.get("software", {}).get("source_sha256", {})
    if any(original.get(name) != checksum for name, checksum in physics_hashes().items()):
        raise ValueError("Legacy solver scientific source differs")
    relative = Path(run_paths[0]).parent / "attempts" / f"{attempt['number']:03d}"
    name = attempt["job_name"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", name):
        raise ValueError("Invalid legacy solver job name")
    wanted = [(relative / "solver-complete.json").as_posix()]
    wanted += [(relative / "raw" / (name + suffix)).as_posix() for suffix in (".odb", ".sta", ".inp")]
    model = (relative / "raw/model_manifest.json").as_posix()
    if model in files:
        wanted.append(model)
    if not set(wanted) <= files.keys() or any(files[path]["bytes"] <= 0 for path in wanted):
        raise ValueError("Legacy archive lacks a complete original ODB, STA or input deck")
    restore(manifest, store.root, client=github.client, allow_incomplete=True, paths=wanted)
    _closed_solver(run, destination(store.root, relative.as_posix()))
    # Rebase saved filesystem paths only after the original solver checks pass.
    store.reindex()
    run, batch = store.list("runs")[0], store.list("batches")[0]
    run.update(status="queued", phase="queued", force_new_solver=False, explicit_recover=False, error=None)
    for key in ("summary", "quality", "report"):
        run.pop(key, None)
    run["solver_recovery"] = {
        "kind": ARCHIVED_KIND, "new_FE_solve": False,
        "manifest_digest": job["postprocess_source"]["manifest"]["digest"],
        "source_sha": job["postprocess_source"]["source_sha"],
        "native_extraction_complete": False,
    }
    batch.update(status="running", pause_requested=False, stop_immediately=False)
    store.save("runs", run)
    store.save("batches", batch)
    return batch


class SavedSolverEngine(Engine):
    """An extraction recovery can never fall back to build/check/solve."""

    postprocess_only = True

    def _execute(self, r, batch):
        if (len(r.get("attempts", [])) != 1 or r.get("force_new_solver") or r.get("explicit_recover")):
            raise ValueError("Postprocessing recovery requires the original solver attempt")
        _closed_solver(r, Path(r["attempts"][0]["path"]))
        return super()._execute(r, batch)

    def _monitor(self, r, a, phase, args, spool=None):
        if phase in ("building", "checking", "solving"):
            raise ValueError("Postprocessing recovery forbids a new FE process")
        return super()._monitor(r, a, phase, args, spool)
