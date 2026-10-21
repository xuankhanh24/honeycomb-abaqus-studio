from __future__ import annotations

import json
import threading
from functools import wraps
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from .data import write_rows
from .store import now

REPORT_LOCK = threading.RLock()


def serialized(function):
    @wraps(function)
    def call(*args, **kwargs):
        with REPORT_LOCK:
            return function(*args, **kwargs)

    return call


def input_rows(data, prefix=""):
    result = []
    for key, value in data.items():
        if key.endswith("plastic_table"):
            continue
        if isinstance(value, dict):
            result.extend(input_rows(value, prefix + key + "."))
        else:
            result.append(
                [prefix + key, json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value]
            )
    return result


def styles():
    if "Vietnamese" not in pdfmetrics.getRegisteredFontNames():
        candidates = [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf",
        ]
        pdfmetrics.registerFont(TTFont("Vietnamese", str(next(p for p in candidates if p.exists()))))
    s = getSampleStyleSheet()
    for name in ("Normal", "BodyText", "Heading1", "Heading2", "Heading3", "Title"):
        s[name].fontName = "Vietnamese"
    s["Normal"].fontSize = 8
    s["Normal"].leading = 11
    s["BodyText"].fontSize = 9
    s["BodyText"].leading = 13
    return s


def table(rows, widths=None):
    s = styles()
    cells = [[Paragraph(escape(str(x)) if x is not None else "—", s["Normal"]) for x in row] for row in rows]
    if widths:
        available = A4[0] - 72
        if sum(widths) > available:
            widths = [w * available / sum(widths) for w in widths]
    t = LongTable(cells, colWidths=widths, repeatRows=1, hAlign="LEFT", splitInRow=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7edf4")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#66788a")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
            ]
        )
    )
    return t


def footer(canvas, doc):
    canvas.setFont("Vietnamese", 8)
    canvas.drawString(36, 22, "Honeycomb Abaqus Studio · Dữ liệu có thể truy vết · " + str(doc.page))


def plots(rows: list[dict], directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    time = [r["time_ms"] for r in rows]
    configs = [
        (
            "force_time",
            "Lực tiếp xúc – thời gian",
            time,
            [r["contact_force_N"] for r in rows],
            "Thời gian (ms)",
            "Lực (N)",
        ),
        (
            "displacement_time",
            "Chuyển vị viên – thời gian",
            time,
            [r["impactor_displacement_mm"] for r in rows],
            "Thời gian (ms)",
            "Chuyển vị xuống (mm)",
        ),
        (
            "velocity_time",
            "Vận tốc viên – thời gian",
            time,
            [r["velocity_mm_s"] / 1000 for r in rows],
            "Thời gian (ms)",
            "Vận tốc theo Z (m/s)",
        ),
        (
            "force_displacement",
            "Lực – chuyển vị viên",
            [r["impactor_displacement_mm"] for r in rows],
            [r["contact_force_N"] for r in rows],
            "Chuyển vị từ đầu bước (mm)",
            "Lực (N)",
        ),
    ]
    for filename, title, x, y, xlabel, ylabel in configs:
        fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
        ax.plot(x, y, color="#165a9c", lw=1.2)
        ax.set(title=title, xlabel=xlabel, ylabel=ylabel)
        ax.grid(alpha=0.2)
        fig.savefig(directory / (filename + ".png"), dpi=170)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
    for key in ("ALLKE", "ALLIE", "ALLPD", "ALLSE", "ALLAE", "ALLVD", "ALLWK", "ETOTAL"):
        ax.plot(time, [r[key + "_J"] for r in rows], label=key, lw=1)
    ax.set(xlabel="Thời gian (ms)", ylabel="Năng lượng (J)", title="Thành phần năng lượng (dữ liệu thô)")
    ax.legend(ncol=4, fontsize=8)
    ax.grid(alpha=0.2)
    fig.savefig(directory / "energies.png", dpi=170)
    plt.close(fig)


@serialized
def run_report(run: dict, attempt: Path, rows: list[dict], checkpoint=None):
    s = styles()
    figs = attempt / "figures"
    plots(rows, figs)
    out = attempt / "reports"
    out.mkdir(parents=True, exist_ok=True)
    story = [
        Paragraph("Báo cáo mô phỏng honeycomb", s["Title"]),
        Paragraph(escape(run["id"]), s["BodyText"]),
        Paragraph(
            "Bản tái dựng chưa xác nhận hội tụ hoặc tương đương thí nghiệm. Solver hoàn tất không đồng nghĩa kiểm chứng vật lý.",
            s["BodyText"],
        ),
        Spacer(1, 12),
    ]
    story.append(Paragraph("Kết quả và chất lượng", s["Heading1"]))
    summary = run["summary"]
    story.append(
        table(
            [["Đại lượng", "Giá trị"]]
            + [[k, v] for k, v in summary.items() if not isinstance(v, (dict, list))],
            [265, 258],
        )
    )
    story.append(Paragraph(escape(json.dumps(run["quality"], ensure_ascii=False)), s["BodyText"]))
    if summary.get("field_extrema"):
        story.append(Paragraph("Cực trị trường và vị trí", s["Heading2"]))
        story.append(
            table(
                [["Đại lượng", "Giá trị", "Vị trí"]]
                + [
                    [
                        k,
                        v["value"],
                        f"{v['instance']} · frame {v['frame']} · node {v['node_label']} / element {v['element_label']} · IP {v['integration_point']} · SP {v['section_point']}",
                    ]
                    for k, v in summary["field_extrema"].items()
                ],
                [180, 90, 253],
            )
        )
    if summary.get("physical_dissipation_components_J"):
        story.append(
            table(
                [["Thành phần tiêu tán", "J (null = không ghi)"]]
                + list(summary["physical_dissipation_components_J"].items()),
                [300, 223],
            )
        )
    story.append(PageBreak())
    story.append(Paragraph("Toàn bộ input thực tế", s["Heading1"]))

    def flatten(d, prefix=""):
        result = []
        for key, value in d.items():
            if key.endswith("plastic_table"):
                continue
            if isinstance(value, dict):
                result.extend(flatten(value, prefix + key + "."))
            else:
                result.append(
                    [
                        prefix + key,
                        json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value,
                    ]
                )
        return result

    story.append(
        table([["Tham số (đơn vị trong tên/manifest)", "Giá trị"]] + flatten(run["resolved"]), [255, 268])
    )
    actual = attempt / "raw" / "model_manifest.json"
    if actual.exists():
        story.append(Paragraph("Thông số đo từ mô hình dựng", s["Heading2"]))
        values = json.loads(actual.read_text())
        story.append(
            table(
                [["Thông số", "Giá trị"]]
                + input_rows(
                    {
                        k: v
                        for k, v in values.items()
                        if k not in run["resolved"] or v != run["resolved"].get(k)
                    }
                ),
                [255, 268],
            )
        )
    for key in ("face_plastic_table", "core_plastic_table"):
        story.append(Paragraph("Bảng dẻo: " + key, s["Heading2"]))
        story.append(
            table(
                [["True stress (MPa)", "Plastic strain"]]
                + [["%.9g" % a, "%.9g" % b] for a, b in run["resolved"][key]],
                [260, 263],
            )
        )
    story.append(PageBreak())
    story.append(Paragraph("Đường cong và ảnh mô phỏng", s["Heading1"]))
    for image in sorted(figs.glob("*.png")):
        if checkpoint:
            checkpoint(0, 0)
        from PIL import Image as PILImage

        with PILImage.open(image) as im:
            w, h = im.size
        unit = (
            " · mm"
            if "_U_" in image.stem
            else " · MPa"
            if "_S_" in image.stem
            else " · không thứ nguyên"
            if "PEEQ" in image.stem
            else ""
        )
        story.append(
            KeepTogether(
                [
                    Paragraph(escape(image.stem + unit), s["Heading3"]),
                    Image(str(image), width=510, height=510 * h / w),
                    Spacer(1, 8),
                ]
            )
        )
    inventory = attempt / "extracted" / "inventory.json"
    if inventory.exists():
        data = json.loads(inventory.read_text())
        field_names = sorted(set(f["field"] for f in data["fields"]))
        story.append(Paragraph("Catalogue output đầy đủ", s["Heading1"]))
        story.append(
            table(
                [["Field", "Số frame có dữ liệu", "Tổng giá trị"]]
                + [
                    [
                        name,
                        sum(f["field"] == name for f in data["fields"]),
                        sum(f["rows"] for f in data["fields"] if f["field"] == name),
                    ]
                    for name in field_names
                ],
                [250, 130, 143],
            )
        )
    if summary.get("field_statistics"):
        story.append(Paragraph("Thống kê mọi trường đã ghi", s["Heading1"]))
        story.append(
            Paragraph(
                "Min/max/mean của các mẫu output trên toàn bộ frame; không phải trung bình tích phân theo thời gian. Component giữ quy ước tọa độ ODB.",
                s["BodyText"],
            )
        )
        values = [["Field / component", "Đơn vị", "Min", "Max", "Mean", "Mẫu hữu hạn"]]
        for field, stats in summary["field_statistics"].items():
            for i, component in enumerate(stats["components"]):
                values.append(
                    [
                        field + " / " + component,
                        stats["unit"],
                        *[
                            "%.6g" % stats[k][i] if stats[k][i] is not None else None
                            for k in ("min", "max", "mean")
                        ],
                        stats["count"][i],
                    ]
                )
        story.append(table(values, [160, 55, 77, 77, 77, 77]))
        story.append(
            Paragraph(
                "Dữ liệu từng nút/phần tử, integration point, section point và frame nằm trong Parquet đi kèm. Ảnh giữ biến dạng tỷ lệ 1.0; frame gần cực đại được chọn từ các frame đã lưu.",
                s["BodyText"],
            )
        )
    dest = out / "run-report.pdf"
    document = SimpleDocTemplate(
        str(dest), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36, title=run["id"]
    )
    if checkpoint:
        document.afterFlowable = lambda _: checkpoint(0, 0)  # ty: ignore[invalid-assignment] # ReportLab per-document callback.
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return str(dest)


@serialized
def incomplete_report(run: dict):
    s = styles()
    out = Path(run["path"]) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    story = [
        Paragraph("Báo cáo trạng thái lượt mô phỏng", s["Title"]),
        Paragraph(escape(run["id"]) + " · " + escape(now()), s["BodyText"]),
        Paragraph(
            "Trạng thái: "
            + escape(run["status"])
            + ". Kết quả còn thiếu được ghi là chưa có; báo cáo này không xác nhận mô phỏng đã hoàn tất.",
            s["BodyText"],
        ),
    ]
    if run.get("error"):
        story.append(Paragraph(escape(run["error"]), s["BodyText"]))
    story.append(table([["Input thực tế", "Giá trị"]] + input_rows(run["resolved"]), [260, 263]))
    for key in ("face_plastic_table", "core_plastic_table"):
        story.append(Paragraph(key, s["Heading2"]))
        story.append(table([["True stress (MPa)", "Plastic strain"]] + run["resolved"][key], [260, 263]))
    story.append(Paragraph("Lịch sử attempt", s["Heading2"]))
    story.append(
        table(
            [["Attempt", "Bắt đầu", "Kết thúc", "Lỗi"]]
            + [
                [a["number"], a.get("started_at"), a.get("ended_at"), a.get("error")] for a in run["attempts"]
            ],
            [45, 145, 145, 188],
        )
    )
    dest = out / "status-report.pdf"
    SimpleDocTemplate(
        str(dest), pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return str(dest)


@serialized
def batch_report(batch: dict, runs: list[dict]):
    s = styles()
    out = Path(batch["path"]) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    story = [
        Paragraph(escape(batch["name"]), s["Title"]),
        Paragraph("Báo cáo toàn job · " + escape(now()), s["BodyText"]),
    ]
    rows = []
    for run in runs:
        row = {
            "run_id": run["id"],
            "status": run["status"],
            "changes": run.get("changes", {}),
            "input_hash": run["input_hash"],
            "design_id": run["design_id"],
            **(run.get("summary") or {}),
        }
        rows.append(row)
    write_rows(Path(batch["path"]) / "run-index.csv", rows)
    import pyarrow as pa
    import pyarrow.parquet as pq

    flattened = [
        {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()}
        for r in rows
    ]
    if flattened:
        pq.write_table(
            pa.Table.from_pylist(flattened), Path(batch["path"]) / "run-index.parquet", compression="zstd"
        )
    story.append(
        table(
            [["Lượt", "Trạng thái", "E (J)", "Fmax (N)", "Umax (mm)", "SEA (J/kg)"]]
            + [
                [
                    r["index"],
                    r["status"],
                    r["resolved"]["energy_J"],
                    (r.get("summary") or {}).get("peak_raw_contact_force_N"),
                    (r.get("summary") or {}).get("max_top_centre_downward_mm"),
                    (r.get("summary") or {}).get("SEA_J_kg"),
                ]
                for r in runs
            ],
            [45, 110, 75, 100, 100, 100],
        )
    )
    completed = [r for r in runs if r.get("summary")]
    if completed:
        fig, axs = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
        for r in completed:
            a = r["summary"]
            e = r["resolved"]["energy_J"]
            axs[0].scatter(e, a["peak_raw_contact_force_N"], label=str(r["index"]))
            axs[1].scatter(e, a["max_top_centre_downward_mm"])
        axs[0].set(xlabel="Năng lượng (J)", ylabel="Lực đỉnh (N)")
        axs[1].set(xlabel="Năng lượng (J)", ylabel="Độ võng mặt trên (mm)")
        for ax in axs:
            ax.grid(alpha=0.2)
        fig.savefig(out / "comparison.png", dpi=170)
        plt.close(fig)
        story.append(Image(str(out / "comparison.png"), width=690, height=276))
        # Overlay raw histories in bounded groups so legends remain readable.
        for first in range(0, len(completed), 12):
            subset = completed[first : first + 12]
            fig, axs = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
            for run in subset:
                if not run["attempts"]:
                    continue
                source = Path(run["attempts"][-1]["path"]) / "extracted" / "impact_history.csv"
                if not source.exists():
                    continue
                import csv

                with source.open(encoding="utf-8-sig", newline="") as f:
                    curve = list(csv.DictReader(f))
                t = [float(r["time_ms"]) for r in curve]
                force = [float(r["contact_force_N"]) for r in curve]
                u = [float(r["impactor_displacement_mm"]) for r in curve]
                label = f"Lượt {run['index']}; {run['resolved']['energy_J']:.3g} J"
                axs[0].plot(t, force, label=label, lw=0.9)
                axs[1].plot(u, force, label=label, lw=0.9)
            axs[0].set(xlabel="Thời gian (ms)", ylabel="Lực (N)")
            axs[1].set(xlabel="Chuyển vị viên từ đầu bước (mm)", ylabel="Lực (N)")
            for ax in axs:
                ax.grid(alpha=0.2)
                ax.legend(fontsize=7, ncol=2)
            file = out / f"curves-{first:05d}.png"
            fig.savefig(file, dpi=160)
            plt.close(fig)
            story.append(Image(str(file), width=690, height=251))
        # Physical comparisons are conditioned on the same loading, never across E.
        from .data import pareto
        from .models import digest

        groups = {}
        for run in completed:
            if not (run.get("quality") or {}).get("ml_eligible"):
                continue
            load = {
                k: run["resolved"][k]
                for k in ("energy_J", "mass_kg", "ball_diameter", "impact_x", "impact_y", "gravity", "gap")
            }
            group = groups.setdefault(digest(load)[:12], {"load": load, "runs": []})
            group["runs"].append({"index": run["index"], **run["summary"]})
        for gid, group in groups.items():
            valid = [
                r
                for r in group["runs"]
                if r.get("panel_mass_kg") is not None and r.get("SEA_J_kg") is not None
            ]
            if len(valid) < 2:
                continue
            front = pareto(valid)
            fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
            ax.scatter(
                [r["panel_mass_kg"] * 1000 for r in valid],
                [r["SEA_J_kg"] for r in valid],
                label="Thiết kế đủ chất lượng số",
            )
            ax.scatter(
                [r["panel_mass_kg"] * 1000 for r in front],
                [r["SEA_J_kg"] for r in front],
                marker="x",
                s=70,
                label="Pareto (4 mục tiêu)",
            )
            for r in valid:
                ax.annotate(str(r["index"]), (r["panel_mass_kg"] * 1000, r["SEA_J_kg"]), fontsize=8)
            ax.set(
                xlabel="Khối lượng sandwich (g)",
                ylabel="SEA (J/kg)",
                title=f"Cùng tải {group['load']['energy_J']:.3g} J; chi tiết điều kiện trong input",
            )
            ax.legend()
            ax.grid(alpha=0.2)
            file = out / f"pareto-{gid}.png"
            fig.savefig(file, dpi=160)
            plt.close(fig)
            story.append(Image(str(file), width=620, height=310))
            if len(valid) >= 4:
                import numpy as np
                from scipy.stats import spearmanr

                by_index = {r["index"]: r for r in completed}
                features = ["skin", "bottom_skin", "core_height", "cell_size", "foil", "core_angle"]
                features = [
                    k for k in features if len({by_index[r["index"]]["resolved"][k] for r in valid}) > 1
                ]
                targets = [
                    "panel_mass_kg",
                    "SEA_J_kg",
                    "peak_raw_contact_force_N",
                    "max_top_centre_downward_mm",
                ]
                if features:
                    coefficients = np.full((len(features), len(targets)), np.nan)
                    for i, k in enumerate(features):
                        x = [by_index[r["index"]]["resolved"][k] for r in valid]
                        for j, t in enumerate(targets):
                            y = [r[t] for r in valid]
                            if len(set(y)) > 1:
                                coefficients[i, j] = float(spearmanr(x, y).statistic)
                    fig, ax = plt.subplots(figsize=(10, max(3, len(features) * 0.5)), layout="constrained")
                    mesh = ax.imshow(coefficients, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
                    ax.set_xticks(range(len(targets)), labels=targets, rotation=15, ha="right", fontsize=8)
                    ax.set_yticks(range(len(features)), labels=features)
                    ax.set_title("Tương quan hạng Spearman trong cùng điều kiện tải")
                    fig.colorbar(mesh, ax=ax, label="rho; không phải quan hệ nhân quả")
                    file = out / f"sensitivity-{gid}.png"
                    fig.savefig(file, dpi=160)
                    plt.close(fig)
                    story.append(
                        KeepTogether(
                            [
                                Paragraph(
                                    "Độ nhạy thăm dò: tương quan, chưa kiểm soát tương tác/confounding; chỉ có ý nghĩa trong miền mẫu.",
                                    s["BodyText"],
                                ),
                                Image(str(file), width=690, height=690 * max(3, len(features) * 0.5) / 10),
                            ]
                        )
                    )
                    write_rows(
                        out / f"sensitivity-{gid}.csv",
                        [
                            {
                                "feature": k,
                                "target": t,
                                "spearman_rho": float(coefficients[i, j])
                                if np.isfinite(coefficients[i, j])
                                else None,
                                "samples": len(valid),
                                "load_group": gid,
                            }
                            for i, k in enumerate(features)
                            for j, t in enumerate(targets)
                        ],
                    )
    if runs:
        story.append(PageBreak())
        story.append(Paragraph("Input mô hình nền và cấu hình job", s["Heading1"]))
        story.append(
            table(
                [["Thiết lập job", "Giá trị"]]
                + [
                    [k, json.dumps(v, ensure_ascii=False)]
                    for k, v in batch["spec"].items()
                    if k not in ("model", "axes", "designs")
                ],
                [220, 480],
            )
        )
        story.append(
            Paragraph(
                "Danh sách trục/bảng thiết kế đầy đủ nằm trong batch.json; toàn bộ input thực tế và thay đổi từng lượt được ghi dưới đây.",
                s["BodyText"],
            )
        )
        story.append(
            table([["Input thực tế lượt đầu", "Giá trị"]] + input_rows(runs[0]["resolved"]), [280, 420])
        )
        for key in ("face_plastic_table", "core_plastic_table"):
            story.append(Paragraph(key + " · stress MPa / plastic strain", s["Heading2"]))
            story.append(
                table([["True stress (MPa)", "Plastic strain"]] + runs[0]["resolved"][key], [350, 350])
            )
    story.append(Paragraph("Phụ lục từng lượt", s["Heading1"]))
    for r in runs:
        story.append(Paragraph(escape(r["id"]), s["Heading2"]))
        story.append(
            Paragraph(
                "Input thay đổi: " + escape(json.dumps(r.get("changes", {}), ensure_ascii=False)),
                s["BodyText"],
            )
        )
        story.append(
            Paragraph(
                "Input đầy đủ: runs/"
                + escape(r["id"])
                + "/resolved-input.json. Báo cáo chi tiết nằm trong reports của từng attempt.",
                s["BodyText"],
            )
        )
        if r.get("error"):
            story.append(Paragraph(escape(r["error"]), s["BodyText"]))
        if r.get("quality"):
            story.append(Paragraph(escape(json.dumps(r["quality"], ensure_ascii=False)), s["BodyText"]))
        baseline = dict(input_rows(runs[0]["resolved"])) if runs else {}
        differences = [[k, v] for k, v in input_rows(r["resolved"]) if baseline.get(k) != v]
        if differences:
            story.append(table([["Input khác lượt nền", "Giá trị"]] + differences, [300, 400]))
        for key in ("face_plastic_table", "core_plastic_table"):
            if runs and r["resolved"][key] != runs[0]["resolved"][key]:
                story.append(Paragraph(key + " · bảng của lượt " + str(r["index"]), s["Heading3"]))
                story.append(
                    table([["True stress (MPa)", "Plastic strain"]] + r["resolved"][key], [350, 350])
                )
        if r.get("summary"):
            story.append(
                table(
                    [["Output", "Giá trị"]]
                    + [[k, v] for k, v in r["summary"].items() if not isinstance(v, (dict, list))],
                    [300, 400],
                )
            )
        if r.get("attempts"):
            story.append(
                table(
                    [["Attempt", "Bắt đầu UTC", "Kết thúc UTC", "Thời gian từng giai đoạn (s)"]]
                    + [
                        [a["number"], a.get("started_at"), a.get("ended_at"), a.get("durations", {})]
                        for a in r["attempts"]
                    ],
                    [60, 180, 180, 280],
                )
            )
    dest = out / "batch-report.pdf"
    SimpleDocTemplate(
        str(dest), pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return str(dest)
