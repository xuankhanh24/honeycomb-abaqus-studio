"""Restore native parallel-smoke outputs and check scope, geometry and export coverage."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from honeycomb_studio.cloud_restore import restore, validate_manifest
from honeycomb_studio.cloud_unpack import unpack_fields
from honeycomb_studio.data import verify_export
from honeycomb_studio.reports import run_report
from honeycomb_studio.store import write_json


def verify(manifest_path, root):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    if sum(file["bytes"] for file in manifest["files"]) > 1024**3:
        raise ValueError("Smoke archive exceeds the 1 GiB verification budget")
    transport = restore(manifest, root)
    unpack_fields(root)
    receipt = json.loads((root / "impact-receipt.json").read_text(encoding="utf-8"))
    assert receipt["kind"] == "linux-parallel-angle-smoke" and receipt["solver_success"] is True
    assert receipt["production_runtime_qualified"] is False and receipt["ml_eligible"] is False
    assert receipt["profile"] == "parallel_smoke_not_research" and receipt["status"] == "review"
    intervals = list(receipt["solver_command_intervals"].values())
    assert len(intervals) == 2
    overlap = min(i["end"] for i in intervals) - max(i["start"] for i in intervals)
    assert overlap > 0 and abs(overlap - receipt["solver_command_overlap_seconds"]) < 1e-6
    models, exports, scopes, scope_reports = [], [], [], []
    for file in root.glob("**/raw/model_manifest.json"):
        model = json.loads(file.read_text(encoding="utf-8"))
        assert model["cpus"] == 2 and model["duration"] == .00002
        assert model["core_topology"] == "reentrant_0" and model["reentrant_geometry"] == "angle"
        assert model["clamp_mode"] == "perimeter" and model["mass_scaling"] is False
        angle = model["reentrant_delta_deg"]
        assert math.isclose(model["reentrant_indent"], model["reentrant_cell_height"] / 2 * math.tan(math.radians(angle)))
        attempt = file.parent.parent
        assert (attempt / "solver-complete.json").is_file()
        extracted = attempt / "extracted"
        export = verify_export(extracted)
        assert export["passed"] and export["field_frame_pairs"] > 0
        quality = json.loads((extracted / "quality.json").read_text(encoding="utf-8"))
        view = json.loads((extracted / "field-view.json").read_text(encoding="utf-8"))
        assert quality["ml_eligible"] is False and quality["physical_validation"] == "environment_smoke_only"
        assert view["source"]["data_profile"] == "smoke" and view["source"]["test_only"] is False
        # Standalone reports explicitly state scope. Preserve the reports written
        # on the original runner; these are separately named modern re-renders.
        from docx import Document

        record = json.loads((attempt.parent.parent / "run.json").read_text(encoding="utf-8"))
        with (extracted / "impact_history.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = [{key: float(value) if value else None for key, value in row.items()} for row in csv.DictReader(stream)]
        destination = root.parent / "parallel-smoke-scope-reports" / record["id"]
        destination.mkdir(parents=True, exist_ok=True)
        pdf = Path(run_report(record, destination, rows))
        docx = Path(run_report(record, destination, rows, format="docx"))
        document_text = "\n".join(p.text for p in Document(str(docx)).paragraphs)
        assert "SMOKE — KIỂM TRA MÔI TRƯỜNG" in document_text
        assert "Không phải dữ liệu nghiên cứu" in document_text
        for generated in (pdf, docx):
            with generated.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            scope_reports.append({"path": str(generated), "sha256": checksum, "bytes": generated.stat().st_size,
                                  "native_run_id": receipt["workflow_run_id"], "postprocess_only": True})
        models.append({"angle_deg": angle, "indent_mm": model["reentrant_indent"],
                       "cpus": model["cpus"], "duration_s": model["duration"]})
        exports.append(export)
        scopes.append(quality)
    assert len(models) == 2 and sorted(round(m["angle_deg"], 6) for m in models) == [20, 30]
    raw_names = [file["path"] for file in manifest["files"]]
    for suffix in (".cae", ".inp", ".odb"):
        assert sum(name.endswith(suffix) and "_check" not in name for name in raw_names) == 2
    result = {"kind": "native-parallel-smoke-restoration", "source_run_id": receipt["workflow_run_id"],
              "all_files_size_and_sha256_verified": len(transport["files"]), "models": models,
              "export_checks": exports, "quality_checks": scopes,
              "solver_command_overlap_seconds": overlap, "native_solver_executed_during_verification": False,
              "production_runtime_qualified": False, "research_dataset": False,
              "full_study_speedup_established": False, "integration_kernel_overlap_established": False}
    result["standalone_scope_reports"] = scope_reports
    write_json(Path("output/parallel-smoke-restore-verification.json"), result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    verify(args.manifest, args.destination)
