"""Opt-in, live Drive acceptance with a clearly labelled synthetic job.

Requires interactive desktop OAuth beforehand. Leaves both source and restored
data intact. Stops the client after a real 8 MiB chunk and resumes the same
Google upload session; never changes the machine's network connection.
"""

import argparse
import json
import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession

from honeycomb_studio.backup import DriveBackup
from honeycomb_studio.data import checksum
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec
from honeycomb_studio.store import Store, now, write_json


class ClientInterrupted(BaseException):
    """Simulate process interruption, outside upload's network retry handler."""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    store = Store(args.root)
    backup = DriveBackup(store, Path(os.environ["LOCALAPPDATA"]) / "HoneycombStudio")
    with AuthorizedSession(backup.credentials()) as session:
        response = session.get(
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user(emailAddress),storageQuota"},
            timeout=60,
        )
        response.raise_for_status()
        info = response.json()
    if info["user"]["emailAddress"].lower() != args.account.lower():
        raise ValueError("Connected Drive account differs from the requested account")
    quota = info.get("storageQuota", {})
    if "limit" in quota and int(quota["limit"]) - int(quota.get("usage", 0)) < 64 * 1024**2:
        raise ValueError("Need at least 64 MiB free Drive quota for acceptance")
    batch = store.create(
        BatchSpec(
            name="Drive acceptance - SYNTHETIC, NOT RESEARCH",
            notes="Fake solver fixture; excluded from ML. Live upload/resume/restore acceptance.",
            render_images=False,
        )
    )
    run = store.list("runs", batch["id"])[0]
    Engine(store, fake=True)._execute(run, batch)
    run = store.get("runs", run["id"])
    if run["status"] != "completed" or run["quality"]["ml_eligible"]:
        raise ValueError("Synthetic run must complete and remain ineligible for ML")
    fixture = Path(batch["path"]) / "resumable-test-payload.bin"
    with fixture.open("wb") as stream:
        for _ in range(24):
            stream.write(os.urandom(1024**2))
    original_put = AuthorizedSession.put
    accepted_chunks = []

    def interrupt_after_chunk(session, url, **kwargs):
        result = original_put(session, url, **kwargs)
        if kwargs.get("data") and result.status_code == 308:
            accepted_chunks.append(result.headers.get("Range"))
            raise ClientInterrupted()
        return result

    AuthorizedSession.put = interrupt_after_chunk
    try:
        backup.backup_batch(batch["id"])
    except ClientInterrupted:
        pass
    finally:
        AuthorizedSession.put = original_put
    state_path = next(
        p for p in backup.states.glob("*.json") if json.loads(p.read_text())["batch_id"] == batch["id"]
    )
    before = json.loads(state_path.read_text())
    assert accepted_chunks and before.get("session_url")
    resumed_ranges = []

    def observe_resume(session, url, **kwargs):
        if kwargs.get("data"):
            resumed_ranges.append(kwargs["headers"]["Content-Range"])
        return original_put(session, url, **kwargs)

    AuthorizedSession.put = observe_resume
    try:
        verified = backup.upload(state_path)
    finally:
        AuthorizedSession.put = original_put
    assert verified["status"] == "verified"
    assert resumed_ranges[0].startswith("bytes 8388608-")
    restored = backup.restore_drive(verified["drive_file_id"], verified["sha256"])
    restored_payload = Path(restored["path"])
    # The immutable restored archive retains files outside run folders as well.
    extracted_payload = next(
        p
        for p in (store.root / "restores").glob("*/resumable-test-payload.bin")
        if json.loads((p.parent / "batch.json").read_text())["id"] == batch["id"]
    )
    assert checksum(fixture) == checksum(extracted_payload)
    restored_run = store.list("runs", restored["batch_id"])[0]
    assert restored_run["input_hash"] == run["input_hash"]
    assert restored_run.get("summary") == run.get("summary")
    assert not restored_run["quality"]["ml_eligible"]
    evidence = {
        "created_at": now(),
        "synthetic_fixture": True,
        "account_matches_requested": True,
        "source_batch": batch["id"],
        "bytes": verified["bytes"],
        "sha256": verified["sha256"],
        "drive_file_id": verified["drive_file_id"],
        "web_url": verified.get("web_url"),
        "interruption": "client interrupted after Drive acknowledged a real 8 MiB chunk",
        "first_resumed_range": resumed_ranges[0],
        "upload_size_md5_verified": True,
        "download_sha256_verified": True,
        "restored": restored,
        "restored_catalog_path_exists": restored_payload.exists(),
        "input_and_output_preserved": True,
        "payload_checksum_matches": True,
        "ml_eligible": False,
    }
    write_json(store.root / "drive-acceptance.json", evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
