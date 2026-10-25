"""Connect only the installed test container to the owner's two license ports.

No activation file is transferred. This is a tiny runtime test, not entitlement
verification or qualification of full research workloads on Actions.
"""

import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    root = Path.cwd()
    install = json.loads((root / "output/install-probe/install-probe.json").read_text())
    if not install.get("installation_completed") or install.get("odb_import_exit_code") != 0:
        raise SystemExit("Offline installation and ODB import must pass first")
    endpoint = os.environ["ABAQUS_LICENSE_ENDPOINT"]
    match = re.fullmatch(r"(\d{1,5})@([0-9.]+)", endpoint)
    if not match:
        raise SystemExit("Expected the configured private IPv4 license endpoint")
    manager, host = match.groups()
    ipaddress.IPv4Address(host)
    print("::add-mask::" + host, flush=True)
    vendor = int(os.environ["ABAQUS_VENDOR_PORT"])
    if not all(1 <= int(port) <= 65535 for port in (manager, vendor)):
        raise SystemExit("Invalid license port")
    output = root / "output/native-qualification"
    output.mkdir(parents=True, exist_ok=True)
    config = output / "abaqus_v6.env"
    config.write_text("license_server_type=FLEXNET\nabaquslm_license_file=" + repr(endpoint) + "\n")
    run("sudo", "chown", "-R", "1000:1000", str(output))
    network = "honeycomb-license-probe"
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
        str(manager) + "," + str(vendor),
        "-j",
        "ACCEPT",
    ]
    created = dropped = allowed = input_dropped = False
    try:
        run("docker", "network", "create", "--subnet", subnet, network)
        created = True
        run("sudo", "iptables", "-I", "DOCKER-USER", "1", *drop)
        dropped = True
        run("sudo", "iptables", "-I", "INPUT", "1", *drop)
        input_dropped = True
        run("sudo", "iptables", "-I", "DOCKER-USER", "1", *allow)
        allowed = True
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "512",
            "--memory",
            "8g",
            "--dns",
            "127.0.0.1",
            "--add-host",
            "STARK:" + host,
            "--workdir",
            "/qualification",
            "--env",
            "GITHUB_RUN_ID=" + os.environ["GITHUB_RUN_ID"],
            "--mount",
            "type=volume,source=honeycomb-install,target=/opt",
        ]
        for source, target in [
            (root / "scripts/qualify_cloud_runtime.py", "/qualification/qualify_cloud_runtime.py"),
            (
                root / "src/honeycomb_studio/adapters/cloud_probe.py",
                "/qualification/src/honeycomb_studio/adapters/cloud_probe.py",
            ),
        ]:
            command += ["--mount", "type=bind,source=" + str(source) + ",target=" + target + ",readonly"]
        command += [
            "--mount",
            "type=bind,source=" + str(output) + ",target=/qualification/output/native-qualification",
            "honeycomb-install-probe",
            "python3",
            "qualify_cloud_runtime.py",
            "--abaqus",
            "/opt/SIMULIA/Commands/abaqus",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        run("sudo", "chown", "-R", str(os.getuid()) + ":" + str(os.getgid()), str(output))
        (output / "container.log").write_text(completed.stdout + completed.stderr)
        print("Real native probe exit code:", completed.returncode, flush=True)
        if completed.returncode:
            raise RuntimeError("Native probe failed; inspect redacted receipts and stage logs")
    finally:
        run("sudo", "chown", "-R", str(os.getuid()) + ":" + str(os.getgid()), str(output))
        config.unlink(missing_ok=True)
        for path in output.iterdir():
            if path.suffix in (".log", ".msg", ".dat", ".sta", ".json"):
                text = path.read_text(errors="replace").replace(endpoint, "<private-license-endpoint>")
                path.write_text(text.replace(host, "<private-license-host>"))
        if allowed:
            run("sudo", "iptables", "-D", "DOCKER-USER", *allow)
        if dropped:
            run("sudo", "iptables", "-D", "DOCKER-USER", *drop)
        if input_dropped:
            run("sudo", "iptables", "-D", "INPUT", *drop)
        if created:
            run("docker", "network", "rm", network)


if __name__ == "__main__":
    main()
