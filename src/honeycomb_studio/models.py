"""Versioned, unit-explicit inputs; the resolved JSON is the solver contract."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator


def parameter(default: Any, title: str, unit: str = "", source: str = "Numerical choice", **kw):
    return Field(default, title=title, json_schema_extra={"unit": unit, "source": source}, **kw)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Material(StrictModel):
    name: str = "Aluminium"
    density: float = parameter(2700.0, "Khối lượng riêng", "kg/m³", "Paper Table 1", gt=0)
    young: float = parameter(70000.0, "Mô đun đàn hồi", "MPa", "Paper Table 1", gt=0)
    poisson: float = parameter(0.33, "Hệ số Poisson", "", "Paper Table 1", gt=-1, lt=0.5)
    yield_stress: float = parameter(117.0, "Giới hạn chảy", "MPa", "Paper Table 1", gt=0)
    ultimate: float = parameter(
        124.0, "Giới hạn bền (metadata, không xóa phần tử)", "MPa", "Paper Table 1", gt=0
    )
    hardening: Literal["shifted_ramberg_osgood", "perfect_plastic", "bilinear", "table"] = (
        "shifted_ramberg_osgood"
    )
    alpha: float = parameter(3 / 7, "Hệ số Ramberg–Osgood", "", "Paper Eq. 1; shifted at yield", gt=0)
    exponent: float = parameter(10.0, "Số mũ Ramberg–Osgood", "", "Paper Eq. 1", gt=1)
    tangent_ratio: float = parameter(0.7, "Et/E của bilinear", "", "Paper p.23", gt=0, lt=1)
    plastic_table: list[tuple[float, float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_table(self):
        if self.hardening == "table":
            t = self.plastic_table
            if not t or t[0][1] != 0 or any(s <= 0 or e < 0 for s, e in t):
                raise ValueError("Bảng dẻo phải bắt đầu tại biến dạng dẻo 0, stress > 0")
            if any(b[1] <= a[1] or b[0] < a[0] for a, b in zip(t, t[1:], strict=False)):
                raise ValueError("Biến dạng dẻo phải tăng; stress không được giảm")
        return self

    def table(self) -> list[list[float]]:
        if self.hardening == "table":
            return [list(v) for v in self.plastic_table]
        if self.hardening == "perfect_plastic":
            return [[self.yield_stress, 0.0]]
        ep = [0.0] + [10 ** (-6 + i * 6.5 / 160) for i in range(161)]
        if self.hardening == "bilinear":
            h = self.young * self.tangent_ratio / (1 - self.tangent_ratio)
            return [[self.yield_stress + h * e, e] for e in ep]
        return [
            [
                self.yield_stress
                * (1 + e * self.young / (self.alpha * self.yield_stress)) ** (1 / self.exponent),
                e,
            ]
            for e in ep
        ]


class ModelSpec(StrictModel):
    panel: float = parameter(100.0, "Cạnh tấm vuông", "mm", "Paper section 2", gt=0)
    core_height: float = parameter(20.0, "Chiều cao lõi", "mm", "Paper section 3", gt=0)
    skin: float = parameter(0.75, "Chiều dày mặt trên", "mm", "Paper section 3", gt=0)
    bottom_skin: float | None = parameter(None, "Chiều dày mặt dưới (null = bằng mặt trên)", "mm", gt=0)
    cell_size: float = parameter(
        6.35, "Kích thước ô đối diện cạnh", "mm", "Paper; reconstruction convention", gt=0
    )
    foil: float = parameter(0.0635, "Chiều dày foil đơn", "mm", "Paper section 3", gt=0)
    core_angle: float = parameter(0.0, "Góc hướng ô", "deg")
    phase_x: float = parameter(0.0, "Dịch pha ô X", "mm")
    phase_y: float = parameter(0.0, "Dịch pha ô Y", "mm")
    clamp_diameter: float = parameter(76.4, "Đường kính lỗ kẹp", "mm", "Paper section 3", gt=0)
    ball_diameter: float = parameter(13.1, "Đường kính đầu va đập", "mm", "Paper section 2", gt=0)
    impactor_young: Literal[200000] = parameter(
        200000.0,
        "E vật liệu đầu rigid (không chi phối biến dạng rigid)",
        "MPa",
        "Paper section 3; fixed metadata",
    )
    impactor_poisson: float = parameter(
        0.3, "Poisson đầu rigid", "", "Paper section 3; fixed metadata", ge=0.3, le=0.3
    )
    min_segment_length: float = parameter(
        0.05, "Ngưỡng bỏ đoạn vách cực ngắn ở biên", "mm", "Reconstruction geometry tolerance", gt=0, le=0.1
    )
    mass_kg: float = parameter(2.65, "Khối lượng chuyển động", "kg", "Paper section 2", gt=0)
    loading: Literal["energy", "velocity"] = "energy"
    energy_J: float = parameter(7.0, "Năng lượng ban đầu", "J", "Paper Fig.6", gt=0)
    velocity_m_s: float = parameter(2.29848186156091, "Vận tốc ban đầu (độ lớn)", "m/s", gt=0)
    impact_x: float = parameter(0.0, "Vị trí va đập X", "mm")
    impact_y: float = parameter(0.0, "Vị trí va đập Y", "mm")
    gap: float = parameter(0.1, "Khe hở hình học", "mm", "Paper section 3", ge=0)
    gravity: float = parameter(9.81, "Gia tốc trọng trường", "m/s²", ge=0)
    face_material: Material = Field(default_factory=lambda: Material(name="1100-H14"))
    core_material: Material = Field(
        default_factory=lambda: Material(name="3003-H19", yield_stress=220, ultimate=250)
    )
    friction: float = parameter(0.0, "Hệ số ma sát", "", "Paper: frictionless", ge=0)
    tie_tolerance: float = parameter(0.05, "Dung sai Tie", "mm", gt=0)
    skin_self_contact: bool = parameter(False, "Tự tiếp xúc mặt", "", "Reconstruction at 7 J")
    core_self_contact: Literal[True] = True
    perfect_bond: Literal[True] = True
    mesh_preset: Literal["reference", "quick", "fine", "custom"] = "reference"
    core_centre_seed: float = parameter(0.7, "Seed lõi vùng tâm", "mm", "Reference model", gt=0)
    core_outer_seed: float = parameter(1.3, "Seed lõi phía ngoài", "mm", "Reference model", gt=0)
    fine_radius: float = parameter(22.0, "Bán kính tinh lưới lõi", "mm", "Reference model", gt=0)
    skin_centre_seed: float = parameter(0.75, "Seed mặt vùng tâm", "mm", "Reference model", gt=0)
    skin_outer_seed: float = parameter(1.25, "Seed mặt phía ngoài", "mm", "Reference model", gt=0)
    skin_patch_half: float = parameter(12.0, "Nửa cạnh vùng chia mặt", "mm", "Reference model", gt=0)
    core_z_divisions: int = parameter(20, "Số lớp lưới theo chiều cao", "", "Reference model", ge=2, le=200)
    ball_seed: float = parameter(1.0, "Seed đầu va đập", "mm", "Reference model", gt=0)
    shell_points: int = parameter(5, "Điểm tích phân shell Simpson", "", ge=3, le=15)
    shell_element: Literal["S4R/S3R"] = "S4R/S3R"
    duration: float = parameter(0.006, "Thời gian vật lý", "s", "Reference numerical choice", gt=0, le=1)
    cpus: int = parameter(8, "Số CPU", "", ge=1, le=128)
    precision: Literal["double"] = "double"
    mass_scaling: Literal[False] = False
    bulk_linear: float = parameter(0.06, "Bulk viscosity tuyến tính", "", "Abaqus default", ge=0)
    bulk_quadratic: float = parameter(1.2, "Bulk viscosity bậc hai", "", "Abaqus default", ge=0)
    field_intervals: int = parameter(120, "Số khoảng field", "", ge=2, le=10000)
    history_intervals: int = parameter(1200, "Số khoảng history", "", ge=10, le=1000000)
    field_variables: list[str] = Field(
        default_factory=lambda: ["U", "V", "A", "RF", "CSTRESS", "CFORCE", "S", "PE", "PEEQ", "LE"]
    )
    history_variables: list[str] = Field(
        default_factory=lambda: ["ALLAE", "ALLIE", "ALLKE", "ALLPD", "ALLSE", "ALLVD", "ALLWK", "ETOTAL"]
    )

    @model_validator(mode="after")
    def geometry(self):
        if self.clamp_diameter >= self.panel or self.cell_size >= self.clamp_diameter:
            raise ValueError("Lỗ kẹp phải nhỏ hơn tấm, ô phải nhỏ hơn lỗ kẹp")
        if self.foil * 2 >= self.cell_size / 4:
            raise ValueError("Foil quá dày so với ô")
        if abs(self.phase_x) > self.cell_size or abs(self.phase_y) > self.cell_size:
            raise ValueError("Dịch pha giới hạn trong ±một kích thước ô")
        if self.shell_points % 2 != 1:
            raise ValueError("Số điểm Simpson phải lẻ")
        if abs(self.impact_x) + self.skin_patch_half >= self.clamp_diameter / 2 / math.sqrt(2) or abs(
            self.impact_y
        ) + self.skin_patch_half >= self.clamp_diameter / 2 / math.sqrt(2):
            raise ValueError("Vùng tinh lưới mặt phải nằm trong vùng tự do của lỗ kẹp")
        return self

    def resolved(self) -> dict:
        d = self.model_dump()
        if self.mesh_preset != "custom":
            factor = {"reference": 1.0, "quick": 1.4, "fine": 0.8}[self.mesh_preset]
            for key, value in {
                "core_centre_seed": 0.7,
                "core_outer_seed": 1.3,
                "skin_centre_seed": 0.75,
                "skin_outer_seed": 1.25,
                "ball_seed": 1.0,
            }.items():
                d[key] = value * factor
            d["core_z_divisions"] = round(20 / factor)
        d["bottom_skin"] = self.bottom_skin or self.skin
        if self.loading == "energy":
            d["velocity_m_s"] = math.sqrt(2 * self.energy_J / self.mass_kg)
        else:
            d["energy_J"] = 0.5 * self.mass_kg * self.velocity_m_s**2
        d["velocity"] = d["velocity_m_s"] * 1000
        d["impact_mass"] = self.mass_kg / 1000
        d["impactor_effective_density_tonne_mm3"] = (
            2.25e-6 * (d["impact_mass"] / 0.00265) * (13.1 / self.ball_diameter) ** 3
        )
        if self.friction and "ALLFD" not in d["history_variables"]:
            d["history_variables"].append("ALLFD")
        d["side"] = self.cell_size / math.sqrt(3)
        d["periodic_density_kg_m3"] = 8 * self.foil * self.core_material.density / (3 * self.cell_size)
        d["face_plastic_table"] = self.face_material.table()
        d["core_plastic_table"] = self.core_material.table()
        d["units"] = {
            "length": "mm",
            "mass": "tonne",
            "time": "s",
            "force": "N",
            "stress": "MPa",
            "energy": "N.mm",
        }
        d["validation_status"] = "reconstruction_unvalidated"
        return d


class Axis(StrictModel):
    parameter: str
    start: float | None = None
    stop: float | None = None
    step: float | None = None
    values: list[float | str | bool] | None = None
    include_stop: bool = False

    def points(self, limit: int = 10000) -> list[float | str | bool]:
        vals: list[float | str | bool]
        if self.values is not None:
            vals = list(dict.fromkeys(self.values))
        else:
            if self.start is None or self.stop is None or self.step is None:
                raise ValueError("Khoảng cần đủ đầu, cuối, bước")
            a, b, h = map(lambda x: Decimal(str(x)), (self.start, self.stop, self.step))
            if h <= 0 or b < a:
                raise ValueError("Bước phải > 0; cuối phải >= đầu")
            count = int((b - a) // h) + 1
            if count > limit:
                raise ValueError("Quá nhiều điểm; giảm khoảng hoặc tăng bước")
            vals = [float(a + i * h) for i in range(count)]
            if self.include_stop and Decimal(str(vals[-1])) != b:
                vals.append(float(b))
        if (
            not vals
            or len(vals) > limit
            or any(
                (isinstance(x, (float, int)) and not math.isfinite(x)) or isinstance(x, str) and not x
                for x in vals
            )
        ):
            raise ValueError("Danh sách điểm trống, quá dài hoặc không hữu hạn")
        return vals


class BatchSpec(StrictModel):
    schema_version: Literal["1"] = "1"
    name: Annotated[str, Field(min_length=1, max_length=200)] = "Khảo sát honeycomb"
    notes: str = ""
    project_id: str = "research"
    model: ModelSpec = Field(default_factory=ModelSpec)
    sampling: Literal["grid", "lhs", "table"] = "grid"
    axes: list[Axis] = Field(default_factory=list)
    designs: list[dict[str, Any]] = Field(default_factory=list)
    samples: int = Field(32, ge=1, le=10000)
    seed: int = 42
    max_runs: int = Field(1000, ge=1, le=10000)
    runtime_budget_minutes: float = Field(30, gt=0)
    min_free_gb: float = Field(20, ge=1)
    min_available_ram_gb: float = Field(
        2, ge=0.5, description="Available RAM reserve before solver admission"
    )
    render_images: bool = True
    export_all_fields: Literal[True] = True
    backup_after_run: bool = False


def digest(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def set_parameter(data: dict, key: str, value: Any):
    if key.endswith((".ultimate", ".name")):
        raise ValueError(
            "Tên vật liệu và UTS chỉ là metadata; khảo sát E, yield_stress, hardening hoặc bảng dẻo thực tế"
        )
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            raise ValueError("Tham số không tồn tại: " + key)
        node = node[part]
    if parts[-1] not in node:
        raise ValueError("Tham số không tồn tại: " + key)
    node[parts[-1]] = value


def expand(spec: BatchSpec) -> list[dict]:
    keys = [a.parameter for a in spec.axes]
    if len(set(keys)) != len(keys):
        raise ValueError("Một tham số chỉ được khai báo một trục")
    if "energy_J" in keys and "velocity_m_s" in keys:
        raise ValueError("Không quét đồng thời năng lượng và vận tốc")
    for key in keys:
        if (
            key.startswith(("core_", "skin_", "ball_seed")) and "seed" in key or key == "core_z_divisions"
        ) and spec.model.mesh_preset != "custom":
            raise ValueError("Quét lưới cần chọn preset custom")
    if (
        "energy_J" in keys
        and spec.model.loading != "energy"
        or "velocity_m_s" in keys
        and spec.model.loading != "velocity"
    ):
        raise ValueError("Chọn đúng chế độ energy/velocity trước khi quét")
    if spec.sampling == "table":
        overrides = spec.designs
    elif spec.sampling == "lhs":
        from scipy.stats import qmc

        if not spec.axes or any(a.start is None or a.stop is None or a.stop <= a.start for a in spec.axes):
            raise ValueError("LHS cần các khoảng đầu < cuối")
        samples = qmc.LatinHypercube(len(keys), seed=spec.seed).random(spec.samples)
        overrides = [
            dict(
                zip(
                    keys,
                    [
                        cast(float, a.start) + float(x) * (cast(float, a.stop) - cast(float, a.start))
                        for a, x in zip(spec.axes, row, strict=False)
                    ],
                    strict=False,
                )
            )
            for row in samples
        ]
    else:
        points = [a.points() for a in spec.axes]
        if math.prod(map(len, points)) > spec.max_runs:
            raise ValueError("Số tổ hợp vượt max_runs; dùng LHS hoặc giảm trục")
        overrides = [dict(zip(keys, v, strict=False)) for v in itertools.product(*points)]
    if not overrides or len(overrides) > spec.max_runs:
        raise ValueError("Số lượt trống hoặc vượt giới hạn")
    result, seen = [], set()
    for changes in overrides:
        data = spec.model.model_dump()
        for key, value in changes.items():
            set_parameter(data, key, value)
        requested = ModelSpec.model_validate(data)
        resolved = requested.resolved()
        h = digest(resolved)
        if h in seen:
            continue
        seen.add(h)
        design = {
            key: resolved[key]
            for key in (
                "panel",
                "core_height",
                "skin",
                "bottom_skin",
                "cell_size",
                "foil",
                "core_angle",
                "phase_x",
                "phase_y",
                "face_material",
                "core_material",
            )
        }
        for material in ("face_material", "core_material"):
            design[material] = {k: v for k, v in design[material].items() if k not in ("name", "ultimate")}
        for key in (
            "energy_J",
            "velocity_m_s",
            "loading",
            "gap",
            "gravity",
            "mass_kg",
            "ball_diameter",
            "impact_x",
            "impact_y",
            "cpus",
            "duration",
            "field_intervals",
            "history_intervals",
            "mesh_preset",
            "core_centre_seed",
            "core_outer_seed",
            "skin_centre_seed",
            "skin_outer_seed",
            "core_z_divisions",
            "ball_seed",
            "fine_radius",
            "skin_patch_half",
        ):
            design.pop(key, None)
        result.append(
            {
                "requested": requested.model_dump(),
                "resolved": resolved,
                "input_hash": h,
                "design_id": digest(design)[:20],
                "changes": changes,
            }
        )
    return result


def catalogue() -> list[dict]:
    rows = []

    def walk(model, prefix=""):
        for name, f in model.model_fields.items():
            key = prefix + name
            default = getattr(model(), name)
            if isinstance(default, Material):
                walk(Material, key + ".")
                continue
            extra = f.json_schema_extra or {}
            rows.append(
                {
                    "key": key,
                    "title": f.title or name,
                    "unit": extra.get("unit", ""),
                    "source": extra.get("source", "Numerical choice"),
                    "description": f.description or "",
                    "default": default,
                    "type": str(f.annotation),
                    "sweep_allowed": not key.endswith((".ultimate", ".name")) and key != "impactor_poisson",
                }
            )

    walk(ModelSpec)
    return rows
