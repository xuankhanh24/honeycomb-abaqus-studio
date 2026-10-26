"""Bundle tiny field-reduction files, hard-link large outputs without duplicating ODB."""

import os
import tarfile
from pathlib import Path


def prepare(source: Path, target: Path):
    # Lazy import avoids a cycle when ReleaseArchive prepares its own publication view.
    from .cloud_archive import ALLOWED

    has_reductions = any(source.glob("**/reduced-fields/*.json")) or any(source.glob("**/remote-fields/*.json"))
    reductions = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ALLOWED:
            continue
        if path.suffix.lower() == ".tar" and path.name != "field-reductions.tar":
            continue
        if relative.as_posix() == "RESTORE-README.txt" or (
            has_reductions and relative.as_posix() == "field-reductions.tar"
        ):
            continue
        if any(p in ("cache", "spool", "credentials", "backup-manifests", ".git", ".cloud-stream") for p in relative.parts):
            continue
        if path.name in ("session.json", "engine-settings.json"):
            continue
        if "reduced-fields" in relative.parts or "remote-fields" in relative.parts:
            reductions.append((path, relative))
            continue
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(path, dest)
    if reductions:
        with tarfile.open(target / "field-reductions.tar", "w") as bundle:
            for path, relative in reductions:
                bundle.add(path, arcname=relative.as_posix(), recursive=False)
    (target / "RESTORE-README.txt").write_text(
        "Restore release parts using scripts/restore_cloud_archive.py. Then, if present, "
        "extract field-reductions.tar into the restored root with Python 3.12+ "
        "tarfile.extractall(path=restored_root, filter='data'). It preserves the original "
        "relative paths and bytes of every reduced-field JSON. Original CAE/INP/ODB "
        "and numerical exports are unchanged. Also unpack streamed-fields/*.tar into "
        "the same restored root to recover original full Parquet paths; use "
        "scripts/restore_cloud_archive.py --unpack-fields for exclusive, verified extraction. "
        "Attempt artifact-manifest.json files "
        "refer to the fully restored tree. Research quality remains separate from "
        "transport completeness.\n"
    )
