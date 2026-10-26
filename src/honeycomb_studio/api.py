from __future__ import annotations

import asyncio
import csv
import json
import os
import secrets
import shutil
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .backup import DriveBackup
from .contracts import PUBLIC_CONTRACTS
from .data import archive, dataset, pareto, write_rows
from .engine import Engine
from .estimates import predict, records
from .execution import execution_plan
from .models import BatchSpec, ModelSpec, catalogue, expand
from .reports import batch_report, incomplete_report, run_report
from .solver import command, tail
from .store import Store, write_json


class ReferenceRequest(BaseModel):
    path: str
    model: ModelSpec = Field(default_factory=ModelSpec)
    render: bool = True


class DatasetRequest(BaseModel):
    run_ids: list[str]
    name: str = "Honeycomb dataset"
    seed: int = 42
    features: list[str] | None = None
    targets: list[str] | None = None


class PathRequest(BaseModel):
    path: str


class RestoreRequest(BaseModel):
    file_id: str
    sha256: str


def make_app(store: Store, engine: Engine, token: str, config_dir: Path, start_worker=True) -> FastAPI:
    backup = DriveBackup(store, config_dir)
    engine.backup = backup
    operations = {}

    def brief(run):
        result = {**run}
        result["resolved"] = {
            k: v for k, v in run["resolved"].items() if k not in ("face_plastic_table", "core_plastic_table")
        }
        for key in ("face_material", "core_material"):
            if key in result["resolved"]:
                result["resolved"][key] = {
                    k: v for k, v in result["resolved"][key].items() if k != "plastic_table"
                }
        result.pop("requested", None)
        result["summary"] = {
            k: v for k, v in (run.get("summary") or {}).items() if not isinstance(v, (dict, list))
        }
        result["attempts"] = [{k: v for k, v in a.items() if k not in ("process",)} for a in run["attempts"]]
        return result

    def artifact_list(run):
        root = Path(run["path"])
        entries: list[dict[str, Any]] = []
        complete = True
        for file in root.glob("*"):
            if file.is_file():
                entries.append({"path": file.name, "bytes": file.stat().st_size})
        for attempt in run["attempts"]:
            base = Path(attempt["path"])
            path = base / "artifact-manifest.json"
            if path.exists():
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                entries.extend(
                    {"path": base.relative_to(root).as_posix() + "/" + item["path"], "bytes": item["bytes"]}
                    for item in snapshot["files"]
                )
            else:
                complete = False
                for directory in ("raw", "logs", "reports", "figures", "extracted"):
                    entries.extend(
                        {"path": file.relative_to(root).as_posix(), "bytes": file.stat().st_size}
                        for file in (base / directory).glob("*")
                        if file.is_file()
                    )
        entries.sort(
            key=lambda e: (0 if Path(e["path"]).suffix in (".pdf", ".cae", ".odb", ".inp") else 1, e["path"])
        )
        return entries, complete

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            engine.start_worker()
        yield
        # Closing the UI does not stop the engine. Server shutdown does not kill
        # owned solver processes; persisted ownership supports later adoption.
        engine.shutdown.set()

    app = FastAPI(title="Honeycomb Studio local engine", version="0.2.0", lifespan=lifespan)
    app.state.store = store
    app.state.engine = engine

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.path != "/health" and not secrets.compare_digest(
            request.headers.get("X-Honeycomb-Token", ""), token
        ):
            return JSONResponse({"detail": "Local session token required"}, status_code=401)
        try:
            return await call_next(request)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    def operation(kind, fn):
        identity = secrets.token_hex(8)
        operations[identity] = {"id": identity, "kind": kind, "status": "running"}

        def work():
            try:
                operations[identity].update(status="completed", result=fn())
            except Exception as exc:
                operations[identity].update(status="failed", error=str(exc))

        threading.Thread(target=work, daemon=True, name=kind).start()
        return operations[identity]

    @app.get("/health")
    def health():
        return {
            "service": "honeycomb-studio",
            "version": "0.2.0",
            "capabilities": ["readable_backup", "batch_dataset_export", "docx_reports", "reentrant_core_0deg"],
        }

    @app.post("/v1/engine/shutdown")
    def shutdown_engine():
        if any(op["status"] == "running" for op in operations.values()) or backup.tasks.unfinished_tasks:
            raise ValueError("Chờ thao tác xuất dữ liệu/backup hoàn tất trước khi khởi động lại engine")
        if engine.current_run is not None or any(
            r["status"]
            in {
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
            for r in store.list("runs")
        ):
            raise ValueError("Dừng/chờ lượt đang thực thi trước khi khởi động lại engine")
        engine.shutdown.set()
        callback = getattr(app.state, "request_shutdown", None)
        if callback:
            callback()
        return {"shutting_down": True}

    @app.get("/v1/status")
    def status():
        disk = shutil.disk_usage(store.root)
        vm = psutil.virtual_memory()
        return {
            "data_root": str(store.root),
            "abaqus": engine.abaqus,
            "test_solver": engine.fake,
            "disk_free_gb": disk.free / 1e9,
            "disk_total_gb": disk.total / 1e9,
            "ram_available_gb": vm.available / 1e9,
            "ram_total_gb": vm.total / 1e9,
            "logical_cpus": os.cpu_count(),
            "batches": len(store.list("batches")),
            "runs": len(store.list("runs")),
            "backup": backup.status(),
            "worker_alive": bool(engine.worker and engine.worker.is_alive()),
            "current_run_id": engine.current_run,
            "current_run_ids": sorted(engine.current_runs),
        }

    @app.get("/v1/template")
    def template():
        return {
            "spec": BatchSpec(model=ModelSpec(clamp_mode="perimeter", hex_geometry="parametric", ball_size_mode="radius")).model_dump(),
            "parameters": catalogue(),
            "schema": BatchSpec.model_json_schema(),
            "presets": {
                "reference": {"validated": False, "label": "Theo mô hình tham chiếu"},
                "quick": {"validated": False, "label": "Khảo sát nhanh — chưa hội tụ"},
                "fine": {"validated": False, "label": "Lưới tinh — chưa hội tụ"},
            },
        }

    @app.get("/v1/contracts")
    def contracts():
        return {name: contract.model_json_schema() for name, contract in PUBLIC_CONTRACTS.items()}

    @app.post("/v1/resolve")
    def resolve(spec: ModelSpec):
        return spec.resolved()

    @app.post("/v1/preview")
    def preview(spec: BatchSpec):
        runs = expand(spec)
        calibration = records(store)
        entries: list[dict[str, Any]] = []
        for i, r in enumerate(runs):
            p = r["resolved"]
            entries.append(
                {
                    "index": i + 1,
                    "input_hash": r["input_hash"],
                    "design_id": r["design_id"],
                    "changes": r["changes"],
                    "energy_J": p["energy_J"],
                    "velocity_m_s": p["velocity_m_s"],
                    "ball_radius_mm": p["ball_radius"],
                    "ball_diameter_mm": p["ball_diameter"],
                    "periodic_density_kg_m3": p["periodic_density_kg_m3"],
                    "hex_b_mm": p["hex_b"] if p["core_topology"] == "hexagonal" else None,
                    "hex_l_mm": p["hex_l"] if p["core_topology"] == "hexagonal" else None,
                    "hex_theta_deg": p["hex_theta_deg"] if p["core_topology"] == "hexagonal" else None,
                    "mass_kg": p["mass_kg"],
                    "skin_mm": p["skin"],
                    "core_height_mm": p["core_height"],
                    "cell_size_mm": p["cell_size"],
                    "core_topology": p["core_topology"],
                    "core_cell_plane": p.get("core_cell_plane", "XY"),
                    "foil_mm": p["foil"],
                    "estimate": predict(p, calibration),
                }
            )
        # Before calibration this is expressly a reference-based estimate.
        estimate_minutes = sum(e["estimate"]["solver_minutes"] for e in entries)
        return {
            "runs": entries,
            "count": len(runs),
            "execution": execution_plan(spec.model_dump(), [r["resolved"] for r in runs],
                                        psutil.cpu_count() or 1, psutil.virtual_memory().available / 1024**3,
                                        shutil.disk_usage(store.root).free / 1e9),
            "estimated_solver_minutes": estimate_minutes,
            "estimated_raw_odb_gb": sum(e["estimate"]["raw_odb_gb"] for e in entries),
            "estimated_other_phases_minutes": sum(
                sum(e["estimate"]["other_phase_minutes"].values()) for e in entries
            ),
            "storage_note": "Parquet, CAE, ảnh, PDF, scratch và backup cần thêm chỗ; dùng datacheck/lịch sử để hiệu chỉnh.",
            "runtime_note": "Ước tính theo mẫu tham chiếu; không đảm bảo 20–30 phút với mọi hình học.",
            "warnings": [
                "Mô hình chưa được xác nhận hội tụ",
                *(
                    ["Ngân sách thời gian mỗi lượt dưới ước tính tham chiếu"]
                    if any(e["estimate"]["solver_minutes"] > spec.runtime_budget_minutes for e in entries)
                    else []
                ),
            ],
        }

    @app.post("/v1/batches")
    def create(spec: BatchSpec):
        return store.create(spec)

    @app.get("/v1/batches")
    def batches():
        result = []
        for b in store.list("batches"):
            runs = store.list("runs", b["id"])
            counts = {state: sum(r["status"] == state for r in runs) for state in {r["status"] for r in runs}}
            done = sum(counts.get(s, 0) for s in ("completed", "review", "failed"))
            result.append({**b, "counts": counts, "completed_percent": 100 * done / len(runs) if runs else 0})
        return result

    @app.get("/v1/batches/{bid}")
    def batch(bid: str, full_inputs: bool = False):
        rows = store.list("runs", bid)
        return {**store.get("batches", bid), "runs": rows if full_inputs else [brief(r) for r in rows]}

    @app.post("/v1/batches/{bid}/{action}")
    def control(bid: str, action: Literal["start", "resume", "stop", "pause_after_current"]):
        return engine.control(bid, action)

    @app.get("/v1/runs")
    def runs(q: str = "", status: str = ""):
        return [
            brief(r)
            for r in store.list("runs")
            if (
                not q
                or q.casefold()
                in json.dumps(
                    {"id": r["id"], "changes": r.get("changes"), "resolved": r["resolved"]},
                    ensure_ascii=False,
                ).casefold()
            )
            and (not status or r["status"] == status)
        ]

    @app.get("/v1/runs/{rid}")
    def run(rid: str):
        r = store.get("runs", rid)
        entries, complete = artifact_list(r)
        r.update(
            artifacts=entries[:200],
            artifact_count=len(entries),
            artifact_catalogue_complete=complete,
            artifact_page_size=200,
        )
        return r

    @app.get("/v1/runs/{rid}/artifacts")
    def artifacts(rid: str, offset: int = 0, limit: int = 200):
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("Phân trang artifact không hợp lệ")
        entries, complete = artifact_list(store.get("runs", rid))
        return {
            "items": entries[offset : offset + limit],
            "count": len(entries),
            "complete": complete,
            "next_offset": offset + limit if offset + limit < len(entries) else None,
        }

    @app.post("/v1/runs/{rid}/retry")
    def retry(rid: str):
        return engine.retry(rid)

    @app.post("/v1/runs/{rid}/postprocess")
    def reprocess(rid: str):
        return engine.reprocess(rid)

    @app.get("/v1/runs/{rid}/history")
    def history(rid: str):
        r = store.get("runs", rid)
        if not r["attempts"]:
            return []
        file = Path(r["attempts"][-1]["path"]) / "extracted" / "impact_history.csv"
        if not file.exists():
            return []
        with file.open(encoding="utf-8-sig", newline="") as f:
            return [{k: float(v) if v else None for k, v in row.items()} for row in csv.DictReader(f)]

    @app.get("/v1/runs/{rid}/logs")
    def logs(rid: str):
        r = store.get("runs", rid)
        if not r["attempts"]:
            return {}
        root = Path(r["attempts"][-1]["path"])
        return {
            p.relative_to(root).as_posix(): tail(p, 10000)
            for p in [
                *(root / "logs").glob("*.log"),
                *(root / "raw").glob("*.log"),
                *(root / "raw").glob("*.sta"),
                *(root / "raw").glob("*.dat"),
                *(root / "raw").glob("*.msg"),
            ]
            if p.suffix in (".log", ".sta", ".msg", ".dat")
        }

    @app.post("/v1/runs/{rid}/open/{kind}")
    def open_run(rid: str, kind: Literal["odb", "cae", "pdf", "folder"]):
        r = store.get("runs", rid)
        if kind == "folder":
            path = Path(r["path"])
        else:
            if not r["attempts"]:
                raise ValueError("Lượt chưa có file")
            attempt = Path(r["attempts"][-1]["path"])
            path = (
                attempt / "reports" / "run-report.pdf"
                if kind == "pdf"
                else attempt / "raw" / (r["attempts"][-1]["job_name"] + "." + kind)
            )
        if not path.exists():
            raise ValueError("File chưa có: " + str(path))
        if kind in ("cae", "odb"):
            subprocess.Popen(
                command(engine.abaqus, "cae" if kind == "cae" else "viewer", "database=" + str(path)),
                cwd=path.parent,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        elif os.name == "nt":
            os.startfile(path)
        return {"path": str(path)}

    @app.post("/v1/open")
    def open_artifact(body: PathRequest):
        path = Path(body.path).resolve()
        from .retained import retained_root

        if (
            not (path.is_relative_to(store.root) or path.is_relative_to(retained_root(store)))
            or not path.exists()
        ):
            raise ValueError("Chỉ mở file trong thư viện dữ liệu")
        if path.is_file() and path.suffix.lower() not in (".pdf", ".png", ".csv", ".json", ".txt", ".zip"):
            raise ValueError("Định dạng này dùng công cụ xuất hoặc Abaqus")
        if os.name == "nt":
            os.startfile(path)
        return {"path": str(path)}

    @app.post("/v1/import-reference")
    def import_reference(body: ReferenceRequest):
        return operation(
            "import_reference",
            lambda: engine.import_reference(Path(body.path), body.model.model_dump(), body.render),
        )

    @app.post("/v1/import-designs")
    def import_designs(body: PathRequest):
        path = Path(body.path)
        if path.suffix.lower() != ".csv":
            raise ValueError("Cần file CSV")
        result = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                parsed = {}
                for k, v in row.items():
                    if not v.strip():
                        continue
                    try:
                        parsed[k] = json.loads(v)
                    except json.JSONDecodeError:
                        parsed[k] = v
                result.append(parsed)
                if len(result) > 10000:
                    raise ValueError("CSV vượt 10000 lượt")
        return {"designs": result}

    @app.post("/v1/batches/{bid}/report/export")
    def export_batch_report(bid: str, format: Literal["pdf", "docx"] = "pdf"):
        return operation(
            "batch_report",
            lambda: {"path": batch_report(store.get("batches", bid), store.list("runs", bid), format=format)},
        )

    @app.post("/v1/batches/{bid}/dataset/export")
    def export_batch_dataset(bid: str):
        batch = store.get("batches", bid)
        runs = store.list("runs", bid)

        def export():
            result = dataset(store, [r["id"] for r in runs], "Dữ liệu huấn luyện " + batch["name"])
            source = Path(result["path"])
            included = set(json.loads((source / "dataset.json").read_text(encoding="utf-8"))["run_ids"])
            audit = []
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
                audit.append(
                    {
                        "run_id": run["id"],
                        "index": run["index"],
                        "included": run["id"] in included,
                        "reason": reason,
                    }
                )
            write_rows(source / "job-coverage.csv", audit)
            destination = store.root / "exports" / (result["id"] + ".zip")
            destination.parent.mkdir(exist_ok=True)
            archive(source, destination)
            return {
                **result,
                "directory": str(source),
                "path": str(destination),
                "total_runs": len(runs),
                "excluded_runs": len(runs) - len(included),
            }

        return operation("batch_dataset", export)

    @app.post("/v1/batches/{bid}/archive/export")
    def export_batch_archive(bid: str):
        b = store.get("batches", bid)
        if any(
            r["status"]
            in {
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
            for r in store.list("runs", bid)
        ):
            raise ValueError("Dừng/chờ job trước khi đóng gói")
        dest = store.root / "exports" / (bid + ".zip")
        dest.parent.mkdir(exist_ok=True)
        return operation("archive", lambda: archive(Path(b["path"]), dest) or {"path": str(dest)})

    @app.post("/v1/runs/{rid}/archive/export")
    def export_run_archive(rid: str):
        r = store.get("runs", rid)
        if r["status"] not in ("completed", "review", "failed", "interrupted"):
            raise ValueError("Lượt chưa kết thúc")
        dest = store.root / "exports" / (rid + ".zip")
        dest.parent.mkdir(exist_ok=True)
        return operation("archive", lambda: archive(Path(r["path"]), dest) or {"path": str(dest)})

    @app.post("/v1/runs/{rid}/report/export")
    def export_run_report(rid: str, format: Literal["pdf", "docx"] = "pdf"):
        run = store.get("runs", rid)

        def export():
            if run.get("summary") and run["attempts"]:
                root = Path(run["attempts"][-1]["path"])
                file = root / "extracted/impact_history.csv"
                if file.exists():
                    with file.open(encoding="utf-8-sig", newline="") as f:
                        rows = [
                            {k: float(v) if v else None for k, v in row.items()} for row in csv.DictReader(f)
                        ]
                    return {"path": run_report(run, root, rows, format=format)}
            return {"path": incomplete_report(run, format=format)}

        return operation("run_report", export)

    @app.post("/v1/runs/{rid}/fields/csv")
    def export_fields_csv(rid: str, field: str = ""):
        r = store.get("runs", rid)
        if not r["attempts"]:
            raise ValueError("Chưa có dữ liệu")
        root = Path(r["attempts"][-1]["path"]) / "extracted"
        if not (root / "fields").exists():
            raise ValueError(
                "Lượt dùng dữ liệu nghiên cứu gọn. Chọn Dữ liệu ML gọn; dữ liệu trường đầy đủ vẫn có trong ODB gốc."
            )

        def export():
            import pyarrow.parquet as pq

            count = 0
            out = root / "csv-fields"
            out.mkdir(exist_ok=True)
            for p in (root / "fields").glob("**/*.parquet"):
                pf = pq.ParquetFile(p)
                meta = json.loads(pf.schema_arrow.metadata[b"honeycomb"])
                if field and field != meta["field"]:
                    continue
                target = out / p.relative_to(root / "fields").with_suffix(".csv")
                write_rows(target, pf.read().to_pylist())
                write_json(target.with_suffix(".metadata.json"), meta)
                pf.close()
                count += 1
            return {"path": str(out), "parts": count}

        return operation("fields_csv", export)

    @app.get("/v1/runs/{rid}/fields/csv/preview")
    def preview_fields_csv(rid: str, field: str = ""):
        run = store.get("runs", rid)
        if not run["attempts"]:
            raise ValueError("Chưa có dữ liệu")
        root = Path(run["attempts"][-1]["path"]) / "extracted"
        if not (root / "fields").exists():
            raise ValueError(
                "Không lưu bản sao trường Parquet ở chế độ nghiên cứu gọn. Chọn Dữ liệu ML gọn; ODB gốc vẫn được giữ."
            )
        inventory = json.loads((root / "inventory.json").read_text())
        fields = {}
        for item in inventory["fields"]:
            if not field or item["field"] == field:
                fields[item["field"]] = fields.get(item["field"], 0) + item["rows"]
        if not fields:
            raise ValueError("Không có field đã chọn trong ODB")
        # Conservative range; vector length, precision and CSV quoting affect size.
        components = {item["field"]: len(item.get("components") or ["value"]) for item in inventory["fields"]}
        estimated = sum(count * (110 + components[name] * 24) for name, count in fields.items())
        return {
            "fields": fields,
            "rows": sum(fields.values()),
            "estimated_bytes_range": [int(estimated * 0.6), int(estimated * 1.8)],
            "free_bytes": shutil.disk_usage(store.root).free,
            "note": "Ước tính CSV từ số dòng và component; bao gồm nhãn/section point, chưa tính metadata phụ.",
        }

    @app.post("/v1/datasets")
    def make_dataset(body: DatasetRequest):
        return dataset(store, body.run_ids, body.name, body.seed, body.features, body.targets)

    @app.get("/v1/datasets")
    def datasets():
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in (store.root / "datasets").glob("*/dataset.json")
        ]

    @app.post("/v1/datasets/{identity}/archive/export")
    def export_dataset(identity: str):
        import re

        if not re.fullmatch(r"d[a-f0-9]{16}", identity):
            raise ValueError("Dataset ID không hợp lệ")
        source = store.root / "datasets" / identity
        if not (source / "dataset.json").exists():
            raise ValueError("Không tìm thấy dataset")
        destination = store.root / "exports" / (identity + ".zip")
        destination.parent.mkdir(exist_ok=True)
        return operation(
            "dataset_archive", lambda: archive(source, destination) or {"path": str(destination)}
        )

    @app.get("/v1/pareto")
    def pareto_front():
        from .models import digest

        groups = {}
        for r in store.list("runs"):
            if (
                r["status"] != "completed"
                or r.get("test_only")
                or not (r.get("quality") or {}).get("ml_eligible")
            ):
                continue
            p = r["resolved"]
            load = {
                k: p[k]
                for k in (
                    "energy_J",
                    "velocity_m_s",
                    "mass_kg",
                    "ball_diameter",
                    "impact_x",
                    "impact_y",
                    "gravity",
                    "gap",
                )
            }
            key = digest(load)[:16]
            group = groups.setdefault(key, {"id": key, "load": load, "all": []})
            group["all"].append({"run_id": r["id"], **r["summary"]})
        return [{**g, "front": pareto(g["all"])} for g in groups.values()]

    @app.get("/v1/events")
    def events(after: int = 0):
        return store.events(after)

    @app.get("/v1/events/stream")
    async def event_stream(request: Request, after: int = 0):
        async def stream():
            cursor = after
            while not await request.is_disconnected():
                rows = store.events(cursor)
                for row in rows:
                    cursor = row["seq"]
                    yield "id: %d\ndata: %s\n\n" % (cursor, json.dumps(row, ensure_ascii=False))
                if not rows:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/operations/{identity}")
    def get_operation(identity: str):
        if identity not in operations:
            raise HTTPException(404, "Operation not found")
        return operations[identity]

    @app.get("/v1/backup")
    def backup_status():
        return backup.status()

    @app.post("/v1/backup/connect")
    def connect(body: PathRequest):
        return operation("oauth", lambda: backup.connect(Path(body.path)))

    @app.post("/v1/backup/check")
    def check_backup():
        return operation("backup_check", backup.check_connection)

    @app.post("/v1/backup/batches/{bid}")
    def backup_batch(bid: str):
        return backup.enqueue(bid)

    @app.post("/v1/backup/batches/{bid}/readable")
    def backup_readable_batch(bid: str):
        return backup.enqueue_readable(bid)

    @app.get("/v1/retained")
    def retained_copies():
        from .retained import retained_root

        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in retained_root(store).glob("*/*/drive-index.json")
        ]

    @app.post("/v1/backup/resume/{identity}")
    def resume_backup(identity: str):
        return backup.resume(identity)

    @app.post("/v1/backup/restore-local")
    def restore_local(body: PathRequest):
        return operation("restore", lambda: backup.restore_local(Path(body.path)))

    @app.post("/v1/backup/restore-drive")
    def restore_drive(body: RestoreRequest):
        return operation("restore", lambda: backup.restore_drive(body.file_id, body.sha256))

    @app.post("/v1/catalog/reindex")
    def reindex():
        if engine.current_run is not None:
            raise ValueError("Chờ hoặc dừng lượt đang chạy trước khi xây lại danh mục")
        return {"documents": store.reindex()}

    return app
