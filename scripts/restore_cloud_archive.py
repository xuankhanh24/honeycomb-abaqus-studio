"""Restore a downloaded Releases artifact-manifest.json; never run a solver."""

import argparse
import json
from pathlib import Path

from honeycomb_studio.cloud_restore import restore

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    if args.manifest.stat().st_size > 16 * 1024**2:
        parser.error("Manifest exceeds 16 MiB")
    result = restore(
        json.loads(args.manifest.read_text(encoding="utf-8")),
        args.destination,
        allow_incomplete=args.allow_incomplete,
    )
    print(json.dumps(result, indent=2))
