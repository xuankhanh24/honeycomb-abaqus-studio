"""Small, immutable research products kept outside the simulation data root."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .data import checksum, dataset, manifest, write_rows
from .reports import batch_report
from .store import now, write_json

ACTIVE = {
    "building",
    "checking",
    "solving",
    "extracting",
    "cataloguing",
    "verifying_export",
    "analyzing",
    "rendering",
    "reporting",
    "recovering",
}


def retained_root(store):
    return store.root.parent / (store.root.name + "-retained")


def coverage(runs, included):
    result = []
    for run in runs:
        reason = "Đã xuất"
        if run["id"] not in included:
            if run.get("test_only"):
                reason = "Dữ liệu thử nghiệm giả lập"
            elif run["status"] != "completed":
                reason = "Lượt chưa hoàn tất"
            elif not (run.get("quality") or {}).get("ml_eligible"):
                reason = "Chưa đạt chất lượng số"
            else:
                reason = "Trùng đầu vào"
        result.append(
            {"run_id": run["id"], "index": run["index"], "included": run["id"] in included, "reason": reason}
        )
    return result


def verify_retained(root: Path, expected_hash: str | None = None):
    file = root / "artifact-manifest.json"
    if expected_hash and checksum(file) != expected_hash:
        raise ValueError("Manifest dữ liệu giữ lại đã thay đổi")
    record = json.loads(file.read_text(encoding="utf-8"))
    for entry in record["files"]:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("Thiếu tệp giữ lại: " + entry["path"])
        if path.stat().st_size != entry["bytes"] or checksum(path) != entry["sha256"]:
            raise ValueError("Checksum tệp giữ lại không khớp: " + entry["path"])
    return record


def prepare_readable(store, bid, identity, run_id=None):
    batch = store.get("batches", bid)
    runs = store.list("runs", bid)
    if run_id:
        runs = [r for r in runs if r["id"] == run_id]
        if not runs:
            raise ValueError("Lượt không thuộc job")
    if any(r["status"] in ACTIVE for r in runs):
        raise ValueError("Chờ lượt đang chạy đóng tệp trước khi giữ báo cáo và dữ liệu")
    root = retained_root(store) / bid / identity
    if (root / "artifact-manifest.json").exists():
        verify_retained(root)
        return root
    # Preserve a failed preparation for diagnosis; never overwrite a published snapshot.
    if root.exists():
        root.rename(root.with_name(root.name + "-incomplete-" + str(time.time_ns())))
    root.mkdir(parents=True)
    portable = {**batch, "path": str(root)}
    batch_report(portable, runs)
    batch_report(portable, runs, format="docx")
    for run in runs:
        # Review/failed runs still retain measured histories and settings; only
        # the separate training selection excludes unaccepted samples.
        provenance = root / "run-data" / run["id"]
        for name in ("requested-input.json", "resolved-input.json", "requested-input.csv", "resolved-input.csv"):
            source = Path(run["path"]) / name
            if source.is_file():
                provenance.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, provenance / name)
        for attempt in run.get("attempts", []):
            source = Path(attempt["path"])
            for relative in (
                "raw/model_manifest.json", "actual-input.csv", "extracted/summary.json",
                "extracted/quality.json", "extracted/impact_history.csv",
                "extracted/impact_history.parquet", "solver-complete.json",
            ):
                file = source / relative
                if file.is_file():
                    dest = provenance / f"attempt-{attempt['number']:03d}" / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, dest)
        directories = [("status", Path(run["path"]) / "reports")]
        directories += [
            (f"attempt-{a['number']:03d}", Path(a["path"]) / "reports") for a in run.get("attempts", [])
        ]
        for label, source in directories:
            for path in source.glob("*"):
                if path.is_file() and path.suffix.lower() in (".pdf", ".docx"):
                    target = root / "run-reports" / run["id"] / label / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
    valid = [
        r
        for r in runs
        if r["status"] == "completed"
        and not r.get("test_only")
        and (r.get("quality") or {}).get("ml_eligible")
    ]
    training = root / "training"
    if valid:
        dataset(store, [r["id"] for r in runs], "Dữ liệu huấn luyện " + batch["name"], destination=training)
    else:
        write_json(
            training / "dataset.json",
            {
                "name": batch["name"],
                "samples": 0,
                "run_ids": [],
                "note": "Không có lượt đủ điều kiện huấn luyện; xem job-coverage.csv.",
            },
        )
    selected = json.loads((training / "dataset.json").read_text(encoding="utf-8"))
    write_rows(training / "job-coverage.csv", coverage(runs, set(selected["run_ids"])))
    # Keep inputs and results even for runs excluded from the training set.
    write_json(root / "job.json", batch)
    write_json(root / "runs.json", runs)
    (root / "README.txt").write_text(
        "BÁO CÁO VÀ DỮ LIỆU HUẤN LUYỆN ĐƯỢC GIỮ LẠI\n\n"
        "reports: báo cáo toàn job PDF và DOCX; run-reports: báo cáo từng lượt đã có.\n"
        "training: samples.csv/Parquet, từ điển cột, đường cong và dữ liệu truy vết.\n"
        "Mở PDF và samples.csv trực tiếp trên Drive, không cần tải hoặc giải nén ZIP.\n"
        "job-coverage.csv ghi lượt được nhận và lý do loại; nếu samples=0 thì chưa có mẫu đạt điều kiện.\n"
        "Thư mục này nằm ngoài thư viện mô phỏng. Giữ thư mục *-retained khi dọn dữ liệu.\n"
        "Chỉ dọn dữ liệu mô phỏng sau khi cả ZIP và thư mục tệp riêng đã được xác minh trên Drive.\n",
        encoding="utf-8",
    )
    manifest(
        root,
        {
            "kind": "retained_research_products",
            "batch_id": bid,
            "run_id": run_id,
            "samples": selected["samples"],
            "created_at": now(),
        },
    )
    return root
