import io

from honeycomb_studio.actions_log import ActionsLog, hint


def test_vietnamese_titles_phase_explanation_and_review_findings(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYCOMB_LOG_TITLE", "Mô phỏng thật 7 J · 6 ms")
    stream = io.StringIO()
    summary = tmp_path / "summary.md"
    log = ActionsLog(stream=stream, summary_path=summary)
    run = {"id": "test-input-not-solver-evidence", "status": "solving", "resolved": {"duration": .006},
           "progress": {"solver_percent": 50, "simulation_time_s": .003}}
    log.runs([run])
    log.runs([run])
    text = stream.getvalue()
    assert text.count("[PHASE]") == 1
    assert "TIẾN ĐỘ MÔ PHỎNG" in text and "thời gian vật lý 3.000/6 ms" in text
    assert "Phần trăm = thời gian vật lý" in text
    assert summary.read_text(encoding="utf-8").startswith("## Mô phỏng thật 7 J · 6 ms")
    run.update(status="review", quality={"findings": ["Cuối step còn tiếp xúc >10 N"]})
    log.runs([run])
    assert "Cần xem xét kết quả" in stream.getvalue()
    assert "Cuối step còn tiếp xúc" in summary.read_text(encoding="utf-8")


def test_release_failures_get_specific_vietnamese_guidance():
    assert "giữ chỗ" in hint("403 Forbidden https://api.github.com/repos/example/releases")
    assert "bản nháp" in hint("404 Not Found https://github.com/example/releases/download/untagged/part")
