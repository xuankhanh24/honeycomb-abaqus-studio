import base64
import hashlib
import io
import json
import runpy
import zipfile
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from honeycomb_studio.cloud_github import REPOSITORY
from honeycomb_studio.cloud_job_data import publish_job_data
from honeycomb_studio.cloud_quality import longer_research_spec
from honeycomb_studio.job_data import full_manifest, job_folder, standalone_downloader
from honeycomb_studio.models import Axis, BatchSpec, ModelSpec, expand
from honeycomb_studio.store import Store


def test_longer_run_preserves_physics_and_keeps_original_result():
    spec = BatchSpec(axes=[Axis(parameter="energy_J", values=[5, 7])], execution_mode="parallel").model_dump()
    parent = {"profile": "research", "name": "Bài gốc", "spec": spec,
              "runs": [{"quality": {"findings": ["Cuối step còn tiếp xúc >10 N; cần xem xét tăng thời gian vật lý"]}}]}
    original = deepcopy(parent)
    revised = longer_research_spec(parent)
    assert parent == original
    for old, new in zip(expand(BatchSpec.model_validate(spec)), expand(revised), strict=True):
        assert new["resolved"]["duration"] == old["resolved"]["duration"] * 2
        assert new["resolved"]["history_intervals"] == old["resolved"]["history_intervals"] * 2
        assert new["design_id"] == old["design_id"]
        for key in ("energy_J", "mesh_preset", "panel", "core_height", "face_material", "cpus"):
            assert new["resolved"][key] == old["resolved"][key]
    parent["profile"] = "smoke"
    with pytest.raises(ValueError, match="Smoke"):
        longer_research_spec(parent)
    parent["profile"] = "research"
    parent["runs"][0]["quality"]["findings"].append("artificial_energy=8%")
    with pytest.raises(ValueError, match="Không chỉ"):
        longer_research_spec(parent)


def test_one_parent_folder_contains_all_parallel_results_and_full_solver_bytes(tmp_path, monkeypatch):
    # This is a packaging fixture, not a licensed solver/physics claim.
    store = Store(tmp_path / "store")
    payloads = {}
    sources = []
    identity = "a" * 32
    for i in range(2):
        batch = store.create(BatchSpec())
        run = store.list("runs", batch["id"])[0]
        run.update(status="review", quality={"ml_eligible": False, "findings": ["Contact active"]}, summary={"SEA_J_kg": 12})
        data = (f"PACKAGING FIXTURE ODB {i}").encode()
        sha = hashlib.sha256(data).hexdigest()
        url = f"https://github.com/{REPOSITORY}/releases/download/test/{i}.part"
        payloads[url] = data
        path = f"projects/p/batches/{batch['id']}/runs/{run['id']}/attempts/001/raw/model.odb"
        archive = {"schema_version": "1", "kind": "honeycomb-release-archive", "complete": True,
                   "files": [{"path": path, "bytes": len(data), "sha256": sha,
                              "parts": [{"index": 0, "offset": 0, "bytes": len(data), "sha256": sha,
                                         "digest": "sha256:" + sha, "url": url}]}]}
        sources.append({"job_id": identity, "job_name": "Khảo sát lõi lõm", "index": i,
                        "shard_id": str(i), "status": "review", "manifest_sha256": sha, "archive": archive,
                        "job": {"id": identity, "name": "Khảo sát lõi lõm", "status": "review", "workflow_run_id": 123},
                        "runs": [run]})
    assets = {}

    class Publisher:
        def __init__(self, *args):
            pass

        def upload(self, path, name):
            assets[name] = path.read_bytes()
            return {"url": f"https://github.com/{REPOSITORY}/releases/download/test/" + name,
                    "bytes": len(assets[name]), "digest": "sha256:" + hashlib.sha256(assets[name]).hexdigest(), "asset_id": len(assets)}

    class Catalog:
        def __init__(self):
            self.value = None

        def get(self, key):
            return self.value, None

        def update(self, key, transform):
            self.value = transform(self.value)

    class Github:
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payloads[str(r.url)])))

        def repo(self, method, path, body):
            return {"html_url": "https://github.com/" + REPOSITORY + "/releases/tag/test"}

    monkeypatch.setattr("honeycomb_studio.cloud_job_data.ReleaseArchive", Publisher)
    catalog = Catalog()
    data = publish_job_data(Github(), catalog, sources, {"id": 1}, workflow=456, attempt=1, full=True, root=tmp_path)
    assert data["runs"] == 2 and data["samples"] == 0 and data["source_complete"]
    assert data["full_bundle"]["parts"] == 1
    assert "files" not in data and len(catalog.value["files"]) > 2
    folder = job_folder(identity, sources[0]["job_name"])
    assert folder.startswith("job--khao-sat-loi-lom--")
    bundle = next(value for name, value in assets.items() if name.startswith(folder) and name.endswith(".zip"))
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        for i in range(2):
            name = f"{folder}/04_solver_archive/run-{i + 1:04d}/attempts/001/raw/model.odb"
            assert archive.read(name) == payloads[list(payloads)[i]]
        assert any("03_simulations/run-0002" in name and name.endswith("input/resolved.json") for name in archive.namelist())
        assert json.loads(archive.read(folder + "/01_training/dataset.json"))["samples"] == 0
    # The shipped helper reconstructs and extracts the same verified folder.
    helper = tmp_path / "download_full.py"
    helper.write_bytes(assets["download_full.py"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(bundle))
    runpy.run_path(str(helper), run_name="__main__")
    assert list(tmp_path.glob("*--export-456-1/**/model.odb"))
    assert publish_job_data(Github(), catalog, sources, None, workflow=457, attempt=1, full=True, root=tmp_path) == data
    corrupt = tmp_path / "corrupt-download"
    corrupt.mkdir()
    monkeypatch.chdir(corrupt)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(bytes([bundle[0] ^ 1]) + bundle[1:]))
    with pytest.raises(ValueError, match="checksum"):
        runpy.run_path(str(helper), run_name="__main__")
    assert not list(corrupt.glob("**/model.odb"))
    with pytest.raises(ValueError, match="Duplicate"):
        full_manifest(sources + [sources[0]])


def test_source_manifest_marks_missing_shard_and_downloader_compiles():
    assert full_manifest([{"job_id": "a", "job_name": "Bài đang chạy"}])["complete"] is False
    value = standalone_downloader({"files": []})
    compile(value, "download_full.py", "exec")


def test_job_folder_is_public_but_packaging_and_quality_retry_require_owner(monkeypatch):
    from honeycomb_studio import cloud_api

    identity = "a" * 32
    document = {"id": identity, "name": "Khảo sát lõi lõm", "status": "review", "profile": "research",
                "spec": BatchSpec(model=ModelSpec(cpus=4)).model_dump(), "runs": [{"quality": {"findings": ["Cuối step còn tiếp xúc >10 N"]}}]}
    records = {"jobs/" + identity: document,
               "training/jobs/" + identity: {"id": identity, "files": [{"path": "input/resolved.json", "bytes": 10}]}}

    class Memory:
        def __init__(self, *a):
            pass

        def get(self, key):
            return records.get(key), None

        def update(self, key, transform):
            records[key] = transform(records.get(key))
            return records[key]

    calls = []

    class Github:
        configured = True

        def repo(self, method, path, body):
            calls.append((method, path, body))

    monkeypatch.setattr(cloud_api, "Catalog", Memory)
    monkeypatch.setenv("WEB_SESSION_SECRET", "packaging-tests-only")
    monkeypatch.setenv("WEB_LOCAL_HTTP", "1")
    with TestClient(cloud_api.create_app(Github())) as client:
        assert client.get(f"/api/jobs/{identity}/data").json()["collection"]["files"]
        assert client.get("/api/jobs/invalid/data").status_code == 404
        assert client.post(f"/api/jobs/{identity}/data/collect").status_code == 403
        retry = {"request_id": "b" * 32}
        assert client.post(f"/api/jobs/{identity}/training-retry", json=retry).status_code == 403
        payload = base64.b64encode(json.dumps({"user_id": cloud_api.OWNER_ID, "csrf": "test-csrf"}).encode())
        client.cookies.set("session", TimestampSigner("packaging-tests-only").sign(payload).decode())
        headers = {"X-Honeycomb-CSRF": "test-csrf"}
        assert client.post(f"/api/jobs/{identity}/data/collect", headers=headers).status_code == 200
        assert calls == [("POST", "/actions/workflows/collect-training.yml/dispatches", {"ref": "main", "inputs": {"job_id": identity}})]
        result = client.post(f"/api/jobs/{identity}/training-retry", json=retry, headers=headers)
        assert result.status_code == 201
        assert result.json()["source_job_id"] == identity
        assert result.json()["spec"]["model"]["duration"] == .012
        assert result.json()["status"] == "draft" and records["jobs/" + identity] == document
