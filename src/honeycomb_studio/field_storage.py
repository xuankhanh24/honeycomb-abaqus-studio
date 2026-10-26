"""Read lightweight receipts for full fields moved to verified cloud volumes."""

import hashlib
import json


def remote_reductions(directory):
    for path in sorted((directory / "remote-fields").glob("*.json")):
        from .cloud_restore import validate_manifest

        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("kind") != "honeycomb-remote-field" or item.get("verified_upload") is not True:
            raise ValueError("Unverified remote field receipt")
        volume = item["volume"]
        validate_manifest({"schema_version": "1", "kind": "honeycomb-release-archive",
                           "complete": True, "files": [volume]})
        relative = item["parquet"]["path"]
        local = (directory / relative).resolve()
        if not local.is_relative_to((directory / "fields").resolve()):
            raise ValueError("Remote field receipt escaped fields directory")
        if local.exists():
            with local.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != item["parquet"]["sha256"]:
                    raise ValueError("Local/remote field checksum mismatch")
            continue  # Crash after receipt but before unlink: count the local file once.
        yield item["reduction"]
