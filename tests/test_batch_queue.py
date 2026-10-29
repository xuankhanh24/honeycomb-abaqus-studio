"""Queue isolation and terminal-range collection guards; no licensed solver."""

import runpy
from copy import deepcopy
from pathlib import Path

from honeycomb_studio.cloud_matrix import prepare
from honeycomb_studio.models import BatchSpec, ModelSpec, digest

collect = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/collect_cloud_training.py"))["collect"]


def batch():
    spec = BatchSpec(model=ModelSpec(cpus=4), execution_mode="parallel", max_parallel_runs=3,
                     axes=[{"parameter": "energy_J", "values": [5, 7, 9]}]).model_dump()
    return {"id": "a" * 32, "name": "fixture", "profile": "research", "status": "draft",
            "spec": spec, "input_hash": digest(spec)}


def test_ranges_have_independent_claims_and_immutable_shard_identities():
    a = batch()
    a["spec"].update(max_parallel_runs=20, axes=[{"parameter": "energy_J", "values": list(range(1, 22))}])
    a["input_hash"] = digest(a["spec"])
    first = prepare(a, 1)
    second = prepare({**a, "id": "b" * 32}, 2)
    assert len(first["shards"]) == len(second["shards"]) == 21
    assert first["execution"]["effective_parallel_runs"] == 20
    assert not {s["id"] for s in first["shards"]} & {s["id"] for s in second["shards"]}


def test_active_range_is_excluded_even_when_some_shards_are_verified(tmp_path):
    parent = prepare(batch(), 1)
    parent["shards"][0].update(status="completed", archive_verified=True, release_url="fixture")

    class Catalog:
        def jobs(self):
            return [{"id": parent["id"]}]

        def get(self, key):
            return deepcopy(parent), None

    class NoDownloads:
        def repo(self, *args, **kwargs):
            raise AssertionError("Do not collect partial active ranges")

    sources = collect(NoDownloads(), Catalog(), tmp_path)
    assert len(sources) == 3
    assert all(not s["runs"] and "chưa kết thúc" in s["excluded_reason"] for s in sources)


def test_workflow_isolates_ranges_and_serializes_only_publishers():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/abaqus-linux.yml").read_text(encoding="utf-8")
    assert "group: honeycomb-batch-${{ inputs.job_id }}" in workflow
    assert "honeycomb-licensed-solver" not in workflow
    assert "needs: [prepare, simulate]" in workflow
    assert "fail-fast: false" in workflow
    finalizer = workflow.split("  finalize:")[1]
    assert "group: honeycomb-training-collection" in finalizer
    assert "queue: max" in finalizer
    manual = (root / ".github/workflows/collect-training.yml").read_text(encoding="utf-8")
    assert "group: honeycomb-training-collection" in manual and "queue: max" in manual


def test_web_exposes_runner_state_and_blocks_collecting_active_range(monkeypatch):
    import base64
    import json

    from fastapi.testclient import TestClient
    from itsdangerous import TimestampSigner

    from honeycomb_studio import cloud_api
    from honeycomb_studio.cloud_matrix import matrix_entries

    parent = prepare(batch(), 12)
    label = matrix_entries(parent)["include"][0]["display_name"]
    collection = {"source_complete": True, "source_status": "completed", "workflow_run_id": 12,
                  "collection_workflow_url": "https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/13",
                  "files": [{"path": "large-inventory"}]}

    class Memory:
        def get(self, key):
            return deepcopy(parent if key.startswith("jobs/") else collection), None

    class Connected:
        configured = True

        def repo(self, method, path, body=None):
            assert method == "GET", "Active range must not dispatch collection"
            if "/jobs?" in path:
                return {"jobs": [{"name": label, "id": 99, "status": "in_progress"}]}
            return {"status": "in_progress"}

    monkeypatch.setattr(cloud_api, "Catalog", lambda github: Memory())
    monkeypatch.setenv("WEB_SESSION_SECRET", "queue-test-only")
    monkeypatch.setenv("WEB_LOCAL_HTTP", "1")
    with TestClient(cloud_api.create_app(Connected())) as client:
        path = "/api/jobs/" + parent["id"]
        value = client.get(path).json()
        assert value["shards"][0]["action_status"] == "in_progress"
        assert value["shards"][0]["action_job_id"] == 99
        assert value["shards"][0]["status"] == "draft"
        assert value["data_collection"]["workflow_run_id"] == 12
        assert value["data_collection"]["source_complete"] is True
        assert "files" not in value["data_collection"]
        session = base64.b64encode(json.dumps({"user_id": cloud_api.OWNER_ID, "csrf": "fixture"}).encode())
        client.cookies.set("session", TimestampSigner("queue-test-only").sign(session).decode())
        assert client.post(path + "/data/collect", headers={"X-Honeycomb-CSRF": "fixture"}).status_code == 409
