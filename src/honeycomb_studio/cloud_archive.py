"""Bounded 1-GiB release volumes with immutable names and a final completeness manifest."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from .cloud_github import Github

MAX_PART = 1024**3
ALLOWED = {
    ".json",
    ".csv",
    ".parquet",
    ".pdf",
    ".docx",
    ".png",
    ".gif",
    ".inp",
    ".cae",
    ".odb",
    ".sta",
    ".dat",
    ".msg",
    ".log",
    ".txt",
}


def parts(path: Path, temporary: Path, limit=MAX_PART):
    """Keep only one bounded part on disk; hash both each part and the original file."""
    if not 1 <= limit <= MAX_PART:
        raise ValueError("Part size must be between 1 byte and 1 GiB")
    whole = hashlib.sha256()
    offset = 0
    index = 0
    with path.open("rb") as source:
        while True:
            digest = hashlib.sha256()
            count = 0
            chunk_path = temporary / "upload.part"
            with chunk_path.open("wb") as dest:
                while count < limit:
                    chunk = source.read(min(4 * 1024**2, limit - count))
                    if not chunk:
                        break
                    dest.write(chunk)
                    digest.update(chunk)
                    whole.update(chunk)
                    count += len(chunk)
            if not count:
                chunk_path.unlink()
                break
            yield {
                "index": index,
                "offset": offset,
                "bytes": count,
                "sha256": digest.hexdigest(),
                "path": chunk_path,
                "file_sha256_so_far": whole.hexdigest(),
            }
            offset += count
            index += 1
            chunk_path.unlink(missing_ok=True)


class ReleaseArchive:
    def __init__(self, github: Github, release_id: int, limit=MAX_PART):
        self.github = github
        self.release_id = release_id
        self.limit = limit

    def upload(self, path: Path, name: str):
        assets = self.github.repo("GET", f"/releases/{self.release_id}/assets?per_page=100")
        page = 2
        while len(assets) == (page - 1) * 100:
            extra = self.github.repo("GET", f"/releases/{self.release_id}/assets?per_page=100&page={page}")
            assets.extend(extra)
            if len(extra) < 100:
                break
            page += 1
        with path.open("rb") as source:
            expected = "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
        for asset in assets:
            if asset["name"] == name:
                if asset.get("digest") != expected or asset["size"] != path.stat().st_size:
                    raise ValueError("An existing release asset failed digest verification")
                return {"url": asset["browser_download_url"], "digest": expected, "bytes": asset["size"]}
        if len(assets) >= 1000:
            raise ValueError(
                "Release asset limit reached; preserve incomplete manifest and use another release"
            )
        headers = {
            "Authorization": "Bearer " + str(self.github.access_token()),
            "Content-Type": "application/octet-stream",
            "Content-Length": str(path.stat().st_size),
            "Accept": "application/vnd.github+json",
        }
        from .cloud_github import REPOSITORY

        with path.open("rb") as stream:
            response = self.github.client.post(
                f"https://uploads.github.com/repos/{REPOSITORY}/releases/{self.release_id}/assets",
                params={"name": name},
                headers=headers,
                content=stream,
            )
        response.raise_for_status()
        asset = response.json()
        if asset.get("digest") != expected or asset["size"] != path.stat().st_size:
            raise ValueError("GitHub did not confirm the uploaded asset SHA-256 and size")
        return {"url": asset["browser_download_url"], "digest": expected, "bytes": asset["size"]}

    def publish(self, root: Path, *, attempt: str, complete: bool, checkpoint: str | None = None):
        files = []
        root = root.resolve()
        with tempfile.TemporaryDirectory(prefix="honeycomb-upload-") as temp:
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root)
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ALLOWED:
                    continue
                if any(
                    p in ("cache", "spool", "credentials", "backup-manifests", ".git") for p in relative.parts
                ):
                    continue
                if path.name in ("session.json", "engine-settings.json"):
                    continue
                before = path.stat()
                record = {
                    "path": relative.as_posix(),
                    "bytes": before.st_size,
                    "parts": [],
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }
                for part in parts(path, Path(temp), self.limit):
                    uploaded = self.upload(part["path"], f"{attempt}-{part['sha256']}.part")
                    record["parts"].append(
                        {k: part[k] for k in ("index", "offset", "bytes", "sha256")} | uploaded
                    )
                    record["sha256"] = part["file_sha256_so_far"]
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Source changed during archival; no complete manifest will be published")
                files.append(record)
            manifest = {
                "schema_version": "1",
                "kind": "honeycomb-release-archive",
                "attempt": attempt,
                "complete": complete,
                "files": files,
                "part_limit_bytes": self.limit,
            }
            path = Path(temp) / "artifact-manifest.json"
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
            suffix = f"checkpoint-{checkpoint}-" if checkpoint else ""
            self.upload(path, f"{attempt}-{suffix}artifact-manifest.json")
        return manifest
