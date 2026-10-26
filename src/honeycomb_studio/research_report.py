"""Five-page Vietnamese report, distinct from the machine-readable archive."""

import json
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

from .research import TARGETS

LABELS = {
    "panel_mass_kg": ("Khối lượng tấm sandwich", "kg"),
    "peak_raw_contact_force_N": ("Lực tiếp xúc cực đại", "N"),
    "max_top_centre_downward_mm": ("Độ võng tâm mặt trên cực đại", "mm"),
    "max_bottom_centre_downward_mm": ("Độ võng tâm mặt dưới cực đại", "mm"),
    "max_indentation_from_contact_mm": ("Hành trình đầu va tính từ tiếp xúc cực đại", "mm"),
    "physical_dissipation_J": ("Năng lượng tiêu tán vật lý tại cuối bước", "J"),
    "SEA_J_kg": ("Năng lượng tiêu tán riêng SEA", "J/kg"),
    "contact_duration_ms": ("Khoảng thời gian lực tiếp xúc trên 10 N", "ms"),
    "peak_force_time_ms": ("Thời điểm lực cực đại", "ms"),
    "max_displacement_time_ms": ("Thời điểm hành trình đầu va cực đại", "ms"),
    "end_impactor_velocity_m_s": ("Vận tốc đầu va cuối bước (+Z hướng lên)", "m/s"),
    "PEEQ_max": ("Biến dạng dẻo tương đương cực đại PEEQ", "1"),
    "mises_max_MPa": ("Ứng suất von Mises cực đại", "MPa"),
    "maximum_energy_balance_drift_percent": ("Sai lệch cân bằng năng lượng cực đại", "%"),
    "artificial_energy_over_max_internal_percent": ("Năng lượng nhân tạo / nội năng cực đại", "%"),
}


def number(value):
    if value is None:
        return "Chưa có dữ liệu"
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, (float, int)):
        return format(value, ".5g").replace(".", ",")
    return str(value)


def material_plot(model, destination):
    fig, ax = plt.subplots(figsize=(8, 3), layout="constrained")
    for key, label in (("face_plastic_table", "Tấm mặt"), ("core_plastic_table", "Lõi honeycomb")):
        points = model[key]
        ax.plot([p[1] for p in points], [p[0] for p in points], label=label, lw=1.5)
    ax.set(
        xlabel="Biến dạng dẻo tương đương (không thứ nguyên)",
        ylabel="Ứng suất thực (MPa)",
        title="Đường cong dẻo thực sự đưa vào Abaqus",
    )
    ax.grid(alpha=0.2)
    ax.legend()
    fig.savefig(destination, dpi=170)
    plt.close(fig)


def build(run, attempt: Path, rows, checkpoint=None, format="pdf"):
    from .reports import footer, plots, styles, table

    styles_ = styles()
    model, summary, quality = run["resolved"], run["summary"], run["quality"]
    figures, output = attempt / "figures", attempt / "reports"
    output.mkdir(parents=True, exist_ok=True)
    plots(rows, figures)
    material_plot(model, figures / "material-curves.png")
    story = []

    def text(value, style="BodyText"):
        story.append(Paragraph(escape(value), styles_[style]))

    def grid(values, widths=(305, 140, 78)):
        story.append(table([[number(x) for x in row] for row in values], list(widths)))

    text("BÁO CÁO VA ĐẬP HONEYCOMB", "Title")
    smoke = quality.get("physical_validation") == "environment_smoke_only" or summary.get("data_profile") == "smoke"
    if smoke:
        text("SMOKE — KIỂM TRA MÔI TRƯỜNG", "Heading1")
        text("Bài chạy ngắn để kiểm tra phần mềm. Không phải dữ liệu nghiên cứu, không dùng cho huấn luyện hoặc kết luận hấp thụ năng lượng.")
    text("1. Kết quả chính và điều kiện tải", "Heading1")
    text("Lượt " + str(run.get("index", 1)) + " | Mã truy vết: " + run["id"])
    metrics = [key for key in TARGETS if key not in ("end_impactor_velocity_m_s",)]
    grid(
        [["Đại lượng", "Giá trị", "Đơn vị"]]
        + [
            [
                *LABELS[key][:1],
                summary.get(key, summary.get("field_extrema", {}).get(key, {}).get("value")),
                LABELS[key][1],
            ]
            for key in metrics
        ]
    )
    text("Điều kiện tải và hình học chính", "Heading2")
    grid(
        [
            ["Thông số", "Giá trị", "Đơn vị"],
            [
                "Năng lượng / vận tốc ban đầu",
                f"{number(model['energy_J'])} / {number(model['velocity_m_s'])}",
                "J / m/s",
            ],
            [
                "Khối lượng / đường kính đầu va",
                f"{number(model['mass_kg'])} / {number(model['ball_diameter'])}",
                "kg / mm",
            ],
            [
                "Cạnh tấm / cao lõi / cỡ ô",
                " / ".join(number(model[k]) for k in ("panel", "core_height", "cell_size")),
                "mm",
            ],
            [
                "Mặt trên / mặt dưới / foil đơn",
                " / ".join(number(model[k]) for k in ("skin", "bottom_skin", "foil")),
                "mm",
            ],
        ]
    )
    text(
        "Chất lượng số: "
        + ("đạt các ngưỡng kiểm tra" if quality.get("numerical_quality") == "passed" else "cần xem xét")
        + (". Phạm vi: chỉ kiểm tra môi trường, loại khỏi dữ liệu huấn luyện." if smoke else ". Hội tụ và tương đương thí nghiệm: chưa xác nhận. Dữ liệu dùng cho khảo sát trong miền mô hình đã giả định.")
    )
    for finding in quality.get("findings", []):
        text("Cần xem xét: " + finding)
    text(
        "Ngưỡng tham khảo: sai lệch năng lượng 1%; năng lượng nhân tạo 5%. Các cực đại được lấy trên mẫu đã ghi, không phải cực đại liên tục theo thời gian."
    )

    story.append(PageBreak())
    text("2. Vật liệu, lưới và giả định", "Heading1")
    materials = [model["face_material"], model["core_material"]]
    names = {
        "shifted_ramberg_osgood": "Ramberg-Osgood dịch chuyển",
        "bilinear": "Song tuyến tính",
        "table": "Bảng thực nghiệm",
        "perfect_plastic": "Dẻo lý tưởng",
    }
    values = [["Thông số", "Tấm mặt", "Lõi honeycomb"]]
    for label, key in (
        ("Vật liệu", "name"),
        ("Khối lượng riêng (kg/m³)", "density"),
        ("Mô đun Young (MPa)", "young"),
        ("Hệ số Poisson", "poisson"),
        ("Giới hạn chảy (MPa)", "yield_stress"),
        ("Mô hình hóa bền", "hardening"),
        ("Hệ số alpha", "alpha"),
        ("Số mũ n", "exponent"),
    ):

        def used(material):
            if key in ("alpha", "exponent") and material["hardening"] != "shifted_ramberg_osgood":
                return "Không sử dụng"
            return names.get(str(material.get(key)), material.get(key))

        values.append([label, *[used(m) for m in materials]])
    grid(values, (220, 151, 152))
    story.append(Image(str(figures / "material-curves.png"), width=510, height=191))
    text(
        "Đồ thị vẽ từ bảng ứng suất thực - biến dạng dẻo đã dùng, kể cả khi nguồn là hàm giải tích. Bảng điểm đầy đủ được giữ trong resolved-input.json/CSV, không in lại trong PDF."
    )
    grid(
        [
            ["Thiết lập", "Giá trị", "Đơn vị"],
            [
                "Lõi: seed tâm / ngoài",
                f"{number(model['core_centre_seed'])} / {number(model['core_outer_seed'])}",
                "mm",
            ],
            [
                "Mặt: seed tâm / ngoài",
                f"{number(model['skin_centre_seed'])} / {number(model['skin_outer_seed'])}",
                "mm",
            ],
            [
                "Bán kính tinh lưới / số lớp lõi",
                f"{number(model['fine_radius'])} / {model['core_z_divisions']}",
                "mm / lớp",
            ],
            ["Phần tử / số điểm tích phân shell", f"{model['shell_element']} / {model['shell_points']}", ""],
            [
                "Thời gian vật lý / số CPU",
                f"{number(model['duration'] * 1000)} / {model['cpus']}",
                "ms / CPU",
            ],
        ]
    )
    text(
        f"Hệ số ma sát {number(model['friction'])}; liên kết mặt-lõi lý tưởng; đầu va được dẫn hướng. Mô hình hiện tại không mô tả đứt gãy hoặc tách lớp. Trường hợp cuối bước còn tiếp xúc chưa phải trạng thái đã hồi phục hoàn toàn."
    )

    story.append(PageBreak())
    text("3. Đáp ứng va đập và phân bố năng lượng", "Heading1")
    for file, caption in (
        ("force_displacement.png", "Lực - hành trình đầu va tính từ đầu bước; bao gồm khe hở ban đầu."),
        (
            "energies.png",
            "Năng lượng theo thời gian: ALLPD là tiêu tán dẻo; ALLAE và ALLVD được kiểm tra riêng, không gộp thành hấp thụ vật lý.",
        ),
    ):
        from PIL import Image as PILImage

        with PILImage.open(figures / file) as image:
            width, height = image.size
        story.append(Image(str(figures / file), width=510, height=min(225, 510 * height / width)))
        text(caption)
        story.append(Spacer(1, 10))
    components = summary.get("physical_dissipation_components_J", {})
    recorded = [f"{key} = {number(value)} J" for key, value in components.items() if value is not None]
    text("Thành phần tiêu tán được ghi: " + "; ".join(recorded) + ".")
    text(
        "Nếu chỉ ghi ALLPD, giá trị tiêu tán vật lý hiện tính bằng ALLPD; các cơ chế không được ghi không được suy diễn thành số 0. ALLCD là tiêu tán do creep/nhớt vật liệu; ALLDMD là tiêu tán do hư hỏng, không phải giảm chấn."
    )
    text(
        "SEA = năng lượng tiêu tán vật lý / khối lượng sandwich; lực được lấy từ m(A3 + g) cho đầu va dẫn hướng. Không dùng nội năng ALLIE như nhãn hấp thụ chung."
    )

    manifest = figures / "render-manifest.json"
    rendered = (
        json.loads(manifest.read_text(encoding="utf-8")).get("figures", []) if manifest.exists() else []
    )
    for page, (stage, title) in enumerate(
        (("peak_force", "4. Trạng thái gần lực cực đại"), ("final", "5. Trạng thái cuối bước"))
    ):
        story.append(PageBreak())
        text(title, "Heading1")
        selected = [
            ("U", "full", "Chuyển vị U3 toàn mô hình (mm)"),
            ("S", "core", "Ứng suất von Mises lõi (MPa)"),
            ("PEEQ", "core", "Biến dạng dẻo tương đương lõi (1)"),
        ]
        cells = []
        for variable, view, caption in selected:
            file = figures / f"{stage}_{variable}_{view}.png"
            entry = next((x for x in rendered if x["file"] == file.name), None)
            if not file.exists():
                cells.append([Paragraph(escape(caption + ": chưa có ảnh"), styles_["BodyText"])])
                continue
            width = 510 if variable == "U" else 250
            from PIL import Image as PILImage

            with PILImage.open(file) as image:
                w, h = image.size
            cell = [
                Paragraph(escape(caption), styles_["Heading2"]),
                Image(str(file), width=width, height=width * h / w),
            ]
            if entry:
                cell.append(
                    Paragraph(
                        "Thời gian frame: " + number(entry["time_s"] * 1000) + " ms; biến dạng x1.",
                        styles_["Normal"],
                    )
                )
            cells.append(cell)
        story.extend(cells[0])
        story.append(Table([[cells[1], cells[2]]], colWidths=[261, 261]))
        text(
            "Giữ cả thời điểm lực cực đại và hành trình cực đại trong bảng kết quả; chỉ chọn một bộ ảnh đỉnh để tránh lặp. Cuối bước là thời điểm kết thúc mô phỏng, không tự xác nhận kết cấu đã hết dao động."
        )
        if page == 1:
            text(
                "Hồ sơ kiểm tra: resolved-input.json/CSV, extracted/summary.json, quality.json, impact_history.csv/Parquet và ODB gốc. Bảng ML mỗi lượt một dòng nằm trong samples.csv/Parquet; các file trường nút/phần tử chỉ xuất ở chế độ lưu trữ đầy đủ."
            )
    if format == "docx":
        from .word_report import save_story

        return save_story(story, output / "run-report.docx")
    document = SimpleDocTemplate(
        str(output / "run-report.pdf"),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=30,
        bottomMargin=36,
        title="Báo cáo va đập honeycomb",
    )
    if checkpoint:
        document.afterFlowable = lambda _: checkpoint(0, 0)  # ty: ignore[invalid-assignment] # ReportLab callback.
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return str(output / "run-report.pdf")
