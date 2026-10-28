"""One auditable training table across jobs, using the existing quality selection."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .data import dataset, manifest, write_data_dictionary, write_rows
from .research import FEATURES, PROVENANCE, TARGETS
from .retained import coverage
from .store import now, write_json


def training_paths(archive):
    """Download only original settings and extracted histories, never the large ODB."""
    names = {"run.json", "requested-input.json", "resolved-input.json",
             "impact_history.csv", "impact_history.parquet", "all_histories.parquet"}
    return [f["path"] for f in archive["files"]
            if "/runs/" in f["path"] and Path(f["path"]).name in names]


def collect_runs(root: Path):
    runs = []
    for file in sorted(root.glob("projects/*/batches/*/runs/*/run.json")):
        run = json.loads(file.read_text(encoding="utf-8"))
        if run["id"] != file.parent.name:
            raise ValueError("Run identity differs from its archived directory")
        run["path"] = str(file.parent)
        for attempt in run.get("attempts", []):
            number = attempt["number"]
            if type(number) is not int or number < 1:
                raise ValueError("Invalid attempt number")
            attempt["path"] = str(file.parent / "attempts" / f"{number:03d}")
        runs.append(run)
    return runs


class CollectionStore:
    def __init__(self, runs, root):
        self.root = root
        self.runs = {r["id"]: r for r in runs}
        if len(self.runs) != len(runs):
            raise ValueError("Duplicate run identity across archives")

    def get(self, kind, identity):
        if kind != "runs":
            raise ValueError("Only archived runs are available")
        return self.runs[identity]


def build_collection(sources, out: Path):
    """Sources carry human-readable job names, immutable archive URLs and restored runs."""
    out.mkdir(parents=True, exist_ok=False)
    runs = [run for source in sources for run in source.get("runs", [])]
    store = CollectionStore(runs, out)
    training = out / "01_training"
    valid = [r for r in runs if r.get("status") == "completed" and not r.get("test_only")
             and (r.get("quality") or {}).get("ml_eligible")]
    if valid:
        dataset(store, [r["id"] for r in runs], "Tổng hợp tất cả job cloud", destination=training)
    else:
        columns = [*sorted(PROVENANCE), *("input." + k for k in FEATURES), *TARGETS]
        training.mkdir()
        table = pa.table({k: pa.array([], type=pa.string()) for k in columns})
        pq.write_table(table, training / "samples.parquet", compression="zstd")
        # A header-only CSV explicitly represents zero accepted samples.
        import csv

        with (training / "samples.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
        write_data_dictionary(training, columns)
        write_json(training / "dataset.json", {
            "samples": 0, "run_ids": [], "features": ["input." + k for k in FEATURES],
            "targets": TARGETS, "split_counts": {k: 0 for k in ("train", "validation", "test")},
            "note": "Chưa có mẫu đạt điều kiện. Không dùng bảng rỗng để huấn luyện.",
        })
    meta = json.loads((training / "dataset.json").read_text(encoding="utf-8"))
    audit = out / "02_audit"
    if runs:
        write_rows(audit / "run-selection.csv", coverage(runs, set(meta["run_ids"])))
    else:
        audit.mkdir(parents=True)
        (audit / "run-selection.csv").write_text("run_id,index,included,reason\n", encoding="utf-8")
    index = []
    job_numbers = {identity: i for i, identity in enumerate(dict.fromkeys(s["job_id"] for s in sources), 1)}
    for source in sources:
        i = job_numbers[source["job_id"]]
        folder = f"job-{i:04d}_{source['job_id']}"
        index.append({k: v for k, v in source.items() if k != "runs"} | {"folder": folder})
        for run in source.get("runs", []):
            dest = out / "03_simulations" / folder / run["id"]
            for name, payload in (("input/requested.json", run.get("requested")),
                                  ("input/resolved.json", run["resolved"]),
                                  ("output/summary.json", run.get("summary", {})),
                                  ("output/quality.json", run.get("quality", {}))):
                write_json(dest / name, payload)
            for attempt in run.get("attempts", []):
                for name in ("impact_history.csv", "impact_history.parquet", "all_histories.parquet"):
                    src = Path(attempt["path"]) / "extracted" / name
                    if src.is_file():
                        target = dest / "output" / f"attempt-{attempt['number']:03d}" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, target)
    write_json(audit / "source-jobs.json", index)
    write_json(audit / "input-output-contract.json", {
        "X": meta["features"], "y_candidates": meta["targets"],
        "provenance_do_not_train_on": sorted(PROVENANCE), "split_column": "split",
        "missing_values": "Ô trống/null là thiếu dữ liệu, không thay bằng 0.",
        "target_selection": "Chọn y theo bài toán; các chỉ số kiểm tra chất lượng chỉ dùng lọc/đánh giá.",
    })
    (out / "README.md").write_text(
        "# Bộ dữ liệu mô phỏng tổng hợp\n\n"
        "## Bắt đầu ở đâu?\n\n"
        "- `01_training/samples.csv`: bảng huấn luyện chung; mỗi dòng là một đầu vào duy nhất đạt chất lượng.\n"
        "- `01_training/samples.parquet`: cùng dữ liệu, giữ kiểu và nén tốt hơn cho Python.\n"
        "- `01_training/dataset.json`: số mẫu, danh sách X/y và cách chia train/validation/test.\n"
        "- `01_training/data-dictionary.csv` và `FIELD_DESCRIPTIONS.md`: tên, đơn vị và ý nghĩa từng cột.\n"
        "- `02_audit/run-selection.csv`: từng lượt được nhận hoặc lý do bị loại.\n"
        "- `02_audit/source-jobs.json`: tên bài, ID và liên kết kho gốc; ghi cả bài thiếu dữ liệu.\n"
        "- `03_simulations/job-0001_<ID>/<run-id>/input/`: requested.json (yêu cầu), resolved.json (đầu vào thực tế).\n"
        "- `03_simulations/.../output/`: summary.json (kết quả), quality.json (chất lượng), đường cong theo attempt.\n\n"
        "## Đầu vào và đầu ra\n\n"
        "**Mô phỏng:** đầu vào gồm hình học (mm), vật liệu, ngàm, tải (J hoặc m/s), lưới và thời gian (s). "
        "Đầu ra gồm lực (N), chuyển vị (mm), năng lượng (J), ứng suất (MPa), đường cong theo thời gian và kiểm tra chất lượng.\n\n"
        "**Huấn luyện:** X là các cột `input.*` có trong `dataset.json.features`; "
        "y được chọn từ `dataset.json.targets`, ví dụ `peak_raw_contact_force_N`, "
        "`max_top_centre_downward_mm`, `SEA_J_kg`. Không đưa ID, split hoặc kết quả y vào X. "
        "Các đại lượng phân loại cần mã hóa; giá trị thiếu cần xử lý riêng. "
        "Không tự coi các chỉ số sai số/năng lượng nhân tạo là mục tiêu vật lý.\n\n"
        "Chỉ lấy lượt completed, ml_eligible=true, không phải test_only; smoke/review không dùng huấn luyện. "
        "Khử trùng theo input_hash trên toàn bộ job, chia theo design_id toàn cục để tránh rò rỉ giữa các tập. "
        "Dùng cột split có sẵn; không chia ngẫu nhiên lại từng dòng. "
        "Không có mẫu đạt thì CSV chỉ có tiêu đề và samples=0. "
        "ODB/CAE/INP dung lượng lớn vẫn ở release gốc được dẫn trong source-jobs.json.\n",
        encoding="utf-8",
    )
    summary = {"samples": meta["samples"], "runs": len(runs), "sources": len(sources),
               "unavailable_sources": sum(bool(s.get("excluded_reason")) for s in sources), "created_at": now()}
    write_json(out / "collection.json", summary)
    manifest(out)
    return summary
