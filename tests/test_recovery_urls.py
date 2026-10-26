from copy import deepcopy

import pytest

from honeycomb_studio.cloud_release import canonical_manifest


def test_recover_draft_urls_by_asset_identity_not_path_replacement():
    original = {"files": [{"parts": [{"asset_id": 42, "url": "https://github.com/old/untagged/part", "sha256": "a" * 64, "bytes": 16}]}]}
    assets = [{"id": 42, "browser_download_url": "https://github.com/repo/releases/download/source/part", "digest": "sha256:" + "a" * 64, "size": 16}]
    recovered = canonical_manifest(deepcopy(original), assets)
    assert recovered["files"][0]["parts"][0]["url"] == assets[0]["browser_download_url"]
    assets[0]["digest"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        canonical_manifest(deepcopy(original), assets)
