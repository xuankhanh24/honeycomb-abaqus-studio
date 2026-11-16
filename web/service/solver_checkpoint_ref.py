"""Lightweight checkpoint admission shared by the web service and native worker."""

import re

from .cloud_restore import public_asset

KIND = "honeycomb-completed-solver-checkpoint-v1"


def validate_reference(reference, input_hash):
    """A recorded checkpoint must fail closed rather than silently rerun FE."""
    if (not isinstance(reference, dict) or reference.get("kind") != KIND
            or reference.get("available") is not True or reference.get("input_hash") != input_hash
            or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("run_input_hash", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("runtime_hash", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(reference.get("source_sha", "")))):
        raise ValueError("Invalid completed-solver checkpoint identity")
    asset = reference.get("manifest", {})
    if (not isinstance(asset, dict) or type(asset.get("asset_id")) is not int
            or type(asset.get("bytes")) is not int or not 0 < asset["bytes"] <= 8 * 1024**2
            or not isinstance(asset.get("url"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(asset.get("digest", "")))):
        raise ValueError("Invalid completed-solver checkpoint manifest reference")
    public_asset(asset.get("url", ""))
