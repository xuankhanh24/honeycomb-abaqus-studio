"""Real Abaqus worker for one isolated cloud runner. No fake-solver fallback."""

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
from honeycomb_studio.cloud_matrix import ShardCatalog
from honeycomb_studio.cloud_progress import Progress, execution_deadline
from honeycomb_studio.cloud_runtime import execution_runtime
from honeycomb_studio.cloud_streaming import RollingFields
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec, digest, expand
from honeycomb_studio.store import Store, write_json


def require_qualification(root: Path):
    data, reasons = execution_runtime()
    if reasons:
        raise RuntimeError("; ".join(r["status"] + ": " + r["message"] for r in reasons))
    return data


def run(args):
    if not JOB_ID.fullmatch(args.job_id):
        raise ValueError("Invalid job ID")
    github = Github(token=os.environ["GITHUB_TOKEN"])
    catalog = Catalog(github)
    if getattr(args, "parent_id", None):
        if not JOB_ID.fullmatch(args.parent_id):
            raise ValueError("Invalid parent job ID")
        catalog = ShardCatalog(catalog, args.parent_id, args.job_id, int(os.environ["GITHUB_RUN_ID"]))
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
    field_sink = None
    try:
        deadline = execution_deadline(os.environ["HONEYCOMB_WORKFLOW_STARTED_EPOCH"])
        runtime = require_qualification(Path.cwd())
        if not args.abaqus.is_file() or os.name == "nt":
            raise RuntimeError("blocked_environment: a Linux Abaqus executable is required")
        args.root.mkdir(parents=True, exist_ok=True)
        actual_release = subprocess.run(
            [str(args.abaqus), "information=release"], cwd=args.root,
            capture_output=True, text=True, timeout=60
        )
        if actual_release.returncode or runtime["release"] not in actual_release.stdout:
            raise RuntimeError("blocked_environment: installed Abaqus does not match runtime lock")
        spec_data = job["spec"]
        if digest(spec_data) != job["input_hash"]:
            raise ValueError("Requested input digest does not match the catalog")
        spec_data = json.loads(json.dumps(spec_data))
        spec_data.update(max_runs=20, backup_after_run=False)
        if job["profile"] == "smoke":
            spec_data["data_profile"] = "smoke"
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
        progress = Progress(github, catalog, args.job_id, store, batch["id"], deadline)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: progress.stop_solver())
        progress.start(os.environ["GITHUB_SHA"])
        write_json(args.root / "runtime-lock.json", runtime)
        write_json(args.root / "cloud-request.json", job)
        release = github.repo("PATCH", f"/releases/{job['reserved_release_id']}", {
            "draft": False,
            "body": "Owner-requested native Linux run. Runtime certification remains unverified; inspect actual quality and archive manifests.",
        }) if job.get("reserved_release_id") else github.repo(
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
        if job["profile"] == "full":
            field_sink = RollingFields(args.root, ReleaseArchive(github, release_id), f"workflow-{workflow_id}")
            engine.field_sink = field_sink
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
        pending = store.list("runs", batch["id"])
        wave_index = 0
        while pending:
            if progress.stop_reason or time.monotonic() >= deadline:
                raise RuntimeError((progress.stop_reason or "timed_out") + ": completed runs retained")
            if store.get("batches", batch["id"]).get("pause_requested"):
                reason = "blocked_license" if any(r["status"] == "waiting_license" for r in pending) else "blocked_environment"
                raise RuntimeError(reason + ": batch paused; inspect retained admission/license diagnostics")
            eligible = [run for run in pending if run["status"] != "waiting_license" or run.get("retry_after", 0) <= time.time()]
            if not eligible:
                if store.get("batches", batch["id"]).get("pause_requested"):
                    raise RuntimeError("blocked_license: retries exhausted; all attempt logs retained")
                time.sleep(min(5, max(.1, min(run["retry_after"] for run in pending) - time.time())))
                continue
            wave = engine.execute_wave(eligible, batch)
            wave_index += 1
            if not wave:
                raise RuntimeError("blocked_environment: insufficient CPU/RAM/disk for requested run configuration")
            for finished in wave:
                record = {k: finished.get(k) for k in ("id", "status", "summary", "quality", "error")}
                attempt = finished.get("attempts", [])
                view = Path(attempt[-1]["path"]) / "extracted/field-view.json" if attempt else None
                if view and view.is_file() and view.stat().st_size <= 4 * 1024**2:
                    try:
                        uploaded = ReleaseArchive(github, release_id).upload(
                            view, f"workflow-{workflow_id}-{finished['id']}-field-view.json"
                        )
                        record["field_view"] = {**uploaded, "sha256": uploaded["digest"].removeprefix("sha256:")}
                    except Exception:
                        # Display convenience is secondary to the complete numerical archive.
                        record["field_view_status"] = "direct_view_upload_failed; use verified archive"
                completed = [r for r in completed if r["id"] != record["id"]] + [record]
                catalog.update(
                    key,
                    lambda old: {
                        **old,
                        "runs": completed,
                    "status": finished["status"]
                    if finished["status"] not in ("completed", "review", "waiting_license")
                        else "running",
                    },
                )
            # Every process in this wave has closed its files. Archive before
            # admitting the next wave; never snapshot a live solver output.
            ReleaseArchive(github, release_id).publish(
                args.root, attempt=f"workflow-{workflow_id}", complete=False, checkpoint=f"wave-{wave_index:04d}"
            )
            if any(run["status"] not in ("completed", "review", "waiting_license") for run in wave):
                raise RuntimeError((progress.stop_reason or "failed") + ": see preserved attempt logs")
            done = {run["id"] for run in wave if run["status"] in ("completed", "review")}
            pending = [store.get("runs", run["id"]) for run in pending if run["id"] not in done]
        result_status = "review" if any(r["status"] == "review" for r in completed) else "completed"
    except Exception as exc:
        message = str(exc)
        result_status = next(
            (
                s
                for s in ("blocked_environment", "blocked_license", "blocked_platform_policy", "cancelled", "timed_out")
                if s in message
            ),
            "failed",
        )
        catalog.update(key, lambda old: {**old, "status": result_status, "error": message})
        raise
    finally:
        archive_error = None
        if field_sink is not None:
            try:
                field_sink.flush()
            except Exception:
                # Failed volumes retain their local Parquet and are included in
                # the incomplete final archive. Never certify interrupted export.
                result_status = "failed"
        if release_id:
            try:
                ReleaseArchive(github, release_id).publish(
                    args.root,
                    attempt=f"workflow-{workflow_id}",
                    complete=result_status in ("completed", "review"),
                )
            except Exception as exc:
                archive_error = exc
                result_status = "archive_failed"
            try:
                catalog.update(key, lambda old: {
                    **old, "status": result_status, "archive_verified": archive_error is None,
                })
            except Exception:
                # The release manifest remains the durable truth even if the
                # convenience catalog cannot be updated.
                write_json(args.root / "catalog-update-pending.json", {
                    "status": result_status, "archive_verified": archive_error is None,
                })
            # Secondary backup and status-update failure cannot invalidate the
            # already verified primary archive.
            if store and archive_error is None:
                backup = backup_readable(
                    store, batch["id"], Path(os.environ["RUNNER_TEMP"]) / "private-drive"
                )
                try:
                    catalog.update(key, lambda old: {**old, "drive_backup": backup})
                except Exception:
                    write_json(args.root / "drive-backup-status.json", backup)
        try:
            if progress:
                progress.finish(result_status)
            catalog.update("index", lambda old: {
                "jobs": [dict(row, status=result_status) if row["id"] == args.job_id else row
                         for row in (old or {}).get("jobs", [])]
            })
        except Exception:
            pass
        finally:
            if store:
                store.db.close()
        if archive_error:
            raise RuntimeError("Archive incomplete; retained runner diagnostics are not a durable dataset") from archive_error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--parent-id", help="Parent batch when running one Actions matrix design")
    parser.add_argument("--abaqus", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args())
