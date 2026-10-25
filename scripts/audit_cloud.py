"""Measure the runner; explicitly distinguish hardware facts from Abaqus readiness."""
import argparse
import datetime
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def disk_report(path: str) -> dict:
    resolved = Path(path).resolve()
    usage = shutil.disk_usage(resolved)
    return {"path": str(resolved), "total_bytes": usage.total,
            "free_bytes": usage.free, "used_bytes": usage.used}


def filesystems() -> list[dict]:
    if platform.system() != "Linux":
        return [{"path": str(Path.cwd().anchor), "type": "unknown"}]
    result = []
    for line in Path("/proc/mounts").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] in ("/", "/mnt", "/tmp", "/home", "/home/runner/work"):
            result.append({"device": fields[0], "path": fields[1], "type": fields[2],
                           "ram_backed": fields[2] in ("tmpfs", "ramfs")})
    return result


def measure() -> dict:
    mounts = filesystems()
    candidates = [str(Path.cwd()), os.environ.get("RUNNER_TEMP", "/tmp"), "/mnt"]
    disks = [disk_report(p) for p in dict.fromkeys(candidates) if Path(p).exists()]
    for disk in disks:
        parents = [m for m in mounts if disk["path"] == m["path"] or disk["path"].startswith(m["path"].rstrip("/") + "/")]
        mount = max(parents, key=lambda m: len(m["path"]), default={})
        disk.update(filesystem=mount.get("type", "unknown"), ram_backed=mount.get("ram_backed", False))
    usable = [d for d in disks if not d["ram_backed"]]
    memory = {}
    if platform.system() == "Linux":
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in ("MemTotal", "MemAvailable", "SwapTotal"):
                memory[key + "_bytes"] = int(value.split()[0]) * 1024
    return {"measured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "platform": platform.platform(), "architecture": platform.machine(),
            "python": platform.python_version(), "cpus": os.cpu_count(), "memory": memory,
            "image": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"), "mounts": mounts, "disks": disks,
            "scratch_candidate": max(usable, key=lambda d: d["free_bytes"])["path"] if usable else None,
            "disk_budget": {"measured": False, "reason": "Installer, installed runtime, scratch, ODB and export peaks must be measured with licensed Linux media."}}


def readiness() -> dict:
    # Hardware observation alone must never qualify a runtime or license.
    return {"ready_for_full_simulation": False, "gates": [
        {"status": "blocked_environment", "reason": "No checksum-verified Linux Abaqus runtime has completed qualification."},
        {"status": "blocked_license", "reason": "Linux CAE and Explicit checkout against the owner's server has not been demonstrated."},
        {"status": "blocked_platform_policy", "reason": "Full web-submitted research workloads require confirmed GitHub Actions usage eligibility."},
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = measure()
    result = readiness()
    for name, value in (("environment.json", report), ("feasibility.json", result)):
        (args.output / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    if platform.system() == "Linux":
        subprocess.run(["df", "-hT"], check=True)
        subprocess.run(["lsblk", "-o", "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS"], check=True)
    lines = ["# Ubuntu runner audit", "", f"CPU: {report['cpus']}",
             f"RAM: {report['memory'].get('MemTotal_bytes', 0) / 1024**3:.2f} GiB", "",
             "| Path | Total GiB | Free GiB | Filesystem | RAM-backed |", "|---|---:|---:|---|---|"]
    for disk in report["disks"]:
        lines.append(f"| {disk['path']} | {disk['total_bytes']/1024**3:.2f} | {disk['free_bytes']/1024**3:.2f} | {disk['filesystem']} | {disk['ram_backed']} |")
    lines.extend(["", "**Abaqus is not yet qualified. A successful hardware audit is not a successful simulation.**", ""])
    lines.extend(f"- `{g['status']}`: {g['reason']}" for g in result["gates"])
    summary = "\n".join(lines) + "\n"
    (args.output / "SUMMARY.md").write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(summary)
    print(summary)


if __name__ == "__main__":
    main()
