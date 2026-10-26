"""Accept rolling storage with a labelled subset of already extracted native fields."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import Github
from honeycomb_studio.cloud_restore import restore
from honeycomb_studio.cloud_streaming import RollingFields
from honeycomb_studio.cloud_unpack import unpack_fields
from honeycomb_studio.data import verify_export
from honeycomb_studio.research import field_reduction
from honeycomb_studio.store import write_json

EXPECTED = "b2ddacb8783678d57bf63d6fb96679368f24b3a19afb9b06f20986c20cdcdd56"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    source = Path(os.environ["RUNNER_TEMP"]) / "native-field-source"
    source.mkdir()
    fixture = Path("output/native-field-inputs.tar")
    assert sha(fixture) == EXPECTED
    shutil.copyfile(fixture, source / "field-reductions.tar")
    unpack_fields(source)
    provenance = json.loads((source / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["solver_executed"] is False and len(provenance["files"]) == 6
    root = Path(os.environ["RUNNER_TEMP"]) / "rolling-fields"
    root.mkdir()
    shutil.copytree(source / "extracted", root / "extracted")
    fields = []
    for entry in provenance["files"]:
        assert sha(source / entry["path"]) == entry["sha256"]
        fields.append({**entry["meta"], "rows": entry["rows"]})
    write_json(root / "extracted/inventory.json", {"fields": fields, "export_profile": "native_field_subset"})
    write_json(root / "provenance.json", provenance)
    github = Github(token=os.environ["GITHUB_TOKEN"])
    release = github.repo("POST", "/releases", {
        "tag_name": "rolling-native-fields-" + os.environ["GITHUB_RUN_ID"],
        "target_commitish": os.environ["GITHUB_SHA"], "prerelease": True,
        "name": "Rolling full-field storage acceptance · native Parquet subset",
        "body": "85,394 existing Windows ODB field rows. Transport/export acceptance only; no new solver run. This is a labelled subset, not a complete simulation dataset.",
    })
    archive = ReleaseArchive(github, release["id"])
    limit = max(f["bytes"] for f in provenance["files"]) + 32768
    sink = RollingFields(root, archive, "native-fields", limit=limit)
    for entry in provenance["files"]:
        path = root / entry["path"]
        with pq.ParquetFile(path) as parquet:
            table = parquet.read()
        arrays = {name: np.asarray(table[name].to_pylist(), dtype=float if name in ("data", "mises") else int)
                  for name in ("data", "mises", "instance_index", "node_label", "element_label", "integration_point", "section_point")}
        sink(path, field_reduction(arrays, entry["meta"]))
    sink.flush()
    assert len(sink.records) >= 2
    assert not list((root / "extracted/fields").rglob("*.parquet"))
    before = verify_export(root / "extracted")
    inventory = archive.publish(root, attempt="native-fields", complete=True)
    restored = Path(os.environ["RUNNER_TEMP"]) / "rolling-restored"
    restore(inventory, restored)
    unpacked = unpack_fields(restored)
    after = verify_export(restored / "extracted")
    for entry in provenance["files"]:
        assert sha(restored / entry["path"]) == entry["sha256"] == sha(source / entry["path"])
    assert before["rows"] == after["rows"] == 85394
    receipt = {"kind": "rolling-native-parquet-acceptance", "workflow_run_id": os.environ["GITHUB_RUN_ID"],
               "solver_executed": False, "new_native_full_profile_run": False, "source": provenance["source"],
               "complete_source_field_dataset": False, "source_fixture_sha256": EXPECTED,
               "parquet_files_verified": 6, "source_rows_verified": after["rows"], "volumes": len(sink.records),
               "volume_limit_bytes": limit, "local_parquet_evicted_after_verified_upload": True,
               "all_original_parquet_sha256_restored": True, "restore": unpacked, "release_url": release["html_url"]}
    path = Path("output/rolling-native-fields-verification.json")
    write_json(path, receipt)
    archive.upload(path, path.name)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
