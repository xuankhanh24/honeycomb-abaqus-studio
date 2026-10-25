"""Scan every reachable Git blob and the working tree without printing secrets."""
import argparse
import json
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    "google_token": re.compile(rb"ya29\.[A-Za-z0-9_-]{30,}"),
    "aws_access_key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "google_client_secret": re.compile(rb'"client_secret"\s*:\s*"[^"\s]{16,}"'),
}
FORBIDDEN = {"session.json", "engine-settings.json", "drive-token.dpapi", ".env", ".env.local"}


def inspect(path: str, data: bytes) -> list[str]:
    name = Path(path).name.lower()
    found = [key for key, pattern in PATTERNS.items() if pattern.search(data)]
    if name in FORBIDDEN or name.endswith((".lic", ".dpapi")):
        found.append("credential_or_activation_file")
    return found


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def audit() -> dict:
    objects = {}
    for line in git("rev-list", "--objects", "--all").decode().splitlines():
        sha, _, path = line.partition(" ")
        objects[sha] = path
    payload = git_batch(list(objects))
    findings = []
    count = 0
    for sha, data in payload:
        count += 1
        for rule in inspect(objects[sha], data):
            findings.append({"scope": "history", "object": sha, "path": objects[sha], "rule": rule})
    paths = git("ls-files", "-c", "-o", "--exclude-standard", "-z").decode().split("\0")
    for name in sorted(set(filter(None, paths))):
        path = Path(name)
        if path.is_file():
            for rule in inspect(name, path.read_bytes()):
                findings.append({"scope": "working_tree", "path": name, "rule": rule})
    return {"passed": not findings, "blobs_scanned": count, "findings": findings,
            "limitations": "Pattern-based scan; not a proof that every possible secret or third-party right was found."}


def git_batch(objects: list[str]):
    raw = subprocess.check_output(["git", "cat-file", "--batch"], input=("\n".join(objects) + "\n").encode())
    cursor = 0
    while cursor < len(raw):
        end = raw.index(b"\n", cursor)
        sha, kind, length = raw[cursor:end].split()
        size = int(length)
        cursor = end + 1
        if kind == b"blob":
            yield sha.decode(), raw[cursor:cursor + size]
        cursor += size + 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)
