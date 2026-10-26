import hashlib
import json
import os
import tarfile

import httpx
import pytest

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_publication import prepare


def test_many_reductions_bundle_losslessly_and_large_files_are_not_copied(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "model.odb").write_bytes(b"binary transport fixture")
    (source / "credentials").mkdir()
    (source / "credentials/oauth.json").write_text("private test fixture")
    records = source / "extracted/reduced-fields"
    records.mkdir(parents=True)
    for i in range(1010):
        (records / f"{i}.json").write_bytes(json.dumps({"value": i}).encode())
    prepare(source, target)
    assert os.path.samefile(source / "model.odb", target / "model.odb")
    assert not (target / "credentials").exists()
    assert len(list(target.iterdir())) == 3
    with tarfile.open(target / "field-reductions.tar") as bundle:
        assert len(bundle.getmembers()) == 1010
        for member in bundle:
            assert bundle.extractfile(member).read() == (source / member.name).read_bytes()


def test_upload_retries_after_lost_response_and_reuses_verified_asset(tmp_path, monkeypatch):
    payload = b"transport fixture"
    path = tmp_path / "data"
    path.write_bytes(payload)
    calls = []
    asset = {"id": 1, "name": "test.part", "size": len(payload),
             "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
             "browser_download_url": "https://github.com/test"}

    class Client:
        def post(self, *args, **kwargs):
            calls.append("post")
            raise httpx.ReadTimeout("Accepted on server, response lost")

    class Remote:
        client = Client()

        def access_token(self):
            return "test-fixture"

        def repo(self, *args):
            return [asset] if calls else []

    monkeypatch.setattr("honeycomb_studio.cloud_archive.time.sleep", lambda _: None)
    uploaded = ReleaseArchive(Remote(), 1).upload(path, "test.part")
    assert calls == ["post"]
    assert uploaded["asset_id"] == 1
    asset["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest"):
        ReleaseArchive(Remote(), 1).upload(path, "test.part")
