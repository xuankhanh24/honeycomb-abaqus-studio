"""Vietnamese batch report sections with unit-labelled actual inputs and results."""

import json
from collections import Counter
from xml.sax.saxutils import escape

from reportlab.platypus import PageBreak, Paragraph

from .models import catalogue
from .research_report import LABELS


def append_overview(story, batch, runs):
    from .reports import status_label, styles

    s = styles()
    counts = Counter(r["status"] for r in runs)
    eligible = sum(
        bool((r.get("quality") or {}).get("ml_eligible"))
        and not r.get("test_only")
        and r["status"] == "completed"
        for r in runs
    )
    story.append(Paragraph("Phạm vi và chất lượng dữ liệu", s["Heading1"]))
    story.append(
        Paragraph(
            f"Tổng số {len(runs)} lượt mô phỏng. "
            + escape("; ".join(f"{status_label(k)}: {v}" for k, v in counts.items()))
            + f". Có {eligible} lượt đạt điều kiện chất lượng số để xét xuất dữ liệu huấn luyện. "
            "Các lượt trùng đầu vào được gộp khi tạo dữ liệu. Chất lượng số không thay thế kiểm chứng thí nghiệm. "
            "Ô chưa có dữ liệu không được xem là giá trị bằng không.",
            s["BodyText"],
        )
    )
    if batch.get("spec", {}).get("notes"):
        story.append(Paragraph(escape(batch["spec"]["notes"]), s["BodyText"]))


def append_inputs(story, runs):
    from functools import partial

    from .reports import input_rows, styles
    from .reports import table as report_table

    s = styles()
    table = partial(report_table, max_width=769)
    story.append(PageBreak())
    story.append(Paragraph("Thông số đầu vào thực tế", s["Heading1"]))
    known = {p["key"]: p for p in catalogue()}
    extra = {
        "loading": ("Cách xác định tải", ""),
        "core_self_contact": ("Tự tiếp xúc lõi", ""),
        "perfect_bond": ("Liên kết mặt và lõi lý tưởng", ""),
        "mesh_preset": ("Cấu hình lưới", ""),
        "shell_element": ("Loại phần tử vỏ", ""),
        "precision": ("Độ chính xác solver", ""),
        "mass_scaling": ("Điều chỉnh khối lượng số", ""),
        "field_variables": ("Biến trường xuất ra", ""),
        "history_variables": ("Biến lịch sử xuất ra", ""),
        "impact_mass": ("Khối lượng đầu va trong hệ đơn vị solver", "tonne"),
        "velocity": ("Vận tốc đầu va trong hệ đơn vị solver", "mm/s"),
        "impactor_effective_density_tonne_mm3": ("Khối lượng riêng hiệu dụng đầu va", "tonne/mm³"),
        "side": ("Cạnh ô lục giác", "mm"),
        "periodic_density_kg_m3": ("Khối lượng riêng lõi tuần hoàn", "kg/m³"),
        "validation_status": ("Trạng thái kiểm chứng mô hình", ""),
    }
    for key, (title, unit) in extra.items():
        known[key] = {"title": title, "unit": unit}
    for prefix, label in (("face_material", "mặt"), ("core_material", "lõi")):
        for key, title in (("name", "Tên vật liệu"), ("hardening", "Mô hình hóa bền")):
            known[f"{prefix}.{key}"] = {"title": title, "unit": ""}
        for key, info in known.items():
            if key.startswith(prefix + "."):
                info["title"] += " " + label
    flattened = [dict(input_rows(r["resolved"])) for r in runs]
    keys = list(dict.fromkeys(k for row in flattened for k in row if not k.startswith("units.")))
    common, varying = [], []
    for key in keys:
        values = [row.get(key) for row in flattened]
        if len({json.dumps(v, ensure_ascii=False, sort_keys=True) for v in values}) == 1:
            info = known.get(key, {})
            translated = {
                "energy": "Theo năng lượng",
                "velocity": "Theo vận tốc",
                "reference": "Tham chiếu",
                "quick": "Nhanh",
                "fine": "Mịn",
                "custom": "Tùy chỉnh",
                "double": "Chính xác kép",
                "shifted_ramberg_osgood": "Ramberg-Osgood dịch chuyển",
                "bilinear": "Song tuyến tính",
                "table": "Bảng thực nghiệm",
                "perfect_plastic": "Dẻo lý tưởng",
                "reconstruction_unvalidated": "Mô hình tái dựng chưa kiểm chứng",
            }.get(str(values[0]), values[0])
            common.append([info.get("title", key), translated, info.get("unit", ""), key])
        else:
            varying.append(key)
    story.append(
        Paragraph(
            "Thông số dùng chung được ghi một lần; thông số thay đổi được ghi theo từng lượt. "
            "Bao gồm hình học, vật liệu, điều kiện va đập, tiếp xúc, lưới và thiết lập solver. "
            "Bảng dẻo đầy đủ giữ tại resolved-input.json/CSV của mỗi lượt.",
            s["BodyText"],
        )
    )
    if common:
        story.append(
            table([["Thông số dùng chung", "Giá trị", "Đơn vị", "Mã tham số"]] + common, [310, 150, 65, 244])
        )
    for first in range(0, len(varying), 4):
        subset = varying[first : first + 4]
        headings = ["Lượt"] + [
            known.get(k, {}).get("title", k)
            + (" (" + known[k]["unit"] + ")" if known.get(k, {}).get("unit") else "")
            for k in subset
        ]
        story.append(
            table(
                [headings]
                + [
                    [r["index"]] + [flat.get(k) for k in subset]
                    for r, flat in zip(runs, flattened, strict=True)
                ],
                [40] + [120] * len(subset),
            )
        )


def append_results(story, runs):
    from functools import partial

    from .reports import styles
    from .reports import table as report_table

    s = styles()
    table = partial(report_table, max_width=769)
    story.append(PageBreak())
    story.append(Paragraph("Kết quả và kiểm tra chất lượng từng lượt", s["Heading1"]))
    for first in range(0, len(runs), 5):
        if first:
            story.append(PageBreak())
        subset = runs[first : first + 5]
        rows = [["Đại lượng và đơn vị"] + [f"Lượt {r['index']}" for r in subset]]
        for key, (label, unit) in LABELS.items():
            values = []
            for run in subset:
                summary = run.get("summary") or {}
                value = summary.get(key, summary.get("field_extrema", {}).get(key, {}).get("value"))
                values.append(value)
            rows.append([label + (f" ({unit})" if unit else "")] + values)
        rows.append(
            ["Đủ điều kiện dữ liệu huấn luyện"]
            + [
                bool((r.get("quality") or {}).get("ml_eligible"))
                and not r.get("test_only")
                and r["status"] == "completed"
                for r in subset
            ]
        )
        story.append(table(rows, [220] + [90] * len(subset)))
    for run in runs:
        findings = (run.get("quality") or {}).get("findings", [])
        detail = f"Lượt {run['index']} · {run['id']} · Mã đầu vào {run['input_hash']}"
        story.append(Paragraph(escape(detail), s["Normal"]))
        for finding in findings:
            story.append(Paragraph(escape("Cần xem xét: " + str(finding)), s["BodyText"]))
