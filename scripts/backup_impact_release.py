"""Back up retained real impact tables/reports on a fresh runner, without a solver."""

import json
import os
from pathlib import Path

from honeycomb_studio.cloud_drive import backup_readable
from honeycomb_studio.cloud_restore import restore, validate_manifest
from honeycomb_studio.store import Store, write_json


def run(manifest_path: Path, root: Path):
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest)
    # Drive receives readable products. Original CAE/ODB remain in the complete
    # primary GitHub release. Selection is recorded, never called a full restore.
    selected = [f for f in manifest["files"] if Path(f["path"]).suffix in (".json", ".csv", ".parquet", ".pdf")]
    if sum(f["bytes"] for f in selected) > 256 * 1024**2:
        raise ValueError("Readable-product restore exceeds its 256 MiB budget")
    subset = dict(manifest, files=selected, complete=False)
    restored = restore(subset, root, allow_incomplete=True)
    receipt = json.loads((root / "impact-receipt.json").read_text())
    if not receipt.get("solver_success") or receipt.get("workflow_run_id") != "40206764997":
        raise ValueError("Expected the retained real Linux impact receipt")
    store = Store(root)
    try:
        store.reindex()
        batches = store.list("batches")
        if len(batches) != 1:
            raise ValueError("Expected one retained batch")
        backup = backup_readable(store, batches[0]["id"], root.parent / "private-drive")
        result = {
            "kind": "linux-impact-drive-backup",
            "source_run_id": "40206764997",
            "verification_run_id": os.getenv("GITHUB_RUN_ID"),
            "solver_used": False,
            "full_archive_restored": False,
            "selected_files_sha256_verified": len(restored["files"]),
            "research_status": receipt["status"],
            "ml_eligible": False,
            "backup": backup,
        }
        write_json(Path("output/impact-drive-verification.json"), result)
        if not backup.get("readable_verified"):
            raise RuntimeError("Secondary Drive acceptance did not pass; primary Release remains intact")
    finally:
        store.db.close()


if __name__ == "__main__":
    run(Path("output/impact-artifact-manifest.json"), Path(os.environ["RUNNER_TEMP"]) / "impact-readable")
