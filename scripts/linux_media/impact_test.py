"""One real 7-J development acceptance run; never enables the web dispatch gate."""

import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from honeycomb_studio.cloud_archive import ALLOWED, ReleaseArchive
from honeycomb_studio.cloud_github import Github
from honeycomb_studio.data import manifest
from honeycomb_studio.engine import ADAPTERS, Engine
from honeycomb_studio.models import BatchSpec, digest
from honeycomb_studio.store import Store, write_json

from publication import prepare


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    root = Path.cwd()
    output = Path(os.environ["RUNNER_TEMP"]) / "honeycomb-impact"
    output.mkdir()
    endpoint = os.environ["ABAQUS_LICENSE_ENDPOINT"]
    match = re.fullmatch(r"(\d{1,5})@([0-9.]+)", endpoint)
    if not match:
        raise ValueError("Expected private IPv4 license endpoint")
    manager, host = match.groups()
    ipaddress.IPv4Address(host)
    vendor = int(os.environ["ABAQUS_VENDOR_PORT"])
    if not all(1 <= int(p) <= 65535 for p in (manager, vendor)):
        raise ValueError("Invalid private license port")
    print("::add-mask::" + host, flush=True)
    private = Path(os.environ["RUNNER_TEMP"]) / "impact-private"
    private.mkdir(mode=0o700)
    config = private / "abaqus_v6.env"
    config.write_text(
        "license_server_type=FLEXNET\nabaquslm_license_file="
        + repr(endpoint)
        + "\nmp_mode=THREADS\nparallel=DOMAIN\ndomains=4\n"
    )
    os.environ.update(
        HONEYCOMB_IMPACT_ROOT=str(output),
        HONEYCOMB_LICENSE_HOST=host,
        HONEYCOMB_ADAPTERS=str(ADAPTERS),
        HONEYCOMB_LICENSE_CONFIG=str(config),
    )
    wrapper = root / "scripts/linux_media/abaqus_container.py"
    wrapper.chmod(0o755)
    requested = json.loads((root / "examples/reentrant-perimeter-7J.json").read_text(encoding="utf-8"))
    write_json(output / "original-requested-input.json", requested)
    effective = json.loads(json.dumps(requested))
    effective["model"]["cpus"] = 4
    effective.update(runtime_budget_minutes=285)
    spec = BatchSpec.model_validate(effective)
    write_json(
        output / "execution-adjustments.json",
        {
            "cpus": {"requested": requested["model"]["cpus"], "effective": 4},
            "parallel_mode": "threads",
            "domains": 4,
            "render_images": True,
            "notes": "Original model, extraction and rendering settings retained; only CPU allocation and wall-clock budget adjusted.",
            "physics_changed": False,
            "solver_budget_minutes": 285,
        },
    )
    network = "honeycomb-impact"
    subnet = "172.29.231.0/24"
    drop = ["-s", subnet, "-j", "DROP"]
    allow = [
        "-s",
        subnet,
        "-d",
        host,
        "-p",
        "tcp",
        "-m",
        "multiport",
        "--dports",
        manager + "," + str(vendor),
        "-j",
        "ACCEPT",
    ]
    created = dropped = input_dropped = allowed = False
    engine = store = None
    receipt = {
        "kind": "linux-7j-impact-acceptance",
        "workflow_run_id": os.environ["GITHUB_RUN_ID"],
        "source_commit": os.environ["GITHUB_SHA"],
        "solver_success": False,
        "production_runtime_qualified": False,
        "input_hash": digest(effective),
    }
    try:
        run("docker", "network", "create", "--subnet", subnet, network)
        created = True
        run("sudo", "iptables", "-I", "DOCKER-USER", "1", *drop)
        dropped = True
        run("sudo", "iptables", "-I", "INPUT", "1", *drop)
        input_dropped = True
        run("sudo", "iptables", "-I", "DOCKER-USER", "1", *allow)
        allowed = True
        store = Store(output)
        batch = store.create(spec)
        engine = Engine(store, abaqus=str(wrapper), fake=False)
        engine.runtime_fingerprint = "abaqus2020-centos7-4threads-impact-acceptance"
        engine.control(batch["id"], "start")
        engine.start_worker()
        started = time.monotonic()
        while True:
            current = store.list("runs", batch["id"])[0]
            phase = current["status"]
            progress = current.get("progress", {})
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "elapsed_minutes": round((time.monotonic() - started) / 60, 2),
                        "progress": progress,
                    },
                    default=str,
                ),
                flush=True,
            )
            if phase in ("completed", "review", "failed", "interrupted"):
                receipt.update(
                    status=phase,
                    summary=current.get("summary"),
                    quality=current.get("quality"),
                    error=current.get("error"),
                )
                if current["attempts"]:
                    attempt = Path(current["attempts"][-1]["path"])
                    receipt["solver_success"] = (attempt / "solver-complete.json").exists()
                break
            b = store.get("batches", batch["id"])
            if b["status"] == "paused":
                raise RuntimeError(b.get("resource_error", "Batch paused"))
            if time.monotonic() - started > 285 * 60:
                engine.control(batch["id"], "stop")
                raise RuntimeError("Acceptance budget exceeded; full physics duration was not shortened")
            time.sleep(45)
    except Exception as exc:
        receipt["error"] = str(exc).replace(endpoint, "<private-endpoint>").replace(host, "<private-host>")
        raise
    finally:
        if engine is not None:
            engine.shutdown.set()
            engine.wake.set()
            if engine.worker:
                engine.worker.join(timeout=30)
        # Exact label applies only to disposable containers started by this adapter.
        ids = run("docker", "ps", "-aq", "--filter", "label=honeycomb.impact=true").stdout.split()
        if ids:
            run("docker", "rm", "-f", *ids)
        config.unlink(missing_ok=True)
        for chain, rule, exists in [
            ("DOCKER-USER", allow, allowed),
            ("DOCKER-USER", drop, dropped),
            ("INPUT", drop, input_dropped),
        ]:
            if exists:
                run("sudo", "iptables", "-D", chain, *rule)
        if created:
            run("docker", "network", "rm", network)
        if store is not None:
            store.db.close()
        for path in output.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".log", ".dat", ".msg", ".sta", ".txt"):
                text = path.read_text(errors="replace")
                path.write_text(text.replace(endpoint, "<private-endpoint>").replace(host, "<private-host>"))
        for inventory in output.rglob("artifact-manifest.json"):
            metadata = json.loads(inventory.read_text()).get("metadata", {})
            metadata["public_text_redaction"] = (
                "Private license endpoint/host removed; original binary results unchanged"
            )
            manifest(inventory.parent, metadata)
        write_json(output / "impact-receipt.json", receipt)
        Path("output").mkdir(exist_ok=True)
        shutil.copyfile(output / "impact-receipt.json", "output/impact-receipt.json")

    if receipt.get("status") not in ("completed", "review"):
        raise RuntimeError("Impact acceptance did not finish; real diagnostics retained")


def publish():
    """Archive actual outputs, including partial outputs, without certifying them as complete."""
    output = Path(os.environ["RUNNER_TEMP"]) / "honeycomb-impact"
    if not output.exists():
        return
    receipt = json.loads((output / "impact-receipt.json").read_text())
    github = Github(token=os.environ["GITHUB_TOKEN"])
    github.client.timeout = 300
    release = github.repo(
        "POST",
        "/releases",
        {
            "tag_name": "linux-impact-7j-" + os.environ["GITHUB_RUN_ID"],
            "target_commitish": os.environ["GITHUB_SHA"],
            "name": "Linux 7 J re-entrant perimeter test",
            "draft": False,
            "prerelease": True,
            "body": "Real development acceptance test. Read impact-receipt and quality before using data. Incomplete or review results are not certified.",
        },
    )
    archive = ReleaseArchive(github, release["id"])
    # Thousands of small reduction records must not exhaust Release asset limits.
    # Large binaries are hard-linked into this view; only small records are packed.
    with tempfile.TemporaryDirectory(
        dir=os.environ["RUNNER_TEMP"], prefix="impact-publication-"
    ) as temporary:
        publication = Path(temporary)
        prepare(output, publication)
        ALLOWED.add(".tar")
        archive.publish(
            publication, attempt="impact", complete=receipt.get("status") in ("completed", "review")
        )
    print("Results release: " + release["html_url"], flush=True)
    write_json(Path("output/impact-release.json"), {"url": release["html_url"]})


if __name__ == "__main__":
    import sys

    if "--publish" in sys.argv:
        publish()
    else:
        main()
