"""Real sequential Abaqus worker. No fake-solver fallback and no local-machine fallback."""

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_drive import backup_readable
from honeycomb_studio.cloud_github import JOB_ID, Catalog, Github
from honeycomb_studio.cloud_progress import Progress
from honeycomb_studio.cloud_runtime import qualification
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec, digest, expand
from honeycomb_studio.store import Store, write_json


def require_qualification(root: Path):
    data, reasons = qualification(root / "runtime-lock.json")
    if reasons:
        raise RuntimeError("; ".join(r["status"] + ": " + r["message"] for r in reasons))
    return data


def run(args):
    if not JOB_ID.fullmatch(args.job_id):
        raise ValueError("Invalid job ID")
    github = Github(token=os.environ["GITHUB_TOKEN"])
    catalog = Catalog(github)
    key = "jobs/" + args.job_id
    job, _ = catalog.get(key)
    if job is None:
        raise ValueError("The requested job is not in the catalog")
    workflow_id = int(os.environ["GITHUB_RUN_ID"])

    def claim(old):
        if old.get("workflow_run_id") and old["workflow_run_id"] != workflow_id:
            raise ValueError("This job already belongs to another workflow; refusing a duplicate solver")
        if old["status"] not in ("draft", "dispatching") or old.get("cancel_requested"):
            raise ValueError("Job cannot be claimed in its current state")
        return {**old, "workflow_run_id": workflow_id, "status": "preflight"}

    catalog.update(key, claim)
    store = None
    progress = None
    engine = None
    result_status = "failed"
    release_id = None
    started = time.monotonic()
    try:
        runtime = require_qualification(Path.cwd())
        if not args.abaqus.is_file() or os.name == "nt":
            raise RuntimeError("blocked_environment: a Linux Abaqus executable is required")
        actual_release = subprocess.run(
            [str(args.abaqus), "information=release"], capture_output=True, text=True, timeout=60
        )
        if actual_release.returncode or runtime["release"] not in actual_release.stdout:
            raise RuntimeError("blocked_environment: installed Abaqus does not match runtime lock")
        spec_data = job["spec"]
        if digest(spec_data) != job["input_hash"]:
            raise ValueError("Requested input digest does not match the catalog")
        spec_data = json.loads(json.dumps(spec_data))
        spec_data.update(max_runs=10, backup_after_run=False)
        spec_data["model"]["cpus"] = 4
        for design in spec_data.get("designs", []):
            design["cpus"] = 4
        if job["profile"] == "smoke":
            short = {"duration": 0.0001, "field_intervals": 4, "history_intervals": 100}
            spec_data["model"].update(short)
            spec_data["designs"] = [dict(d, **short) for d in spec_data.get("designs", [])]
            spec_data.update(render_images=False)
        spec_data["export_all_fields"] = job["profile"] == "full"
        spec = BatchSpec.model_validate(spec_data)
        expand(spec)
        args.root.mkdir(parents=True, exist_ok=True)
        store = Store(args.root)
        if store.list("batches"):
            raise ValueError("Use a clean workspace; do not silently reuse an earlier cloud attempt")
        engine = Engine(store, abaqus=str(args.abaqus), fake=False)
        engine.runtime_fingerprint = digest(runtime)
        batch = store.create(spec)
        progress = Progress(github, catalog, args.job_id, store, batch["id"], started + 285 * 60)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: progress.stop_solver())
        progress.start(os.environ["GITHUB_SHA"])
        write_json(args.root / "runtime-lock.json", runtime)
        write_json(args.root / "cloud-request.json", job)
        release = github.repo(
            "POST",
            "/releases",
            {
                "tag_name": "simulation-" + args.job_id,
                "target_commitish": os.environ["GITHUB_SHA"],
                "name": spec.name,
                "body": "Public research run. See the attempt manifest for completeness and scientific quality.",
                "draft": False,
            },
        )
        release_id = release["id"]
        catalog.update(
            key,
            lambda old: {
                **old,
                "status": "running",
                "release_id": release_id,
                "release_url": release["html_url"],
            },
        )
        completed = []
        for run in store.list("runs", batch["id"]):
            if time.monotonic() - started > 285 * 60:
                raise RuntimeError(
                    "Job budget reached; completed runs are retained. Native solver restart is not qualified."
                )
            engine._execute(run, batch)
            finished = store.get("runs", run["id"])
            completed.append({k: finished.get(k) for k in ("id", "status", "summary", "quality", "error")})
            catalog.update(
                key,
                lambda old: {
                    **old,
                    "runs": completed,
                    "status": finished["status"]
                    if finished["status"] not in ("completed", "review")
                    else "running",
                },
            )
            if finished["status"] not in ("completed", "review"):
                raise RuntimeError("A run did not complete; see its preserved attempt logs")
            # Preserve each completed run before spending runner time on the next one.
            ReleaseArchive(github, release_id).publish(
                args.root, attempt=f"workflow-{workflow_id}-run-{run['id']}", complete=False
            )
        result_status = "review" if any(r["status"] == "review" for r in completed) else "completed"
    except Exception as exc:
        message = str(exc)
        result_status = next(
            (
                s
                for s in ("blocked_environment", "blocked_license", "blocked_platform_policy")
                if s in message
            ),
            "failed",
        )
        catalog.update(key, lambda old: {**old, "status": result_status, "error": message})
        raise
    finally:
        if progress:
            progress.finish(result_status)
        if store:
            try:
                catalog.update(
                    "index",
                    lambda old: {
                        "jobs": [
                            dict(row, status=result_status) if row["id"] == args.job_id else row
                            for row in (old or {}).get("jobs", [])
                        ]
                    },
                )
            except Exception:
                pass
        if release_id:
            try:
                ReleaseArchive(github, release_id).publish(
                    args.root,
                    attempt=f"workflow-{workflow_id}",
                    complete=result_status in ("completed", "review"),
                )
                catalog.update(key, lambda old: {**old, "status": result_status, "archive_verified": True})
                if store:
                    backup = backup_readable(
                        store, batch["id"], Path(os.environ["RUNNER_TEMP"]) / "private-drive"
                    )
                    catalog.update(key, lambda old: {**old, "drive_backup": backup})
            except Exception:
                catalog.update(
                    key,
                    lambda old: {
                        **old,
                        "status": "archive_failed",
                        "archive_verified": False,
                        "error": "Archive incomplete; runner files must not be treated as a durable complete dataset.",
                    },
                )
                raise

        if store:
            store.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--abaqus", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args())
