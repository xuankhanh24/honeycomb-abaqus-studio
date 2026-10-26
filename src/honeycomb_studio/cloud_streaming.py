"""Bounded full-field publication; evict Parquet only after verified durable upload."""

import hashlib
import json
import tarfile
from pathlib import Path

from .cloud_archive import MAX_PART
from .cloud_restore import validate_manifest
from .store import write_json


class RollingFields:
    def __init__(self, root, archive, identity, limit=256 * 1024**2):
        if not 1024 <= limit <= MAX_PART:
            raise ValueError("Invalid rolling volume size")
        self.root = Path(root).resolve()
        self.archive, self.identity, self.limit = archive, identity, limit
        self.pending = {}
        self.bytes = 0
        self.index = self.root / "stream-index.json"
        self.records = json.loads(self.index.read_text(encoding="utf-8"))["files"] if self.index.exists() else []
        validate_manifest(self.inventory(), allow_incomplete=True)

    def inventory(self):
        return {"schema_version": "1", "kind": "honeycomb-release-archive", "complete": False,
                "files": self.records, "part_limit_bytes": self.limit}

    def __call__(self, path, reduction):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root) or path.is_symlink():
            raise ValueError("Field path escaped cloud result root")
        if path in self.pending:
            return
        # Reserve TAR headers, PAX metadata and end padding before opening a volume.
        size = path.stat().st_size + 8192
        if size + 10240 > self.limit:
            raise ValueError("One field chunk exceeds the rolling volume budget")
        if self.pending and self.bytes + size + 10240 > self.limit:
            self.flush()
        self.pending[path] = reduction
        self.bytes += size

    def flush(self):
        if not self.pending:
            return
        scratch = self.root / ".cloud-stream"
        scratch.mkdir(exist_ok=True)
        volume = scratch / "pending.tar"
        snapshots = []
        try:
            with tarfile.open(volume, "w", format=tarfile.PAX_FORMAT) as bundle:
                stored = set()
                for path, reduction in self.pending.items():
                    before = path.stat()
                    with path.open("rb") as stream:
                        sha = hashlib.file_digest(stream, "sha256").hexdigest()
                    storage_path = f"streamed-parquet/{sha}/{path.name}"
                    if storage_path not in stored:
                        bundle.add(path, arcname=storage_path, recursive=False)
                        stored.add(storage_path)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError("Field changed during rolling publication")
                    snapshots.append((path, reduction, sha, before.st_size, storage_path))
            size = volume.stat().st_size
            if size > self.limit:
                raise ValueError("Rolling volume exceeded declared disk budget")
            with volume.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            uploaded = self.archive.upload(volume, f"{self.identity}-fields-{sha}.part")
            if uploaded["digest"] != "sha256:" + sha or uploaded["bytes"] != size:
                raise ValueError("Unverified rolling upload; local Parquet retained")
            record = {"path": f"streamed-fields/fields-{sha}.tar", "bytes": size, "sha256": sha,
                      "parts": [{"index": 0, "offset": 0, "sha256": sha, **uploaded}]}
            if not any(r["path"] == record["path"] for r in self.records):
                self.records.append(record)
            validate_manifest(self.inventory(), allow_incomplete=True)
            # Publish the durable reference before any source deletion. A crash
            # can leave duplicate local files, never a missing unreferenced block.
            write_json(self.index, self.inventory())
            for path, reduction, checksum, size, storage_path in snapshots:
                extracted = next(parent for parent in path.parents if parent.name == "extracted")
                receipt = extracted / "remote-fields" / (path.stem + ".json")
                write_json(receipt, {"kind": "honeycomb-remote-field", "verified_upload": True,
                                    "parquet": {"path": path.relative_to(extracted).as_posix(),
                                                "sha256": checksum, "bytes": size},
                                    "storage_path": storage_path, "volume": record, "reduction": reduction})
                # Recheck after network I/O; never discard a concurrently changed file.
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                        raise ValueError("Field changed after upload; local copy retained")
                path.unlink()
                del self.pending[path]
                self.bytes -= size + 8192
        finally:
            volume.unlink(missing_ok=True)
