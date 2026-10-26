"""Recover original field paths from verified volumes, without overwriting files."""

import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path

from .cloud_restore import destination


def unpack_fields(root):
    root = root.resolve()
    volumes = [root / "field-reductions.tar", *sorted((root / "streamed-fields").glob("*.tar"))]
    count = 0
    for volume in volumes:
        if volume.is_symlink():
            raise ValueError("Field volume is a symlink")
        if not volume.is_file():
            continue
        with tarfile.open(volume, "r") as bundle:
            members = bundle.getmembers()
            names = set()
            for member in members:
                destination(root, member.name)
                if (not member.isfile() or not 0 <= member.size <= 1024**3 or
                        member.name.casefold() in names or not member.name.endswith((".json", ".parquet"))):
                    raise ValueError("Unsafe or duplicate field volume member")
                names.add(member.name.casefold())
            for member in members:
                target = destination(root, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="field-restore-", dir=target.parent) as work:
                    temporary = Path(work) / "payload"
                    source = bundle.extractfile(member)
                    if source is None:
                        raise ValueError("Missing field volume member")
                    digest = hashlib.sha256()
                    with source, temporary.open("wb") as output:
                        remaining = member.size
                        while block := source.read(min(1024**2, remaining + 1)):
                            remaining -= len(block)
                            if remaining < 0:
                                raise ValueError("Field member exceeds declared size")
                            digest.update(block)
                            output.write(block)
                        if remaining:
                            raise ValueError("Truncated field member")
                    if target.exists():
                        with target.open("rb") as existing:
                            if hashlib.file_digest(existing, "sha256").hexdigest() != digest.hexdigest():
                                raise ValueError("Existing field differs; choose a clean restore destination")
                    else:
                        destination(root, member.name)
                        os.link(temporary, target)
                    count += 1
    verified = 0
    for receipt in root.glob("**/remote-fields/*.json"):
        item = json.loads(receipt.read_text(encoding="utf-8"))
        if item.get("kind") != "honeycomb-remote-field" or item.get("verified_upload") is not True:
            raise ValueError("Unverified remote field receipt")
        payload = destination(root, item["storage_path"])
        target = destination(receipt.parent.parent, item["parquet"]["path"])
        if (not payload.is_relative_to(root / "streamed-parquet") or
                not target.is_relative_to(receipt.parent.parent / "fields") or target.suffix != ".parquet"):
            raise ValueError("Remote field receipt escaped its storage namespace")
        with payload.open("rb") as stream:
            if (payload.stat().st_size != item["parquet"]["bytes"] or
                    hashlib.file_digest(stream, "sha256").hexdigest() != item["parquet"]["sha256"]):
                raise ValueError("Restored Parquet failed its original checksum")
        if target.exists():
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != item["parquet"]["sha256"]:
                    raise ValueError("Existing field differs; choose a clean restore destination")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            destination(receipt.parent.parent, item["parquet"]["path"])
            os.link(payload, target)
        verified += 1
    return {"members_restored_or_reused": count, "original_parquet_checksums_verified": verified}
