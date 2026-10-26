"""Orchestration fixture only: no native runtime, credentials or research results."""

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec, ModelSpec, digest

module_spec = importlib.util.spec_from_file_location("cloud_worker_test", Path(__file__).resolve().parents[1] / "scripts/cloud_worker.py")
cloud_worker = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(cloud_worker)


def test_cloud_retries_waiting_license_without_duplicate_catalog_rows(tmp_path, monkeypatch):
    identity = "a" * 32
    spec = BatchSpec(model=ModelSpec(cpus=1), render_images=False).model_dump()
    documents = {"jobs/" + identity: {"id": identity, "status": "draft", "profile": "research",
                 "spec": spec, "input_hash": digest(spec)}, "index": {"jobs": [{"id": identity}]}}
    checkpoints = []
    calls = []

    class Remote:
        def __init__(self, **kwargs):
            pass

        def repo(self, method, path, body=None):
            return {"id": 1, "html_url": "https://github.com/example/test-fixture"}

    class Catalog:
        def __init__(self, remote):
            pass

        def get(self, key):
            return documents.get(key), None

        def update(self, key, transform):
            documents[key] = transform(documents.get(key))
            return documents[key]

    class TestEngine(Engine):
        def __init__(self, store, **kwargs):
            super().__init__(store, fake=True)

        def _execute(self, run, batch):
            calls.append(run["id"])
            run.update(status="waiting_license" if len(calls) == 1 else "completed",
                       retry_after=0, test_only=True, quality={"ml_eligible": False})
            self.store.save("runs", run)

    class Progress:
        stop_reason = None

        def __init__(self, *args):
            pass

        def start(self, *args):
            pass

        def finish(self, *args):
            pass

    class Archive:
        def __init__(self, *args):
            pass

        def publish(self, root, **kwargs):
            checkpoints.append(kwargs)

    monkeypatch.setenv("GITHUB_TOKEN", "test-fixture")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_SHA", "test-fixture")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("HONEYCOMB_WORKFLOW_STARTED_EPOCH", str(time.time()))
    monkeypatch.delenv("HONEYCOMB_DRIVE_CREDENTIALS_JSON", raising=False)
    monkeypatch.setattr(cloud_worker, "Github", Remote)
    monkeypatch.setattr(cloud_worker, "Catalog", Catalog)
    monkeypatch.setattr(cloud_worker, "Engine", TestEngine)
    monkeypatch.setattr(cloud_worker, "Progress", Progress)
    monkeypatch.setattr(cloud_worker, "ReleaseArchive", Archive)
    monkeypatch.setattr(cloud_worker, "require_qualification", lambda _: {"release": "test-fixture"})
    monkeypatch.setattr(cloud_worker.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="test-fixture"))
    monkeypatch.setattr(cloud_worker.signal, "signal", lambda *args: None)
    executable = tmp_path / "abaqus-fixture"
    executable.touch()
    monkeypatch.setattr(cloud_worker, "os", SimpleNamespace(environ=cloud_worker.os.environ, name="posix"))
    cloud_worker.run(SimpleNamespace(job_id=identity, abaqus=executable, root=tmp_path / "results"))
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(documents["jobs/" + identity]["runs"]) == 1
    assert documents["jobs/" + identity]["runs"][0]["status"] == "completed"
    assert [row.get("checkpoint") for row in checkpoints] == ["wave-0001", "wave-0002", None]
