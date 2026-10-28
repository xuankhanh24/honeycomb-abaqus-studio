"""Propose an explicit new research job when contact has not ended; never edit results."""

from copy import deepcopy

from .models import BatchSpec, expand


def longer_research_spec(parent):
    if parent["profile"] == "smoke":
        raise ValueError("Smoke chỉ kiểm tra môi trường. Hãy tạo bài research đầy đủ từ Thiết lập.")
    if parent.get("shards") and any(s["status"] not in ("review", "completed") for s in parent["shards"]):
        raise ValueError("Job còn lượt chưa hoàn tất hoặc lỗi môi trường. Cần xử lý các lượt đó trước.")
    runs = parent.get("runs", [])
    findings = [finding for run in runs for finding in (run.get("quality") or {}).get("findings", [])]
    if not findings or any(not f.startswith("Cuối step còn tiếp xúc >10 N") for f in findings):
        raise ValueError("Không chỉ có lỗi thời gian tiếp xúc. Xem quality.json để sửa đúng nguyên nhân trước khi chạy lại.")
    spec = deepcopy(parent["spec"])
    expanded = expand(BatchSpec.model_validate(spec).model_copy(update={"max_runs": 20}))
    if any(r["resolved"]["duration"] * 2 > .024 + 1e-12 for r in expanded):
        raise ValueError("Đề xuất tự động dừng ở 24 ms. Cần xem đường cong và ngân sách trước khi tăng tiếp.")
    spec["name"] = parent["name"][:120] + " · research · thời gian ×2"
    spec["model"]["duration"] *= 2
    spec["model"]["history_intervals"] = min(1000000, spec["model"].get("history_intervals", 1200) * 2)
    for axis in spec.get("axes", []):
        if axis["parameter"] == "duration":
            if axis.get("values") is not None:
                axis["values"] = [value * 2 for value in axis["values"]]
            for key in ("start", "stop", "step"):
                if axis.get(key) is not None:
                    axis[key] *= 2
    for design in spec.get("designs", []):
        if "duration" in design:
            design["duration"] *= 2
        if "history_intervals" in design:
            design["history_intervals"] = min(1000000, design["history_intervals"] * 2)
    spec.update(data_profile="research", max_runs=20, runtime_budget_minutes=270)
    result = BatchSpec.model_validate(spec)
    expand(result)
    return result
