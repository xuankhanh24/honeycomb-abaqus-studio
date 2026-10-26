import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from honeycomb_studio.actions_log import ActionsLog, clean, markdown, snapshot


def test_secrets_and_control_commands_are_redacted_everywhere(tmp_path, monkeypatch):
    secret = 'private"key\\with\nnewlines'
    monkeypatch.setenv("GITHUB_TOKEN", secret)
    stream = io.StringIO()
    events, summary = tmp_path / "events.jsonl", tmp_path / "summary.md"
    log = ActionsLog(stream=stream, events_path=events, summary_path=summary)
    text = secret + " https://host.test/file?signature=PRIVATE ::error::bad\nnext"
    log.emit("TEST", text, nested={"value": secret})
    log.notices.append(text)
    log.summary()
    for value in (stream.getvalue(), events.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8")):
        assert secret not in value
        assert "signature=PRIVATE" not in value
        assert "\n::error::" not in value
    assert json.loads(events.read_text(encoding="utf-8"))["nested"]["value"] == "<redacted>"
    assert "[link]" not in markdown("[link](javascript:alert(1)) | <script>")
    assert "<script>" not in markdown("<script>")
    assert "token" not in clean("Authorization: Bearer token")


def test_only_phase_measurements_are_percentages():
    run = {"id": "one", "status": "building", "progress": {"solver_percent": 65}}
    assert snapshot(run)["percent"] is None
    run["status"] = "solving"
    assert snapshot(run)["percent"] == 65
    run["status"] = "extracting"
    assert snapshot(run)["percent"] is None
    run["progress"]["extraction_percent"] = 12
    assert snapshot(run)["percent"] == 12


def test_transfer_rates_use_actual_bytes_and_never_invent_completion(tmp_path):
    now = [0.0]
    log = ActionsLog(clock=lambda: now[0], stream=io.StringIO(), summary_path=tmp_path / "summary")
    transfer = log.transfer("ODB", 100)
    now[0] = 20
    transfer.advance(40)
    assert log.transfers["ODB"]["rate"] == 2
    assert "chưa xác minh" in log.transfers["ODB"]["state"]
    with pytest.raises(ValueError, match="byte count"):
        transfer.verified()
    transfer.advance(60)
    transfer.verified()
    assert log.transfers["ODB"]["state"] == "Đã xác minh"
    unknown = log.transfer("Unknown total", None)
    unknown.advance(1)
    unknown.report("Đang truyền")
    assert log.transfers["Unknown total"]["total"] is None


def test_wrapper_preserves_failure_and_writes_redacted_details(tmp_path):
    root = Path(__file__).resolve().parents[1]
    detail, summary = tmp_path / "details.log", tmp_path / "summary.md"
    env = dict(os.environ, HONEYCOMB_ACTIONS_LOG="1", GITHUB_STEP_SUMMARY=str(summary),
               HONEYCOMB_LOG_DIR=str(tmp_path), TEST_TOKEN="private-secret-value", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, str(root / "scripts/actions_step.py"), "--title", "Installer",
                             "--details", str(detail), "--heartbeat", "0.1", "--", sys.executable,
                             "-c", "import time; print('private-secret-value license failed', flush=True); time.sleep(.25); raise SystemExit(7)"],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 7
    assert "[HEARTBEAT]" in result.stdout
    assert "[FIX]" in result.stdout
    assert "private-secret-value" not in result.stdout + detail.read_text(encoding="utf-8") + summary.read_text(encoding="utf-8")
    assert "exit code 7" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("valid", [True, False])
def test_upload_marks_verified_only_after_remote_digest(tmp_path, monkeypatch, valid):
    import hashlib

    import httpx

    from honeycomb_studio.actions_log import get_actions_log
    from honeycomb_studio.cloud_archive import ReleaseArchive
    from honeycomb_studio.cloud_github import Github

    monkeypatch.setenv("HONEYCOMB_ACTIONS_LOG", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setenv("HONEYCOMB_LOG_DIR", str(tmp_path))
    content = b"test transport only" * 100
    path = tmp_path / "upload.part"
    path.write_bytes(content)

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=[])
        assert request.read() == content
        return httpx.Response(201, json={"digest": "sha256:" + (hashlib.sha256(content).hexdigest() if valid else "0" * 64),
                                         "size": len(content), "browser_download_url": "https://github.com/fixture", "id": 1})

    archive = ReleaseArchive(Github(token="test-only", client=httpx.Client(transport=httpx.MockTransport(handle))), 1)
    if valid:
        archive._upload(path, "model.part")
    else:
        with pytest.raises(ValueError, match="SHA-256"):
            archive._upload(path, "model.part")
    transfer = get_actions_log().transfers["Upload model.part"]
    assert transfer["done"] == len(content)
    assert (transfer["state"] == "Đã xác minh") is valid


def test_local_progress_remains_visible_when_github_is_offline(tmp_path, monkeypatch, capsys):
    from honeycomb_studio.cloud_progress import Progress
    from honeycomb_studio.models import BatchSpec
    from honeycomb_studio.store import Store

    monkeypatch.setenv("HONEYCOMB_ACTIONS_LOG", "1")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setenv("HONEYCOMB_LOG_DIR", str(tmp_path))
    store = Store(tmp_path / "store")
    batch = store.create(BatchSpec())

    class Offline:
        def get(self, key):
            progress.done.set()
            raise ConnectionError("network offline")

    progress = Progress(None, Offline(), "fixture", store, batch["id"], 0)
    try:
        progress.loop()
        assert "[RUN]" in capsys.readouterr().out
        assert progress.stop_reason == "timed_out"
    finally:
        store.db.close()
