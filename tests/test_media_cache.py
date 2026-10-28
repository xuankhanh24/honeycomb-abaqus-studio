import hashlib

import pytest

from honeycomb_studio.media_cache import (
    ISO_BYTES,
    ISO_SHA256,
    download_iso,
    drive_failure_hint,
    preflight_drive_iso,
    verify_iso,
)


def test_drive_preflight_refresh_failure_propagates_without_exposing_provider_secrets():
    class RefreshError(Exception):
        pass

    error = RefreshError("private refresh token payload", {"error": "invalid_grant", "private": "do-not-print"})

    class Revoked:
        def get(self, *args, **kwargs):
            raise error

    with pytest.raises(RefreshError):
        preflight_drive_iso(Revoked(), "test-file-id")
    hint = drive_failure_hint(error)
    assert "invalid_grant" in hint and "HONEYCOMB_DRIVE_CREDENTIALS_JSON" in hint
    assert "do-not-print" not in hint and "payload" not in hint


def test_drive_preflight_checks_auth_download_permission_and_exact_pinned_metadata():
    info = {"size": str(ISO_BYTES), "sha256Checksum": ISO_SHA256, "trashed": False,
            "capabilities": {"canDownload": True}}

    class Remote:
        def get(self, url, **kwargs):
            assert url.endswith("/test-file-id") and "alt" not in kwargs["params"]
            return type("Metadata", (), {"status_code": 200, "json": lambda self: info})()

    assert preflight_drive_iso(Remote(), "test-file-id")["download_allowed"]
    info["capabilities"]["canDownload"] = False
    with pytest.raises(ValueError, match="quyền tải"):
        preflight_drive_iso(Remote(), "test-file-id")
    info["capabilities"]["canDownload"] = True
    info["sha256Checksum"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        preflight_drive_iso(Remote(), "test-file-id")


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
