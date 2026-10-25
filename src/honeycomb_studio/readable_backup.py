"""Publish frozen PDF and training products as ordinary Drive files beside ZIP."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .data import checksum
from .retained import verify_retained
from .store import now, write_json


def publish(backup, state_path: Path):
    from google.auth.transport.requests import AuthorizedSession

    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("readable_verified"):
        return state
    root = Path(state["readable_path"])
    try:
        inventory = verify_retained(root, state["readable_manifest_sha256"])
        entries = list(inventory["files"])
        manifest = root / "artifact-manifest.json"
        entries.append(
            {"path": manifest.name, "bytes": manifest.stat().st_size, "sha256": checksum(manifest)}
        )
        priority = {
            "reports/batch-report.pdf": 0,
            "reports/batch-report.docx": 1,
            "training/samples.csv": 2,
            "training/samples.parquet": 3,
            "training/data-dictionary.json": 4,
            "training/job-coverage.csv": 5,
        }
        entries.sort(key=lambda e: (priority.get(e["path"], 6), e["path"]))
        state.update(status="uploading_readable", stage="creating_readable_folders", updated_at=now())
        state.pop("error", None)
        write_json(state_path, state)
        folders = state.get("readable_folders", {})
        with AuthorizedSession(backup.credentials()) as session:
            if "." not in folders:
                parent = backup._folder(session, "Honeycomb Abaqus Studio", "root")
                parent = backup._folder(
                    session,
                    state.get("name", state["batch_id"]) + " [" + state["batch_id"] + "]",
                    state["batch_id"],
                    parent,
                )
                folders["."] = backup._folder(
                    session,
                    "PDF và dữ liệu huấn luyện [" + state["id"] + "]",
                    state["id"] + "-readable",
                    parent,
                )
                state.update(
                    readable_folder_id=folders["."],
                    readable_folders=folders,
                    readable_url="https://drive.google.com/drive/folders/" + folders["."],
                )
                write_json(state_path, state)
            parents = {p.as_posix() for e in entries for p in Path(e["path"]).parents if p.as_posix() != "."}
            for relative in sorted(parents, key=lambda p: (len(Path(p).parts), p)):
                if relative in folders:
                    continue
                key = state["id"] + "-" + hashlib.sha256(relative.encode()).hexdigest()[:20]
                folders[relative] = backup._folder(
                    session, Path(relative).name, key, folders[Path(relative).parent.as_posix()]
                )
                state["readable_folders"] = folders
                state.update(readable_folders_done=len(folders), updated_at=now())
                write_json(state_path, state)
        records = []
        state.update(
            status="uploading_readable",
            stage="uploading_readable_files",
            readable_files_total=len(entries),
            readable_files_done=0,
        )
        write_json(state_path, state)
        child_states = backup.states / "readable" / state["id"]

        def send(entry):
            source = root / entry["path"]
            identity = "bk" + hashlib.sha256((state["id"] + "/" + entry["path"]).encode()).hexdigest()[:16]
            path = child_states / (identity + ".json")
            if not path.exists():
                mime = {".csv": "text/csv", ".parquet": "application/vnd.apache.parquet"}.get(
                    source.suffix.lower(), mimetypes.guess_type(source.name)[0] or "application/octet-stream"
                )
                write_json(
                    path,
                    {
                        "id": identity,
                        "batch_id": state["batch_id"],
                        "file": str(source),
                        "drive_name": source.name,
                        "mime_type": mime,
                        "parent_id": folders[Path(entry["path"]).parent.as_posix()],
                        "bytes": entry["bytes"],
                        "sha256": entry["sha256"],
                        "md5": checksum(source, "md5"),
                        "status": "prepared",
                        "offset": 0,
                    },
                )
            for attempt in range(3):
                try:
                    result = backup._upload_file(path)
                    break
                except RuntimeError:
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
            if result["status"] != "verified":
                raise ValueError("Tệp riêng chưa được xác minh: " + entry["path"])
            return {
                **entry,
                "drive_file_id": result["drive_file_id"],
                "web_url": result.get("web_url"),
                "verified_at": result["verified_at"],
            }

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(send, entry): entry for entry in entries}
            for future in as_completed(futures):
                records.append(future.result())
                state.update(
                    readable_files_done=len(records),
                    updated_at=now(),
                    readable_percent=100 * len(records) / len(entries),
                )
                write_json(state_path, state)
        records.sort(key=lambda r: r["path"])
        if state.get("kind") == "readable_bundle" and state.get("archive_backup_id"):
            archive_path = backup.states / (state["archive_backup_id"] + ".json")
            archived = json.loads(archive_path.read_text(encoding="utf-8"))
            if archived.get("batch_id") == state["batch_id"] and archived.get("status") == "verified":
                state.update(
                    archive_verified=True,
                    archive_file_id=archived.get("drive_file_id"),
                    archive_url=archived.get("web_url"),
                )
        # Durable local evidence survives deletion of the simulation library.
        index = {
            "batch_id": state["batch_id"],
            "backup_id": state["id"],
            "created_at": now(),
            "readable_url": state["readable_url"],
            "local_directory": str(root),
            "archive_verified": bool(state.get("archive_verified")),
            "archive_file_id": state.get("archive_file_id", state.get("drive_file_id")),
            "files": records,
        }
        write_json(root / "drive-index.json", index)
        state.update(
            status="verified",
            readable_verified=True,
            readable_verified_at=now(),
            verified_at=now(),
            readable_files=records,
            samples=inventory["metadata"]["samples"],
            percent=100.0,
        )
        state.pop("error", None)
        write_json(state_path, state)
        return state
    except Exception as exc:
        state.update(status="waiting_readable", error=str(exc), updated_at=now())
        write_json(state_path, state)
        raise
