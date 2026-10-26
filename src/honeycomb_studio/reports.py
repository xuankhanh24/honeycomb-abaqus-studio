from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
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
    if "VietnameseBold" not in pdfmetrics.getRegisteredFontNames():
        bold = Path("C:/Windows/Fonts/arialbd.ttf")
        if not bold.exists():
            bold = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans-Bold.ttf"
        pdfmetrics.registerFont(TTFont("VietnameseBold", str(bold)))
    s = getSampleStyleSheet()
    for name in ("Normal", "BodyText", "Heading1", "Heading2", "Heading3", "Title"):
        s[name].fontName = "Vietnamese"
    s["Normal"].fontSize = 8
    s["Normal"].leading = 11
    s["BodyText"].fontSize = 9
    s["BodyText"].leading = 13
    for name, size, leading in (
        ("Title", 20, 25),
        ("Heading1", 14, 19),
        ("Heading2", 11, 15),
        ("Heading3", 10, 13),
    ):
        s[name].fontName = "VietnameseBold"
        s[name].fontSize = size
        s[name].leading = leading
        s[name].textColor = colors.black
    return s


def table(rows, widths=None, max_width=None):
    s = styles()
    from .research_report import number

    cells = [[Paragraph(escape(number(x)), s["Normal"]) for x in row] for row in rows]
    if widths:
        available = max_width or A4[0] - 72
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
    energy_labels = {
        "ALLKE": "Động năng",
        "ALLIE": "Nội năng",
        "ALLPD": "Tiêu tán dẻo",
        "ALLSE": "Đàn hồi",
        "ALLAE": "Năng lượng nhân tạo",
        "ALLVD": "Nhớt số",
        "ALLWK": "Công ngoại lực",
        "ETOTAL": "Tổng năng lượng",
    }
    for key, label in energy_labels.items():
        ax.plot(time, [r[key + "_J"] for r in rows], label=label + " (" + key + ")", lw=1)
    ax.set(xlabel="Thời gian (ms)", ylabel="Năng lượng (J)", title="Thành phần năng lượng (dữ liệu thô)")
    ax.legend(ncol=2, fontsize=7)
    ax.grid(alpha=0.2)
    fig.savefig(directory / "energies.png", dpi=170)
    plt.close(fig)


@serialized
def run_report(run: dict, attempt: Path, rows: list[dict], checkpoint=None, format="pdf"):
    from .research_report import build

    return build(run, attempt, rows, checkpoint, format=format)


@serialized
def incomplete_report(run: dict, format="pdf"):
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
    if format == "docx":
        from .word_report import save_story

        return save_story(story, out / "status-report.docx")
    dest = out / "status-report.pdf"
    SimpleDocTemplate(
        str(dest), pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return str(dest)


@serialized
def batch_report(batch: dict, runs: list[dict], format="pdf"):
    s = styles()
    out = Path(batch["path"]) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    story = [
        Paragraph("Báo cáo tổng hợp mô phỏng honeycomb", s["Title"]),
        Paragraph(escape(batch["name"]), s["Heading1"]),
        Paragraph(
            "Mã job: "
            + escape(batch["id"])
            + " · Xuất lúc "
            + datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M UTC+7"),
            s["BodyText"],
        ),
    ]
    from .batch_details import append_inputs, append_overview, append_results

    if batch.get("spec", {}).get("data_profile") == "smoke":
        story.append(Paragraph("SMOKE — KIỂM TRA MÔI TRƯỜNG", s["Heading1"]))
        story.append(Paragraph("Bài chạy ngắn, không phải dữ liệu nghiên cứu và không dùng cho huấn luyện hoặc kết luận hấp thụ năng lượng.", s["BodyText"]))

    append_overview(story, batch, runs)
    from .research import TARGETS

    rows = []
    for run in runs:
        row = {
            "run_id": run["id"],
            "status": run["status"],
            "changes": run.get("changes", {}),
            "input_hash": run["input_hash"],
            "design_id": run["design_id"],
            **{k: v for k, v in (run.get("summary") or {}).items() if k in TARGETS},
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
                    status_label(r["status"]),
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
        story.append(PageBreak())
        story.append(Paragraph("Biểu đồ so sánh và đường cong mô phỏng", s["Heading1"]))
        fig, axs = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
        for r in completed:
            a = r["summary"]
            e = r["resolved"]["energy_J"]
            if a.get("peak_raw_contact_force_N") is not None:
                axs[0].scatter(e, a["peak_raw_contact_force_N"], label=str(r["index"]))
            if a.get("max_top_centre_downward_mm") is not None:
                axs[1].scatter(e, a["max_top_centre_downward_mm"])
        axs[0].set(xlabel="Năng lượng (J)", ylabel="Lực đỉnh (N)")
        axs[1].set(xlabel="Năng lượng (J)", ylabel="Độ võng mặt trên (mm)")
        for ax in axs:
            ax.grid(alpha=0.2)
        fig.savefig(out / "comparison.png", dpi=170)
        plt.close(fig)
        story.append(Image(str(out / "comparison.png"), width=690, height=276))
        # Overlay raw histories in bounded groups so legends remain readable.
        from .history_sources import load_history

        history_sources = []
        for first in range(0, len(completed), 12):
            subset = completed[first : first + 12]
            available, missing = [], []
            for run in subset:
                history = load_history(run)
                if history:
                    available.append((run, history))
                    history_sources.append(
                        {
                            "run_id": run["id"],
                            "attempt": run["attempts"][-1]["number"] if run["attempts"] else None,
                            "source": str(history["path"]),
                            "kind": history["kind"],
                            "samples": len(history["rows"]),
                        }
                    )
                else:
                    missing.append(str(run["index"]))
                    history_sources.append({"run_id": run["id"], "source": None, "samples": 0})
            if missing:
                story.append(
                    Paragraph(
                        "Chưa có đường cong gốc hợp lệ cho lượt "
                        + ", ".join(missing)
                        + ". Cần khôi phục dữ liệu lịch sử; không suy diễn đường cong từ các chỉ số cực đại.",
                        s["BodyText"],
                    )
                )
            if not available:
                continue
            fig, axs = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
            for run, history in available:
                curve = history["rows"]
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
                if ax.get_legend_handles_labels()[0]:
                    ax.legend(fontsize=7, ncol=2)
            file = out / f"curves-{first:05d}.png"
            fig.savefig(file, dpi=160)
            plt.close(fig)
            story.append(Image(str(file), width=660, height=240))
            recovered = [str(run["index"]) for run, history in available if history["kind"] != "attempt"]
            if recovered:
                story.append(
                    Paragraph(
                        "Đường cong gốc của lượt "
                        + ", ".join(recovered)
                        + " được đọc từ bản giữ lại hoặc dataset, đúng mã lượt và attempt.",
                        s["Normal"],
                    )
                )
        from .store import write_json

        write_json(out / "history-sources.json", history_sources)
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
    append_inputs(story, runs)
    append_results(story, runs)
    if format == "docx":
        from .word_report import save_story

        return save_story(story, out / "batch-report.docx", landscape=True)
    dest = out / "batch-report.pdf"
    SimpleDocTemplate(
        str(dest), pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return str(dest)


def status_label(value):
    return {
        "completed": "Hoàn tất",
        "failed": "Lỗi",
        "interrupted": "Bị dừng",
        "queued": "Đang chờ",
        "review": "Cần xem xét",
        "solving": "Đang giải",
    }.get(value, value)
