import hashlib
from pathlib import Path

import httpx
import pytest

from honeycomb_studio.cloud_github import REPOSITORY
from honeycomb_studio.cloud_restore import restore


def inventory():
    payloads = [b"transport fixture A", b"transport fixture B", b"transport fixture C"]
    offset = 0
    parts = []
    for index, data in enumerate(payloads):
        sha = hashlib.sha256(data).hexdigest()
        parts.append(
            {
                "index": index,
                "offset": offset,
                "bytes": len(data),
                "sha256": sha,
                "digest": "sha256:" + sha,
                "url": f"https://github.com/{REPOSITORY}/releases/download/test/{index}.part",
            }
        )
        offset += len(data)
    return {
        "schema_version": "1",
        "kind": "honeycomb-release-archive",
        "complete": True,
        "files": [
            {
                "path": "raw/test.odb",
                "bytes": offset,
                "sha256": hashlib.sha256(b"".join(payloads)).hexdigest(),
                "parts": parts,
            }
        ],
    }, payloads


def test_restore_survives_new_process_and_reuses_verified_prefix(tmp_path):
    manifest, payloads = inventory()
    requests = []

    def interrupted(request):
        index = int(Path(request.url.path).stem)
        requests.append(index)
        if index == 1:
            raise httpx.ReadError("simulated network interruption")
        return httpx.Response(200, content=payloads[index])

    with httpx.Client(transport=httpx.MockTransport(interrupted)) as client:
        with pytest.raises(httpx.ReadError):
            restore(manifest, tmp_path, client=client)
    assert requests == [0, 1]
    assert not (tmp_path / "raw/test.odb").exists()

    def resumed(request):
        index = int(Path(request.url.path).stem)
        requests.append(index)
        return httpx.Response(200, content=payloads[index])

    # No in-memory state from the first invocation is reused.
    with httpx.Client(transport=httpx.MockTransport(resumed)) as client:
        assert restore(manifest, tmp_path, client=client)["complete_dataset"]
        assert requests == [0, 1, 1, 2]
        assert (tmp_path / "raw/test.odb").read_bytes() == b"".join(payloads)
        assert restore(manifest, tmp_path, client=client)["files"][0]["reused"]
        assert requests == [0, 1, 1, 2]


def test_bad_checksum_and_incomplete_archive_are_not_complete(tmp_path):
    manifest, _ = inventory()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"wrong"))
    ) as client:
        with pytest.raises(ValueError, match="SHA-256"):
            restore(manifest, tmp_path, client=client)
    assert not (tmp_path / "raw/test.odb").exists()
    manifest["complete"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        restore(manifest, tmp_path)


def test_subset_restore_does_not_claim_full_archive(tmp_path):
    manifest, _ = inventory()
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("No downloads expected"))) as client:
        result = restore(manifest, tmp_path, client=client, paths=[])
        assert result == {"files": [], "complete_dataset": False}
        with pytest.raises(ValueError, match="absent"):
            restore(manifest, tmp_path, client=client, paths=["missing.json"])


@pytest.mark.parametrize(
    "path", ["../escape.odb", "/escape.odb", "C:/escape.odb", "raw\\..\\escape", "raw/CON.txt"]
)
def test_untrusted_paths_rejected_before_network(tmp_path, path):
    manifest, _ = inventory()
    manifest["files"][0]["path"] = path
    with pytest.raises(ValueError, match="path"):
        restore(manifest, tmp_path)


def test_existing_file_never_overwritten(tmp_path):
    manifest, _ = inventory()
    (tmp_path / "raw").mkdir()
    path = tmp_path / "raw/test.odb"
    path.write_bytes(b"user's original file")
    with pytest.raises(ValueError, match="Existing file"):
        restore(manifest, tmp_path)
    assert path.read_bytes() == b"user's original file"
