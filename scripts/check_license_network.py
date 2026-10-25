"""Observe private TCP reachability, explicitly without claiming a solver/license checkout."""

import argparse
import json
import os
import re
import socket
from pathlib import Path


def probe(host, manager_port, vendor_port, denied_ports=(22, 445, 3389), timeout=8):
    outcomes = {}
    for label, port in (("manager", manager_port), ("vendor", vendor_port)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                outcomes[label] = True
        except OSError:
            outcomes[label] = False
    denied = {}
    for port in denied_ports:
        try:
            with socket.create_connection((host, port), timeout=min(timeout, 2)):
                denied[str(port)] = False
        except OSError:
            denied[str(port)] = True
    return {
        "schema_version": "1",
        "kind": "private-license-network-probe",
        "tcp_reachable": outcomes,
        "negative_tcp_checks_blocked": denied,
        "network_passed": all(outcomes.values()) and all(denied.values()),
        "linux_license_checkout": False,
        "solver_executed": False,
        "scope": "TCP only; a blocked negative probe does not identify which network layer denied it.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/license-network.json"))
    args = parser.parse_args()
    match = re.fullmatch(r"([0-9]{1,5})@([A-Za-z0-9.-]+)", os.getenv("ABAQUS_LICENSE_ENDPOINT", ""))
    vendor = os.getenv("ABAQUS_VENDOR_PORT", "")
    if not match or not vendor.isdecimal():
        raise SystemExit("blocked_license: private manager/vendor endpoints are not configured")
    manager_port, host = int(match.group(1)), match.group(2)
    vendor_port = int(vendor)
    if any(not 1 <= p <= 65535 for p in (manager_port, vendor_port)):
        raise SystemExit("blocked_license: invalid private license port")
    result = probe(host, manager_port, vendor_port)
    result["github_run_id"] = os.getenv("GITHUB_RUN_ID")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if not result["network_passed"]:
        raise SystemExit("blocked_license: private reachability or negative network checks failed")


if __name__ == "__main__":
    main()
