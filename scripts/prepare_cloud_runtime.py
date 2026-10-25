"""Install owner-supplied, checksum-pinned Linux media in an ephemeral runner."""

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path


def main():
    if os.name != "posix" or os.getenv("GITHUB_ACTIONS") != "true":
        raise SystemExit("Only run this installer on an ephemeral Linux Actions runner")
    required = [
        "ABAQUS_LINUX_BUNDLE_URL",
        "ABAQUS_LINUX_BUNDLE_SHA256",
        "ABAQUS_LICENSE_ENDPOINT",
        "ABAQUS_VENDOR_PORT",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise SystemExit("blocked_environment: missing configuration: " + ", ".join(missing))
    url = os.environ["ABAQUS_LINUX_BUNDLE_URL"]
    if not url.startswith("https://"):
        raise SystemExit("Installer media requires HTTPS")
    work = Path(os.environ["RUNNER_TEMP"]) / "abaqus-install"
    work.mkdir()
    before = shutil.disk_usage(work)
    budgets = json.loads(os.environ.get("ABAQUS_DISK_BUDGET_JSON", "{}"))
    keys = ("download", "extracted", "installed", "scratch", "odb", "export", "upload", "reserve")
    if any(not isinstance(budgets.get(k), int) or budgets[k] <= 0 for k in keys):
        raise SystemExit("blocked_environment: a measured byte budget is required for " + ", ".join(keys))
    if before.free < sum(budgets[k] for k in keys):
        raise SystemExit("blocked_environment: actual available disk is below the measured peak budget")
    media = work / "media.tar.gz"
    total = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as source, media.open("wb") as dest:
        while chunk := source.read(4 * 1024**2):
            total += len(chunk)
            if total > budgets["download"]:
                raise SystemExit("Installer download exceeded the declared budget")
            dest.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != os.environ["ABAQUS_LINUX_BUNDLE_SHA256"].lower():
        raise SystemExit("Installer SHA-256 mismatch; no installer was executed")
    target = work / "media"
    with tarfile.open(media) as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > budgets["extracted"] or any(
            m.issym() or m.islnk() or m.isdev() for m in members
        ):
            raise SystemExit("Installer archive exceeds budget or contains unsupported links/devices")
        archive.extractall(target, filter="data")
    recipe = target / "install.sh"
    if not recipe.is_file():
        raise SystemExit("Verified bundle must contain the owner's version-specific install.sh")
    subprocess.run(["bash", str(recipe)], cwd=target, check=True, timeout=3600)
    endpoint = os.environ["ABAQUS_LICENSE_ENDPOINT"]
    import re

    if not re.fullmatch(r"[0-9]{1,5}@[A-Za-z0-9.-]+", endpoint):
        raise SystemExit("Invalid FlexNet endpoint")
    # Client configuration only; the actual activation file remains on the owner's server.
    (Path.home() / "abaqus_v6.env").write_text(
        "license_server_type = 'FLEXNET'\nabaquslm_license_file = " + repr(endpoint) + "\n", encoding="utf-8"
    )
    after = shutil.disk_usage(work)
    Path("output").mkdir(exist_ok=True)
    Path("output/runtime-disk.json").write_text(
        json.dumps({"before_free": before.free, "after_free": after.free, "budget": budgets})
    )


if __name__ == "__main__":
    main()
