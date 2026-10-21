"""Immutable local snapshots and resumable Google Drive transfers.

Credentials never enter a data archive. Uploaded binary files are checked using
Drive's MD5 plus size; SHA-256 in the manifest is verified again on restore.
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from .data import archive, checksum
from .store import now, write_input_csv, write_json

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveBackup:
    def __init__(self, store, config_dir: Path):
        self.store = store
        self.config_dir = config_dir
        config_dir.mkdir(parents=True, exist_ok=True)
        self.states = store.root / "backup-manifests"
        self.states.mkdir(parents=True, exist_ok=True)
        self.tasks = queue.Queue()
        self.thread = None
        self.lock = threading.Lock()

    def _save_token(self, text: str):
        import win32crypt  # ty: ignore[unresolved-import] # Provided by pywin32 on Windows.

        blob = win32crypt.CryptProtectData(text.encode(), "Honeycomb Drive OAuth", None, None, None, 0)
        path = self.config_dir / "drive-token.dpapi"
        path.write_bytes(blob)

    def credentials(self):
        import win32crypt  # ty: ignore[unresolved-import] # Provided by pywin32 on Windows.
        from google.oauth2.credentials import Credentials

        path = self.config_dir / "drive-token.dpapi"
        if not path.exists():
            raise ValueError(
                "Chưa đăng nhập Google Drive. Chọn OAuth client JSON và đăng nhập trong Cài đặt."
            )
        _, data = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)
        return Credentials.from_authorized_user_info(json.loads(data), SCOPES)

    def connect(self, client_file: Path):
        from google_auth_oauthlib.flow import InstalledAppFlow

        # The system browser handles consent; no embedded webview or account password.
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent", timeout_seconds=180)
        self._save_token(creds.to_json())
        return {"connected": True}

    def status(self):
        states = []
        for p in sorted(self.states.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                item = json.loads(p.read_text(encoding="utf-8"))
                # A resumable URL is a bearer capability; do not send it to the UI.
                item.pop("session_url", None)
                states.append(item)
            except (OSError, json.JSONDecodeError):
                pass
        return {"connected": (self.config_dir / "drive-token.dpapi").exists(), "transfers": states}

    def enqueue(self, bid, run_id=None):
        self.store.get("batches", bid)
        if not (self.config_dir / "drive-token.dpapi").exists():
            raise ValueError("Chưa đăng nhập Google Drive; dữ liệu local vẫn được giữ nguyên")
        identity = "bk" + uuid.uuid4().hex[:16]
        request = {"id": identity, "batch_id": bid, "run_id": run_id, "status": "queued", "created_at": now()}
        write_json(self.states / (identity + ".json"), request)
        self.tasks.put(("backup", request))
        self.start()
        return {"queued": True, "batch_id": bid, "id": identity}

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True, name="drive-backup")
            self.thread.start()

    def _loop(self):
        while True:
            try:
                action, value = self.tasks.get()
            except queue.Empty:
                continue
            try:
                if action == "backup":
                    self.backup_batch(value["batch_id"], value.get("run_id"), value["id"])
                elif action == "resume":
                    self.upload(Path(value))
            except Exception as exc:
                if action == "backup":
                    path = self.states / (value["id"] + ".json")
                    state = json.loads(path.read_text(encoding="utf-8"))
                    if not state.get("sha256"):
                        state.update(status="waiting_resume", error=str(exc))
                        write_json(path, state)
                self.store.event(
                    value["batch_id"] if action == "backup" else None,
                    None,
                    {"type": "backup_error", "error": str(exc)},
                )
            finally:
                self.tasks.task_done()

    def resume(self, identity: str):
        if not re.fullmatch(r"bk[a-f0-9]{16}", identity):
            raise ValueError("Backup ID không hợp lệ")
        state = self.states / (identity + ".json")
        if not state.exists():
            raise ValueError("Không tìm thấy backup")
        request = json.loads(state.read_text(encoding="utf-8"))
        self.tasks.put(("resume", str(state)) if request.get("sha256") else ("backup", request))
        self.start()
        return {"queued": True}

    def _folder(self, session, name, key, parent=None):
        # Search by app-owned stable keys, not unescaped user-visible names.
        query = (
            "trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has { key='honeycomb_folder' and value='"
            + key
            + "' }"
        )
        response = session.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": query, "fields": "files(id,name)", "pageSize": 100},
            timeout=60,
        )
        response.raise_for_status()
        found = response.json().get("files", [])
        if found:
            return found[0]["id"]
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"honeycomb_folder": key},
        }
        if parent:
            metadata["parents"] = [parent]
        response = session.post(
            "https://www.googleapis.com/drive/v3/files", params={"fields": "id"}, json=metadata, timeout=60
        )
        response.raise_for_status()
        return response.json()["id"]

    def backup_batch(self, bid, run_id=None, identity=None):
        batch = self.store.get("batches", bid)
        runs = self.store.list("runs", bid)
        if run_id is None and any(
            r["status"]
            in {
                "building",
                "checking",
                "solving",
                "extracting",
                "cataloguing",
                "verifying_export",
                "analyzing",
                "rendering",
                "reporting",
                "recovering",
            }
            for r in runs
        ):
            raise ValueError("Chờ lượt đang chạy đóng file trước khi snapshot job")
        identity = identity or "bk" + uuid.uuid4().hex[:16]
        write_json(
            self.states / (identity + ".json"),
            {"id": identity, "batch_id": bid, "run_id": run_id, "status": "preparing", "created_at": now()},
        )
        snapshots = self.store.root / "backups"
        snapshots.mkdir(parents=True, exist_ok=True)
        destination = snapshots / (identity + ".zip")
        source = Path(batch["path"])
        if run_id is not None:
            run = self.store.get("runs", run_id)
            if run["batch_id"] != bid or run["status"] not in ("completed", "review"):
                raise ValueError("Chỉ backup tự động lượt đã hoàn tất")
            source = snapshots / (identity + "-snapshot")
            if source.exists():
                source.rename(snapshots / (identity + "-interrupted-" + str(time.time_ns())))
            source.mkdir()
            single = json.loads(json.dumps(batch))
            single["runs_total"] = 1
            single["spec"].update(model=run["requested"], sampling="grid", axes=[], designs=[])
            write_json(source / "batch.json", single)
            shutil.copytree(Path(run["path"]), source / "runs" / run["id"])
        self.store.snapshot(source / "catalog-snapshot.sqlite")
        archive(source, destination)
        if run_id is not None:
            resolved_source = source.resolve()
            if (
                resolved_source.parent != snapshots.resolve()
                or resolved_source.name != identity + "-snapshot"
            ):
                raise ValueError("Temporary snapshot escaped backup workspace")
            shutil.rmtree(resolved_source)
        state = {
            "id": identity,
            "batch_id": bid,
            "run_id": run_id,
            "name": batch["name"],
            "file": str(destination),
            "bytes": destination.stat().st_size,
            "sha256": checksum(destination),
            "md5": checksum(destination, "md5"),
            "status": "prepared",
            "offset": 0,
            "created_at": now(),
        }
        path = self.states / (identity + ".json")
        write_json(path, state)
        return self.upload(path)

    def upload(self, state_path: Path):
        from google.auth.transport.requests import AuthorizedSession

        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") == "verified":
            return state
        source = Path(state["file"])
        if (
            not source.exists()
            or source.stat().st_size != state["bytes"]
            or checksum(source) != state["sha256"]
        ):
            raise ValueError("File backup thay đổi hoặc mất; không tiếp tục upload")
        creds = self.credentials()
        session = AuthorizedSession(creds)
        base = "https://www.googleapis.com/drive/v3/files"
        try:
            if not state.get("session_url"):
                root_folder = self._folder(session, "Honeycomb Abaqus Studio", "root")
                parent = self._folder(
                    session,
                    state.get("name", state["batch_id"]) + " [" + state["batch_id"] + "]",
                    state["batch_id"],
                    root_folder,
                )
                response = session.post(
                    "https://www.googleapis.com/upload/drive/v3/files",
                    params={"uploadType": "resumable", "fields": "id,size,md5Checksum,webViewLink"},
                    json={
                        "name": re.sub(r"[/\\]", "_", state.get("name", "Honeycomb"))[:120]
                        + "-"
                        + state["id"]
                        + ".zip",
                        "parents": [parent],
                        "description": "Honeycomb job " + state["batch_id"] + "; SHA256 " + state["sha256"],
                        "appProperties": {"honeycomb_backup": state["id"]},
                    },
                    headers={
                        "X-Upload-Content-Type": "application/zip",
                        "X-Upload-Content-Length": str(state["bytes"]),
                    },
                    timeout=60,
                )
                response.raise_for_status()
                state["session_url"] = response.headers["Location"]
                write_json(state_path, state)
            query = session.put(
                state["session_url"],
                headers={"Content-Length": "0", "Content-Range": "bytes */%d" % state["bytes"]},
                data=b"",
                timeout=60,
            )
            if query.status_code in (200, 201):
                info = query.json()
                offset = state["bytes"]
            elif query.status_code == 308:
                offset = (
                    int(query.headers.get("Range", "bytes=0--1").split("-")[-1]) + 1
                    if "Range" in query.headers
                    else 0
                )
            elif query.status_code in (404, 410):
                state.pop("session_url", None)
                state.update(status="session_expired", offset=0)
                write_json(state_path, state)
                raise RuntimeError("Phiên upload đã hết hạn; bấm tiếp tục để tạo phiên mới")
            else:
                query.raise_for_status()
            state["status"] = "uploading"
            started = time.monotonic()
            initial = offset
            with source.open("rb") as f:
                while offset < state["bytes"]:
                    f.seek(offset)
                    block = f.read(8 * 1024 * 1024)
                    end = offset + len(block) - 1
                    for retry in range(6):
                        try:
                            response = session.put(
                                state["session_url"],
                                data=block,
                                headers={
                                    "Content-Length": str(len(block)),
                                    "Content-Range": "bytes %d-%d/%d" % (offset, end, state["bytes"]),
                                },
                                timeout=120,
                            )
                            if response.status_code in (429, 500, 502, 503, 504):
                                raise RuntimeError("Drive tạm thời: " + str(response.status_code))
                            if response.status_code == 308:
                                offset = int(response.headers["Range"].split("-")[-1]) + 1
                            else:
                                response.raise_for_status()
                                info = response.json()
                                offset = state["bytes"]
                            break
                        except Exception:
                            if retry == 5:
                                raise
                            time.sleep(min(30, 2**retry))
                            # A lost response may still have committed bytes at Drive.
                            probe = session.put(
                                state["session_url"],
                                headers={
                                    "Content-Length": "0",
                                    "Content-Range": "bytes */%d" % state["bytes"],
                                },
                                data=b"",
                                timeout=60,
                            )
                            if probe.status_code in (200, 201):
                                info = probe.json()
                                offset = state["bytes"]
                                break
                            if probe.status_code == 308:
                                acknowledged = (
                                    int(probe.headers["Range"].split("-")[-1]) + 1
                                    if "Range" in probe.headers
                                    else 0
                                )
                                if acknowledged != offset:
                                    offset = acknowledged
                                    break
                            else:
                                probe.raise_for_status()
                    elapsed = max(0.01, time.monotonic() - started)
                    speed = (offset - initial) / elapsed
                    state.update(
                        offset=offset,
                        percent=offset / state["bytes"] * 100,
                        speed_bytes_s=speed,
                        eta_seconds=(state["bytes"] - offset) / speed if speed > 0 else None,
                    )
                    write_json(state_path, state)
            remote = session.get(
                base + "/" + info["id"], params={"fields": "id,size,md5Checksum,webViewLink"}, timeout=60
            )
            remote.raise_for_status()
            info = remote.json()
            if int(info["size"]) != state["bytes"] or info.get("md5Checksum") != state["md5"]:
                raise ValueError("Drive checksum hoặc kích thước không khớp")
            state.update(
                status="verified",
                drive_file_id=info["id"],
                web_url=info.get("webViewLink"),
                verified_at=now(),
                percent=100.0,
            )
            state.pop("session_url", None)
            state.pop("error", None)
            write_json(state_path, state)
            self._save_token(creds.to_json())
            return state
        except Exception as exc:
            message = str(exc).replace(state.get("session_url", "__no_session__"), "[resumable session]")
            state.update(status="waiting_retry", error=message)
            write_json(state_path, state)
            raise RuntimeError(message) from None
        finally:
            session.close()

    def restore_drive(self, file_id: str, expected_sha256: str):
        from google.auth.transport.requests import AuthorizedSession

        if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise ValueError("Cần SHA-256 từ manifest backup")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise ValueError("Drive file ID không hợp lệ")
        staging = self.store.root / "backups"
        staging.mkdir(exist_ok=True)
        target = staging / ("download-" + uuid.uuid4().hex + ".zip")
        with AuthorizedSession(self.credentials()) as session:
            response = session.get(
                "https://www.googleapis.com/drive/v3/files/" + file_id,
                params={"alt": "media"},
                stream=True,
                timeout=120,
            )
            response.raise_for_status()
            with target.open("wb") as f:
                for block in response.iter_content(8 * 1024 * 1024):
                    f.write(block)
        if checksum(target) != expected_sha256:
            raise ValueError("SHA-256 gói tải về không khớp")
        return self.restore_local(target)

    def restore_local(self, archive_path: Path):
        target = self.store.root / "restores" / ("restore-" + uuid.uuid4().hex[:12])
        target.mkdir(parents=True)
        with zipfile.ZipFile(archive_path) as z:
            if sum(i.file_size for i in z.infolist()) * 2 > shutil.disk_usage(self.store.root).free - 1024**3:
                raise ValueError("Không đủ chỗ cho kiểm tra và đăng ký bản khôi phục")
            for info in z.infolist():
                resolved = (target / info.filename).resolve()
                if not resolved.is_relative_to(target.resolve()):
                    raise ValueError("ZIP chứa đường dẫn ngoài thư mục khôi phục")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Không chấp nhận symlink trong gói backup")
            z.extractall(target)
        meta = json.loads((target / "artifact-manifest.json").read_text(encoding="utf-8"))
        declared = {i["path"] for i in meta["files"]}
        actual = {
            p.relative_to(target).as_posix()
            for p in target.rglob("*")
            if p.is_file() and p != target / "artifact-manifest.json"
        }
        if declared != actual:
            raise ValueError("Manifest không bao phủ chính xác mọi file trong gói")
        for item in meta["files"]:
            path = (target / item["path"]).resolve()
            if (
                not path.is_relative_to(target.resolve())
                or not path.is_file()
                or path.stat().st_size != item["bytes"]
                or checksum(path) != item["sha256"]
            ):
                raise ValueError("Kiểm tra file khôi phục không đạt: " + item["path"])
        # Copy into a new project/batch identity. Source manifests remain archived.
        old = json.loads((target / "batch.json").read_text(encoding="utf-8"))
        from .models import BatchSpec

        new = self.store.create(BatchSpec.model_validate(old["spec"]))
        destination = Path(new["path"])
        old_runs = sorted(target.glob("runs/*/run.json"))
        fresh = self.store.list("runs", new["id"])
        for file, new_run in zip(old_runs, fresh, strict=False):
            restored = json.loads(file.read_text(encoding="utf-8"))
            source = file.parent
            shutil.copytree(source / "attempts", Path(new_run["path"]) / "attempts", dirs_exist_ok=True)
            new_run.update(
                status=restored["status"],
                summary=restored.get("summary"),
                quality=restored.get("quality"),
                restored_from=restored["id"],
                **{
                    key: restored[key]
                    for key in ("requested", "resolved", "input_hash", "design_id", "changes")
                },
            )
            for kind, key in (("requested-input", "requested"), ("resolved-input", "resolved")):
                write_json(Path(new_run["path"]) / (kind + ".json"), new_run[key])
                write_input_csv(Path(new_run["path"]) / (kind + ".csv"), new_run[key])
            new_run["attempts"] = restored["attempts"]
            for attempt in new_run["attempts"]:
                attempt["path"] = str(Path(new_run["path"]) / "attempts" / ("%03d" % attempt["number"]))
                attempt["process"] = None
            if new_run["status"] not in ("completed", "review", "failed"):
                new_run["status"] = "interrupted"
            self.store.save("runs", new_run)
        new.update(status="restored", restored_from=old["id"])
        self.store.save("batches", new)
        self.store.refresh_library_index()
        return {"batch_id": new["id"], "path": str(destination), "verified": True}
