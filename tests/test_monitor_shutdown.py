from pathlib import Path

import pytest

from honeycomb_studio.engine import Detached, Engine
from honeycomb_studio.models import BatchSpec
from honeycomb_studio.store import Store


def test_shutdown_during_monitor_wait_preserves_owned_process(tmp_path, monkeypatch):
    store = Store(tmp_path)
    batch = store.create(BatchSpec())
    run = store.list("runs", batch["id"])[0]
    attempt = {"path": str(Path(run["path"]) / "attempts/001"), "job_name": "fixture",
               "number": 1, "process": {"pid": 123, "created": 1}}
    engine = Engine(store, fake=True)
    monkeypatch.setattr("honeycomb_studio.engine.solver.owned_tree_alive", lambda _: True)
    monkeypatch.setattr("honeycomb_studio.engine.solver.refresh_owned_tree", lambda _: None)
    monkeypatch.setattr("honeycomb_studio.engine.solver.owned_alive", lambda _: False)
    monkeypatch.setattr(engine.shutdown, "wait", lambda _: engine.shutdown.set())
    with pytest.raises(Detached):
        engine._monitor(run, attempt, "solving", None)
    assert attempt["process"] == {"pid": 123, "created": 1}
    assert "durations" not in attempt
    store.db.close()
