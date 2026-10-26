import hashlib
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from honeycomb_studio import cloud_api
from honeycomb_studio.cloud_github import REPOSITORY, Github


def test_field_view_asset_is_catalog_bound_bounded_and_verified(monkeypatch):
    raw = b'{"kind":"honeycomb-field-view","source":{"test_fixture":true}}'
    asset = {"asset_id": 123, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    class Catalog:
        def __init__(self, github):
            pass

        def get(self, key):
            return {"runs": [{"id": "run-one", "field_view": asset}]}, None

    def upstream(request):
        assert str(request.url) == f"https://api.github.com/repos/{REPOSITORY}/releases/assets/123"
        return httpx.Response(200, content=raw)

    monkeypatch.setattr(cloud_api, "Catalog", Catalog)
    github = Github(client=httpx.Client(transport=httpx.MockTransport(upstream)))
    with TestClient(cloud_api.create_app(github)) as client:
        url = "/api/jobs/" + "a" * 32 + "/field-view/run-one"
        assert client.get(url).content == raw
        assert client.get(url.replace("run-one", "unknown")).status_code == 404
        asset["sha256"] = "0" * 64
        assert client.get(url).status_code == 502
        asset["bytes"] = 4 * 1024**2 + 1
        assert client.get(url).status_code == 404


def test_actual_reference_display_exports_match_manifest():
    root = Path(__file__).resolve().parents[1] / "web/static"
    for reference in json.loads((root / "reference/index.json").read_text(encoding="utf-8")):
        view = reference["field_view"]
        raw = (root / view["url"].lstrip("/")).read_bytes()
        data = json.loads(raw)
        assert hashlib.sha256(raw).hexdigest() == view["sha256"]
        assert len(raw) <= 4 * 1024**2
        history = (root / reference["history"].lstrip("/")).read_bytes()
        assert hashlib.sha256(history).hexdigest() == reference["sha256"]
        assert not history.startswith(b"\xef\xbb\xbf") and b"\r\n" not in history
        if reference["id"] == "linux-perimeter-7j":
            assert reference["status"] == "review" and reference["cloud_qualification"] is False
            assert reference["clamp_mode"] == "perimeter"
            assert data["source"]["clamp_mode"] == reference["clamp_mode"]
            assert data["source"]["energy_J"] == 7
            assert data["source"]["test_only"] is False
            assert reference["quality"]["ml_eligible"] is False
            assert len(data["frames"]) == 13
            assert data["frames"][-1]["time_s"] > .00599
            continue
        assert data["source"]["cloud_qualification"] is False
        assert data["source"]["clamp_mode"] == "circular"
        assert data["source"]["reference_id"] == reference["id"]
        assert len(data["frames"]) == 13
        assert data["frames"][-1]["time_s"] > 0.00599
        assert data["sampling"]["display_elements"] <= 1000
        verification = (root / view["verification_url"].lstrip("/")).read_bytes()
        assert hashlib.sha256(verification).hexdigest() == view["verification_sha256"]
        receipt = json.loads(verification)
        assert receipt["passed"] is True
        assert receipt["solver_executed"] is False
        assert receipt["linux_qualification"] is False
        assert receipt["odb_sha256"] == data["source"]["odb_sha256"]
        assert receipt["display_sha256"] == view["sha256"]
        assert len(receipt["comparisons"]) == 81
