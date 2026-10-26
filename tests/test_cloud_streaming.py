import hashlib
import tarfile
from pathlib import Path

import httpx
import numpy as np
import pyarrow.parquet as pq
import pytest

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import REPOSITORY
from honeycomb_studio.cloud_restore import restore
from honeycomb_studio.cloud_streaming import RollingFields
from honeycomb_studio.cloud_unpack import unpack_fields
from honeycomb_studio.data import consume_spool, verify_export
from honeycomb_studio.field_storage import remote_reductions
from honeycomb_studio.store import write_json


class MemoryArchive(ReleaseArchive):
    def __init__(self):
        self.limit = 32768
        self.payloads = {}
        self.bad_digest = False

    def upload(self, path, name):
        data = path.read_bytes()
        url = f"https://github.com/{REPOSITORY}/releases/download/stream-test/{name}"
        self.payloads[url] = data
        return {"url": url, "bytes": len(data),
                "digest": "sha256:" + ("0" * 64 if self.bad_digest else hashlib.sha256(data).hexdigest())}


def fixture(root, frames=5):
    extracted = root / "projects/p/batches/b/runs/r/attempts/001/extracted"
    spool = extracted / "spool"
    spool.mkdir(parents=True)
    fields = []
    for frame in range(frames):
        arrays = {"data": np.array([[1., 2., frame + 3.], [0., 4., 0.]]),
                  "mises": np.array([np.nan, np.nan]), "instance_index": np.array([0, 0]),
                  "node_label": np.array([11, 22]), "element_label": np.array([-1, -1]),
                  "integration_point": np.array([-1, -1]), "section_point": np.array([-1, -1])}
        np.savez(spool / f"{frame}.npz", **arrays)
        meta = {"npz": f"{frame}.npz", "sequence": frame, "kind": "field", "step": "Impact",
                "frame": frame, "time_s": frame * .001, "field": "U", "instances": ["TOP-1"],
                "components": ["U1", "U2", "U3"]}
        write_json(spool / f"{frame}.ready", meta)
        fields.append({**meta, "rows": 2})
    write_json(extracted / "inventory.json", {"fields": fields, "export_profile": "full_fields"})
    return extracted


def test_rolling_full_fields_restore_original_rows_labels_and_paths_without_local_copies(tmp_path):
    root = tmp_path / "source"
    extracted = fixture(root)
    archive = MemoryArchive()
    sink = RollingFields(root, archive, "fixture", limit=32768)
    assert consume_spool(extracted, sink) == 5
    sink.flush()
    assert not list((extracted / "fields").rglob("*.parquet"))
    assert not list((root / ".cloud-stream").iterdir())
    assert len(list(remote_reductions(extracted))) == 5
    assert verify_export(extracted)["rows"] == 10
    assert all(f["bytes"] <= sink.limit for f in sink.records)
    manifest = archive.publish(root, attempt="fixture", complete=True)
    assert any(f["path"].startswith("streamed-fields/") for f in manifest["files"])
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=archive.payloads[str(request.url)])
    )) as client:
        restored = tmp_path / "restored"
        restore(manifest, restored, client=client)
    proof = unpack_fields(restored)
    assert proof["original_parquet_checksums_verified"] == 5
    restored_extract = restored / extracted.relative_to(root)
    assert verify_export(restored_extract)["rows"] == 10  # Receipts + local rows counted once.
    files = sorted((restored_extract / "fields").rglob("*.parquet"))
    assert len(files) == 5
    with pq.ParquetFile(files[-1]) as parquet:
        rows = parquet.read().to_pylist()
    assert rows[0]["data"] == [1, 2, 7] and rows[0]["node_label"] == 11
    unpack_fields(restored)  # Idempotent reuse, never overwrite a different file.
    files[0].write_bytes(b"user file")
    with pytest.raises(ValueError, match="Existing field differs"):
        unpack_fields(restored)


def test_failed_upload_keeps_all_parquet_and_never_writes_remote_receipts(tmp_path):
    extracted = fixture(tmp_path, frames=1)
    archive = MemoryArchive()
    sink = RollingFields(tmp_path, archive, "fixture", limit=32768)
    consume_spool(extracted, sink)
    archive.bad_digest = True
    with pytest.raises(ValueError, match="Unverified"):
        sink.flush()
    assert len(list((extracted / "fields").rglob("*.parquet"))) == 1
    assert not list((extracted / "remote-fields").glob("*.json"))
    archive.bad_digest = False
    sink.flush()
    assert verify_export(extracted)["rows"] == 2


def test_crash_after_receipt_before_eviction_neither_double_counts_nor_loses_data(tmp_path, monkeypatch):
    extracted = fixture(tmp_path, frames=2)
    sink = RollingFields(tmp_path, MemoryArchive(), "fixture", limit=65536)
    consume_spool(extracted, sink)
    original = Path.unlink
    deleted = []

    def interrupted(path, *args, **kwargs):
        if path.suffix == ".parquet":
            deleted.append(path)
            if len(deleted) == 2:
                raise OSError("deliberate second-file eviction interruption")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(OSError):
        sink.flush()
    assert len(list((extracted / "fields").rglob("*.parquet"))) == 1
    assert verify_export(extracted)["rows"] == 4
    monkeypatch.setattr(Path, "unlink", original)
    sink.flush()
    assert verify_export(extracted)["rows"] == 4


def test_archived_receipts_survive_extraction_retry_directory_rename(tmp_path):
    root = tmp_path / "source"
    extracted = fixture(root, frames=1)
    archive = MemoryArchive()
    sink = RollingFields(root, archive, "fixture", limit=32768)
    consume_spool(extracted, sink)
    sink.flush()
    history = extracted.parent / "postprocess-history/extract-previous"
    history.parent.mkdir()
    extracted.rename(history)
    # A new extraction generation can publish to the same logical field name.
    current = fixture(root, frames=2)
    consume_spool(current, sink)
    sink.flush()
    manifest = archive.publish(root, attempt="fixture", complete=True)
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=archive.payloads[str(request.url)])
    )) as client:
        restore(manifest, tmp_path / "restored", client=client)
    proof = unpack_fields(tmp_path / "restored")
    assert proof["original_parquet_checksums_verified"] == 3


@pytest.mark.parametrize("kind", ["traversal", "symlink"])
def test_unpack_rejects_traversal_and_symlinks_before_writing(tmp_path, kind):
    import io

    with tarfile.open(tmp_path / "field-reductions.tar", "w") as bundle:
        member = tarfile.TarInfo("../escape.json" if kind == "traversal" else "fields/escape.parquet")
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "../escape.json"
            bundle.addfile(member)
        else:
            member.size = 2
            bundle.addfile(member, io.BytesIO(b"{}"))
    with pytest.raises(ValueError):
        unpack_fields(tmp_path)
    assert not (tmp_path.parent / "escape.json").exists()
