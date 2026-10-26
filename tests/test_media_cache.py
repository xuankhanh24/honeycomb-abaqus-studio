import hashlib

import pytest

from honeycomb_studio.media_cache import download_iso, verify_iso


class Response:
    status_code = 200

    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, block_size):
        yield self.content[:3]
        yield self.content[3:]


class Session:
    def __init__(self, content):
        self.content = content

    def get(self, url, **kwargs):
        assert url == "https://www.googleapis.com/drive/v3/files/test-file-id"
        assert kwargs["params"] == {"alt": "media"}
        return Response(self.content)


def test_private_media_download_requires_exact_bytes_and_hash(tmp_path):
    content = b"test-only installer transport fixture"
    digest = hashlib.sha256(content).hexdigest()
    target = tmp_path / "media.iso"
    result = download_iso(Session(content), "test-file-id", target, expected_bytes=len(content), expected_sha256=digest)
    assert result["sha256"] == digest
    assert target.read_bytes() == content
    assert verify_iso(target, expected_bytes=len(content), expected_sha256=digest)["md5"] == hashlib.md5(content).hexdigest()


@pytest.mark.parametrize("data", [b"truncated", b"longer-than-expected", b"wronghash!"])
def test_bad_download_never_publishes_an_installable_iso(tmp_path, data):
    target = tmp_path / "media.iso"
    with pytest.raises(ValueError):
        download_iso(Session(data), "test-file-id", target, expected_bytes=10, expected_sha256=hashlib.sha256(b"valid-data").hexdigest())
    assert not target.exists()
    assert not target.with_suffix(".iso.part").exists()
