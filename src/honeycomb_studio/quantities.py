"""Portable column meanings and units for research datasets."""

from functools import cache

from .models import catalogue


@cache
def input_descriptors():
    return {item["key"]: item for item in catalogue()}


DERIVED_UNITS = {
    "impact_mass": "tonne",
    "velocity": "mm/s",
    "periodic_density_kg_m3": "kg/m³",
    "hex_pitch_y_mm": "mm",
    "hex_cell_height_mm": "mm",
    "impactor_effective_density_tonne_mm3": "tonne/mm³",
}
MEANINGS = {
    "initial_kinetic_energy_J": "ALLKE at first history sample / 1000",
    "peak_raw_contact_force_N": "max m_tonne*(A3+g_mm_s2), guided rigid impactor; no smoothing",
    "peak_force_time_ms": "Time at maximum raw contact force",
    "max_impactor_displacement_mm": "max(-RP.U3) from step start; includes initial gap travel",
    "max_indentation_from_contact_mm": "Impactor travel relative to first contact force above 10 N",
    "max_top_centre_downward_mm": "max(-U3) of top node nearest impact location selected at build",
    "max_bottom_centre_downward_mm": "max(-U3) of bottom node nearest impact location selected at build",
    "contact_duration_ms": "Last minus first history time with contact force >10 N",
    "plastic_dissipation_J": "ALLPD at last history sample /1000",
    "physical_dissipation_J": "ALLPD plus recorded ALLFD (friction), ALLDMD (damage), ALLCD (creep/viscoelastic dissipation) at last sample; excludes artificial and numerical viscosity energy",
    "transferred_energy_at_last_contact_J": "Initial impactor kinetic energy minus kinetic energy at last contact, plus gravity work on impactor",
    "panel_mass_kg": "Finite sandwich mass: two faces and honeycomb, excludes impactor",
    "SEA_J_kg": "Physical dissipation / finite sandwich mass",
    "maximum_energy_balance_drift_percent": "100*max(abs(ETOTAL-ETOTAL[0]))/initial ALLKE",
    "artificial_energy_over_max_internal_percent": "100*max(abs(ALLAE))/max(ALLIE)",
    "contact_force_check_max_relative_percent": "Maximum contact resultant versus m(A3+g) difference normalized by peak contact force",
    "PEEQ_max": "Largest recorded PEEQ across frames, instances, integration and shell section points; location retained in source summary",
    "mises_max_MPa": "Largest ODB von Mises invariant across recorded frames and section points; location retained in source summary",
    "displacement_magnitude_max_mm": "Largest recorded displacement magnitude across all instances, including impactor",
}
PROVENANCE = {
    "run_id",
    "batch_id",
    "design_id",
    "input_hash",
    "split",
    "schema_version",
    "validation_status",
    "numerical_quality",
    "physical_validation",
    "attempt_number",
    "extractor_version",
    "solver_completed",
    "frames",
    "force_method",
}

# One definition source for JSON, the readable CSV and the export guide.
INPUT_MEANINGS = {
    "core_topology": "hexagonal: tổ ong XY đùn theo Z; reentrant_0: ô lõm hình 1 trong XZ, đùn theo Y.",
    "reentrant_cell_height": "Chiều cao bao ô lõm theo Z, đo theo trung diện vách; mặc định 5 mm.",
    "reentrant_indent": "Độ lõm mỗi bên ô theo X; eo ô = cell_size − 2×reentrant_indent.",
    "reentrant_depth_seed": "Kích thước lưới theo chiều sâu Y của lõi ô lõm; chọn custom để sửa.",
    "phase_z": "Dịch pha mạng ô lõm theo Z trước khi cắt theo chiều cao lõi.",
    "panel": "Độ dài cạnh của tấm sandwich vuông.",
    "core_height": "Chiều cao lõi tổ ong, không gồm chiều dày hai tấm mặt.",
    "skin": "Chiều dày tấm mặt trên, phía chịu va đập.",
    "bottom_skin": "Chiều dày tấm mặt dưới sau khi giải quyết giá trị mặc định bằng mặt trên.",
    "cell_size": "Lõi hexagonal: khoảng cách đối diện cạnh; lõi reentrant_0: bề rộng bao ô lõm theo X.",
    "foil": "Chiều dày lá kim loại đơn tạo vách lõi; vách đôi có chiều dày 2×foil.",
    "core_angle": "Góc xoay mạng ô tổ ong trong mặt phẳng tấm.",
    "phase_x": "Độ dịch mạng ô tổ ong theo trục X trước khi cắt theo biên tấm.",
    "phase_y": "Độ dịch mạng ô tổ ong theo trục Y trước khi cắt theo biên tấm.",
    "clamp_mode": "perimeter: chỉ ngàm nút trên bốn cạnh ngoài của hai tấm mặt; circular: ngàm vùng ngoài lỗ tròn. Khóa cả 6 bậc tự do.",
    "clamp_diameter": "Đường kính vùng tròn tự do, chỉ dùng khi clamp_mode=circular.",
    "ball_diameter": "Đường kính đầu va hình cầu cứng; suy ra D=2R khi nhập bán kính.",
    "ball_radius": "Bán kính viên bi; R=D/2. Khối lượng chuyển động được nhập riêng.",
    "velocity_m_s": "Độ lớn vận tốc va chạm (m/s); nhập trực tiếp hoặc suy ra từ v=√(2E/m).",
    "ball_size_mode": "radius: nhập R, suy ra D=2R; diameter: nhập D, suy ra R=D/2.",
    "hex_geometry": "regular: b=l=cell_size/√3, θ=60°; parametric: nhập riêng b, l, θ, suy ra bề rộng ô.",
    "hex_b": "Chiều dài vách đứng b theo hình 7; vách đứng có chiều dày kép 2t.",
    "hex_l": "Chiều dài vách nghiêng l theo hình 7; chiều dày t.",
    "hex_theta_deg": "Góc θ với phương đứng theo hình 7, không phải góc xoay toàn bộ mạng ô core_angle.",
    "mass_kg": "Tổng khối lượng chuyển động của đầu va, dùng để tính động năng và lực quán tính.",
    "energy_J": "Động năng ban đầu: E = 0,5×m×v²; v là độ lớn vận tốc ban đầu, chưa cộng công trọng lực.",
    "impact_x": "Tọa độ X của tâm đầu va so với tâm tấm.",
    "impact_y": "Tọa độ Y của tâm đầu va so với tâm tấm.",
    "gap": "Khe hở ban đầu giữa đáy đầu va và mặt trên của tấm.",
    "gravity": "Độ lớn gia tốc trọng trường theo chiều -Z, tác dụng lên đầu va.",
    "friction": "Hệ số ma sát tiếp xúc; 0 tương ứng không ma sát.",
}
MATERIAL_MEANINGS = {
    "density": "Khối lượng riêng của vật liệu.",
    "young": "Mô đun đàn hồi Young E.",
    "poisson": "Hệ số Poisson ν, không thứ nguyên.",
    "yield_stress": "Ứng suất bắt đầu chảy dẻo σy.",
    "hardening": "Quy luật hóa bền: shifted_ramberg_osgood (Ramberg–Osgood dịch tại chảy), perfect_plastic (dẻo lý tưởng), bilinear (hai đoạn thẳng), table (bảng ứng suất–biến dạng dẻo).",
    "alpha": "Hệ số α, chỉ dùng với shifted_ramberg_osgood: σ = σy×[1 + εp×E/(α×σy)]^(1/n).",
    "exponent": "Số mũ n của shifted_ramberg_osgood; chỉ có tác dụng khi chọn quy luật này.",
    "tangent_ratio": "Tỷ số Et/E, chỉ dùng với bilinear; không có tác dụng khi chọn shifted_ramberg_osgood.",
}
# title, unit, Vietnamese definition; identifiers stay stable for training code.
VI_COLUMNS = {
    "run_id": (
        "Mã lượt mô phỏng",
        "",
        "Định danh lượt mô phỏng; nối với curves/<run_id> và provenance/<run_id>.",
    ),
    "batch_id": ("Mã job", "", "Định danh job chứa lượt mô phỏng."),
    "design_id": (
        "Mã thiết kế vật lý",
        "",
        "Nhóm thiết kế vật lý, loại trừ tải và lưới; các mẫu cùng nhóm được giữ trong cùng một tập chia dữ liệu.",
    ),
    "input_hash": (
        "Mã băm đầu vào",
        "",
        "SHA-256 của đầu vào đã giải quyết; dùng truy vết và loại mẫu trùng, không dùng làm đặc trưng học.",
    ),
    "physical_validation": (
        "Kiểm chứng vật lý",
        "",
        "not_established: chưa xác lập kiểm chứng bằng thực nghiệm; chất lượng số đạt không đồng nghĩa với mô hình vật lý đã được kiểm chứng.",
    ),
    "numerical_quality": (
        "Chất lượng số",
        "",
        "passed: đạt bộ kiểm tra chất lượng số của project; xem quality.json trong provenance để biết tiêu chí và cảnh báo.",
    ),
    "attempt_number": (
        "Số lần chạy",
        "1",
        "Số thứ tự attempt cung cấp kết quả cho mẫu này, không phải số thứ tự lượt trong job.",
    ),
    "extractor_version": (
        "Phiên bản bộ trích xuất",
        "",
        "Phiên bản phần mềm trích xuất dữ liệu từ ODB; dùng truy vết kết quả.",
    ),
    "split": (
        "Tập chia dữ liệu",
        "",
        "train: huấn luyện; validation: hiệu chỉnh; test: đánh giá cuối. Chia theo design_id để tránh rò rỉ giữa các mức tải cùng thiết kế.",
    ),
    "peak_raw_contact_force_N": (
        "Lực tiếp xúc cực đại",
        "N",
        "Cực đại lực thô m_tonne×(A3 + g_mm_s²) của đầu va được dẫn hướng; không làm trơn.",
    ),
    "peak_force_time_ms": (
        "Thời điểm lực cực đại",
        "ms",
        "Thời gian từ đầu bước tại mẫu lịch sử có lực tiếp xúc thô cực đại.",
    ),
    "max_displacement_time_ms": (
        "Thời điểm hành trình cực đại",
        "ms",
        "Thời gian từ đầu bước tại mẫu lịch sử có hành trình đầu va hướng xuống cực đại.",
    ),
    "max_indentation_from_contact_mm": (
        "Hành trình cực đại tính từ tiếp xúc",
        "mm",
        "Hành trình đầu va hướng xuống cực đại, trừ hành trình tại mẫu đầu tiên có lực >10 N; không phải biến dạng dẻo dư.",
    ),
    "max_top_centre_downward_mm": (
        "Độ võng mặt trên cực đại",
        "mm",
        "max(-U3) tại nút mặt trên gần vị trí va nhất được chọn khi dựng mô hình; hướng xuống dương.",
    ),
    "max_bottom_centre_downward_mm": (
        "Độ võng mặt dưới cực đại",
        "mm",
        "max(-U3) tại nút mặt dưới gần vị trí va nhất được chọn khi dựng mô hình; hướng xuống dương.",
    ),
    "end_impactor_velocity_m_s": (
        "Vận tốc đầu va cuối bước",
        "m/s",
        "Vận tốc V3 ở mẫu cuối, đổi từ mm/s sang m/s; dương là hướng lên +Z, âm là hướng xuống.",
    ),
    "contact_duration_ms": (
        "Khoảng thời gian tiếp xúc",
        "ms",
        "Thời điểm cuối trừ thời điểm đầu có lực >10 N; nếu có nhiều đợt tiếp xúc, khoảng này có thể gồm cả khoảng tách rời.",
    ),
    "maximum_energy_balance_drift_percent": (
        "Sai lệch cân bằng năng lượng",
        "%",
        "100×max(|ETOTAL(t)−ETOTAL(0)|)/ALLKE(0), dùng kiểm tra chất lượng số.",
    ),
    "artificial_energy_over_max_internal_percent": (
        "Tỷ lệ năng lượng nhân tạo",
        "%",
        "100×max(|ALLAE|)/max(ALLIE), dùng kiểm tra ảnh hưởng năng lượng nhân tạo.",
    ),
    "physical_dissipation_J": (
        "Năng lượng tiêu tán vật lý",
        "J",
        "Tổng ALLPD và các kênh được ghi ALLFD, ALLDMD, ALLCD tại cuối bước, đổi N·mm sang J; không cộng năng lượng nhân tạo hoặc độ nhớt số.",
    ),
    "panel_mass_kg": (
        "Khối lượng tấm sandwich",
        "kg",
        "Khối lượng hữu hạn của hai tấm mặt và lõi tổ ong, không gồm đầu va.",
    ),
    "SEA_J_kg": (
        "Năng lượng tiêu tán riêng",
        "J/kg",
        "physical_dissipation_J/panel_mass_kg; không mặc định lấy toàn bộ động năng ban đầu làm năng lượng hấp thụ.",
    ),
    "PEEQ_max": (
        "Biến dạng dẻo tương đương cực đại",
        "1",
        "PEEQ lớn nhất trên các frame, instance, điểm tích phân và điểm tiết diện shell đã ghi; vị trí cực trị lưu trong summary nguồn.",
    ),
    "mises_max_MPa": (
        "Ứng suất von Mises cực đại",
        "MPa",
        "Bất biến von Mises lớn nhất trong dữ liệu trường ODB đã ghi; vị trí cực trị lưu trong summary nguồn.",
    ),
}


def describe_column(key: str) -> dict:
    input_key = key.removeprefix("input.")
    input_meta = input_descriptors().get(input_key, {}) if key.startswith("input.") else {}
    unit = input_meta.get("unit", DERIVED_UNITS.get(input_key, ""))
    if not unit:
        for suffix, value in (
            ("_m_s", "m/s"),
            ("_mm_s", "mm/s"),
            ("_kg_m3", "kg/m³"),
            ("_J_kg", "J/kg"),
            ("_MPa", "MPa"),
            ("_percent", "%"),
            ("_mm", "mm"),
            ("_ms", "ms"),
            ("_kg", "kg"),
            ("_N", "N"),
            ("_J", "J"),
            ("_s", "s"),
        ):
            if key.endswith(suffix):
                unit = value
                break
    title = input_meta.get("title", key)
    definition = input_meta.get("description") or MEANINGS.get(key, key.replace("_", " "))
    if key.startswith("input."):
        definition = INPUT_MEANINGS.get(input_key, definition)
        material, _, field = input_key.partition(".")
        if material in ("face_material", "core_material") and field in MATERIAL_MEANINGS:
            prefix = "Vật liệu tấm mặt" if material == "face_material" else "Vật liệu lõi"
            title = prefix + " — " + ("Quy luật hóa bền" if field == "hardening" else title)
            definition = prefix + ": " + MATERIAL_MEANINGS[field]
    elif key in VI_COLUMNS:
        title, unit, definition = VI_COLUMNS[key]
    return {
        "role": "input" if key.startswith("input.") else "provenance" if key in PROVENANCE else "target",
        "title": title,
        "unit": unit or "Không thứ nguyên / phân loại / định danh",
        "definition": definition,
        "source": input_meta.get(
            "source", "Resolved model / ODB histories or fields; input hash and attempt identify source"
        ),
        "missing": "Giá trị thiếu: null trong JSON/Parquet, ô trống trong CSV; không tự điền hoặc thay bằng 0.",
    }
