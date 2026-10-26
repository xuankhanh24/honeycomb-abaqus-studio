"""Download and inventory a third-party Linux media candidate; execute no media.

Only metadata leaves the ephemeral runner. This does not establish publisher
authenticity, installation success, license entitlement or solver acceptance.
"""

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeycomb_studio.actions_log import get_actions_log

BASE = "https://dl1.softgozar.com/Files/Software/DS_SIMULIA_Suite_2020_Linux64_Softgozar.com.part"
SIZES = [2147483648] * 4 + [1211173011]
ISO_LIMIT = 16 * 1024**3


def download(index, directory):
    url = BASE + str(index + 1) + ".rar?1605356"
    path = directory / f"media.part{index + 1}.rar"
    digest = hashlib.sha256()
    count = 0
    started = last = time.monotonic()
    logger = get_actions_log()
    transfer = logger.transfer(f"Tải bộ cài · phần {index + 1}/5", SIZES[index]) if logger else None
    with urllib.request.urlopen(url, timeout=90) as response, path.open("xb") as stream:
        if response.status != 200:
            raise ValueError("Expected a complete archive volume")
        while block := response.read(4 * 1024**2):
            count += len(block)
            if count > SIZES[index]:
                raise ValueError("Archive volume exceeds its observed Content-Length")
            stream.write(block)
            digest.update(block)
            if transfer:
                transfer.advance(len(block))
            elif time.monotonic() - last > 30:
                print(f"part {index + 1}: {count}/{SIZES[index]} bytes", flush=True)
                last = time.monotonic()
    if count != SIZES[index]:
        raise ValueError("Truncated archive volume")
    if transfer:
        transfer.report("Kích thước đủ · đã tính SHA-256; chờ đối chiếu ISO đã ghim", force=True)
    print(f"part {index + 1}: downloaded and hashed", flush=True)
    return {"url": url, "bytes": count, "sha256": digest.hexdigest(), "seconds": time.monotonic() - started}


def main():
    if os.name != "posix" or os.getenv("GITHUB_ACTIONS") != "true":
        raise SystemExit("Use an ephemeral Linux inspection runner")
    root = Path(os.environ["RUNNER_TEMP"]) / "abaqus-media-inspection"
    root.mkdir()
    output = Path("output/media-inspection")
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "kind": "third-party-linux-media-inspection",
        "source_page": "https://www.softgozar.com/ds-simulia-abaqus_/",
        "release_claimed_by_mirror": "2020 Linux64",
        "publisher_authenticity_verified": False,
        "installer_executed": False,
        "activation_tools_executed": False,
        "license_checked_out": False,
        "solver_executed": False,
        "github_run_id": os.environ["GITHUB_RUN_ID"],
    }
    try:
        get_actions_log()  # Initialize before parallel downloads.
        before = shutil.disk_usage(root)
        report["disk_before"] = {"total": before.total, "free": before.free}
        if before.free < sum(SIZES) + ISO_LIMIT + 4 * 1024**3:
            raise ValueError("Not enough measured free disk for download, bounded ISO and reserve")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            report["volumes"] = list(pool.map(lambda i: download(i, root), range(5)))
        archive = str(root / "media.part1.rar")
        listing = subprocess.run(
            ["unrar", "lb", "-pwww.softgozar.com", archive],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout.splitlines()
        report["archive_entries"] = listing[:2000]
        iso_names = [name for name in listing if name.lower().endswith(".iso")]
        if len(iso_names) != 1:
            raise ValueError("Expected exactly one separately packaged ISO")
        name = iso_names[0]
        if any(p in ("..", "crack") for p in re.split(r"[/\\]", name.lower())) or ":" in name:
            raise ValueError("Unsafe ISO entry")
        technical = subprocess.run(
            ["unrar", "lt", "-pwww.softgozar.com", archive, name],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout
        sizes = [int(n) for n in re.findall(r"^\s*Size:\s*(\d+)\s*$", technical, re.M)]
        if not sizes or max(sizes) > ISO_LIMIT:
            raise ValueError("ISO size is absent or exceeds the inspection disk budget")
        destination = root / "iso"
        destination.mkdir()
        # e extracts only the selected ISO with paths discarded. No activation files.
        subprocess.run(
            ["unrar", "e", "-idq", "-y", "-o-", "-pwww.softgozar.com", archive, name, str(destination) + "/"],
            check=True,
            timeout=1800,
        )
        iso = destination / re.split(r"[/\\]", name)[-1]
        if not iso.is_file() or iso.is_symlink() or iso.stat().st_size > ISO_LIMIT:
            raise ValueError("ISO extraction did not produce the bounded regular file")
        with iso.open("rb") as stream:
            iso_digest = hashlib.sha256()
            for block in iter(lambda: stream.read(4 * 1024**2), b""):
                iso_digest.update(block)
            report["iso"] = {
                "name": iso.name,
                "bytes": iso.stat().st_size,
                "sha256": iso_digest.hexdigest(),
            }
        inventory = subprocess.run(
            ["7z", "l", "-slt", str(iso)],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout
        entries = re.findall(r"^Path = (.+)$", inventory, re.M)
        report["linux_installer_entries"] = [
            p for p in entries if "Linux64" in p and (p.endswith("StartTUI.sh") or p.endswith("StartGUI.sh"))
        ]
        report["passed_media_inventory"] = bool(report["linux_installer_entries"])
        if not report["passed_media_inventory"]:
            raise ValueError("No Linux64 installer entry in ISO")
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["disk_after_free"] = shutil.disk_usage(root).free
        (output / "inspection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
