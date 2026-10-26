"""Interrupt real Release uploads, then resume on a fresh runner without a solver."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import Github
from honeycomb_studio.cloud_restore import restore
from honeycomb_studio.store import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("interrupt", "resume"))
    parser.add_argument("--release-id", type=int)
    args = parser.parse_args()
    github = Github(token=os.environ["GITHUB_TOKEN"])
    if args.mode == "interrupt":
        release = github.repo("POST", "/releases", {
            "tag_name": "archive-recovery-" + os.environ["GITHUB_RUN_ID"],
            "target_commitish": os.environ["GITHUB_SHA"],
            "name": "Archive recovery acceptance · retained real impact report",
            "prerelease": True,
            "body": "Transport acceptance only. Reuses an existing real report; no simulation executed.",
        })
        release_id = release["id"]
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"release_id={release_id}\n")
    else:
        release_id = args.release_id
        if release_id is None:
            raise ValueError("The original release ID is required for recovery")
    source = Path(os.environ["RUNNER_TEMP"]) / "recovery-source"
    source.mkdir()
    data = Path("web/static/reference/linux-perimeter-7j-report.pdf").read_bytes()
    index = json.loads(Path("web/static/reference/index.json").read_text(encoding="utf-8"))
    expected = next(r for r in index if r["id"] == "linux-perimeter-7j")["report"]["sha256"]
    assert hashlib.sha256(data).hexdigest() == expected
    (source / "retained-report.pdf").write_bytes(data)
    archive = ReleaseArchive(github, release_id, limit=256 * 1024)
    if args.mode == "interrupt":
        original = archive.upload
        uploaded = []

        def interrupted(path, name):
            if uploaded:
                raise ConnectionError("Deliberate client interruption after first acknowledged part")
            result = original(path, name)
            uploaded.append(result)
            return result

        archive.upload = interrupted
        try:
            archive.publish(source, attempt="recovery", complete=True)
        except ConnectionError:
            pass
        else:
            raise AssertionError("Interruption did not occur")
        assets = github.repo("GET", f"/releases/{release_id}/assets?per_page=100")
        assert len(assets) == 1 and assets[0]["name"].endswith(".part")
        return
    before = github.repo("GET", f"/releases/{release_id}/assets?per_page=100")
    assert len(before) == 1 and before[0]["name"].endswith(".part")
    manifest = archive.publish(source, attempt="recovery", complete=True)
    after = github.repo("GET", f"/releases/{release_id}/assets?per_page=100")
    assert next(a for a in after if a["name"] == before[0]["name"])["id"] == before[0]["id"]
    restored = Path(os.environ["RUNNER_TEMP"]) / "recovery-restored"
    verification = restore(manifest, restored)
    assert (restored / "retained-report.pdf").read_bytes() == data
    proof = {
        "kind": "cross-runner-release-upload-recovery", "workflow_run_id": os.environ["GITHUB_RUN_ID"],
        "release_id": release_id, "solver_executed": False,
        "partial_upload_before_interruption": len(before), "existing_asset_id_reused": before[0]["id"],
        "complete_manifest_after_recovery": manifest["complete"],
        "all_files_restored_and_verified": len(verification["files"]),
        "report_sha256": expected, "test_part_size_bytes": 256 * 1024,
        "large_odb_upload_recovery_qualified": False,
    }
    path = Path("output/archive-recovery-verification.json")
    write_json(path, proof)
    archive.upload(path, "archive-recovery-verification.json")


if __name__ == "__main__":
    main()
