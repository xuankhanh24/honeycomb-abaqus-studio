"""Recover retained numerical data without a new solver; explicitly inventory missing originals."""

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from honeycomb_studio.actions_log import get_actions_log
from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import Github
from honeycomb_studio.cloud_release import reserve_release
from honeycomb_studio.cloud_restore import restore
from honeycomb_studio.contracts import QualityReport
from honeycomb_studio.data import history_summary, verify_export


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.source_run_id.isdigit():
        parser.error("Numeric source run ID required")
    github = Github(token=os.environ["GITHUB_TOKEN"])
    source_run = github.repo("GET", "/actions/runs/" + args.source_run_id)
    assert source_run["path"] == ".github/workflows/linux-impact-7j.yml"
    assert source_run["head_branch"] == "main" and source_run["status"] == "completed"
    candidates = [p.parent for p in args.artifact_root.rglob("original-requested-input.json")
                  if (p.parent / "impact-receipt.json").is_file()]
    assert len(candidates) == 1
    root = candidates[0]
    receipt = json.loads((root / "impact-receipt.json").read_text())
    assert receipt["workflow_run_id"] == args.source_run_id and receipt["solver_success"]
    assert receipt["status"] == "review" and receipt["summary"]["frames"] == 121
    logger = get_actions_log()
    with logger.stage("Kiểm tra dữ liệu gốc và khôi phục bảng history từ JSON gốc"):
        regenerated = []
        for run_file in root.rglob("run.json"):
            run = json.loads(run_file.read_text())
            for complete in run_file.parent.glob("attempts/*/extracted/complete.json"):
                extracted = complete.parent
                quality = QualityReport.model_validate_json((extracted / "quality.json").read_text())
                assert quality.solver_completed and quality.physical_validation == "not_established"
                verify_export(extracted)
                with tempfile.TemporaryDirectory() as directory:
                    scratch = Path(directory) / "extracted"
                    shutil.copytree(extracted, scratch)
                    model = json.loads((extracted.parent / "raw/model_manifest.json").read_text())
                    history_summary(scratch, run["resolved"], actual=model)
                    for name in ("impact_history.csv", "impact_history.parquet", "all_histories.csv", "all_histories.parquet"):
                        if not (extracted / name).exists():
                            shutil.copyfile(scratch / name, extracted / name)
                            regenerated.append((extracted / name).relative_to(root).as_posix())
        # Preserve every original manifest; do not rewrite it to hide a missing report/image.
        missing, checked = [], 0
        for manifest in root.rglob("artifact-manifest.json"):
            document = json.loads(manifest.read_text())
            for entry in document.get("files", []):
                target = (manifest.parent / entry["path"]).resolve()
                assert target.is_relative_to(root.resolve())
                if not target.is_file():
                    missing.append(target.relative_to(root).as_posix())
                else:
                    assert target.stat().st_size == entry["bytes"] and sha256(target) == entry["sha256"], entry["path"]
                    checked += 1
        odbs = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in root.rglob("*.odb")]
        assert len(odbs) == 2
        result = {"kind": "native-actions-artifact-recovery", "source_run_id": args.source_run_id,
                  "source_commit": source_run["head_sha"], "recovery_run_id": os.environ["GITHUB_RUN_ID"],
                  "solver_rerun": False, "license_used": False, "solver_success": True,
                  "physical_validation": "not_established", "research_status": receipt["status"],
                  "original_manifest_entries_verified": checked, "missing_original_files": sorted(set(missing)),
                  "regenerated_history_files": regenerated, "odbs": odbs,
                  "retention_complete": not missing}
        (root / "recovery-receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        logger.notices.append(f"Khôi phục artifact dự phòng: {len(set(missing))} tệp gốc không có trong backup. Xem recovery-receipt.json; không chứng nhận lưu trữ đầy đủ.")
    release = reserve_release(github, tag="linux-impact-7j-" + args.source_run_id,
                              sha=source_run["head_sha"], name="Recovered Linux 7 J · read retention gaps")
    release = github.repo("PATCH", f"/releases/{release['id']}", {"draft": False,
                "body": "Recovery upload in progress. Read the final manifest and recovery-receipt for retention gaps; scientific quality remains review."})
    with logger.stage("Upload dữ liệu giữ được và manifest có trạng thái lưu trữ đúng"):
        manifest = ReleaseArchive(github, release["id"]).publish(root, attempt="impact", complete=not missing)
    with logger.stage("Runner khôi phục archive vừa xuất và kiểm tra checksum"):
        destination = Path(os.environ["RUNNER_TEMP"]) / "recovered-roundtrip"
        restore(manifest, destination, allow_incomplete=True)
        if (destination / "field-reductions.tar").exists():
            with tarfile.open(destination / "field-reductions.tar") as bundle:
                bundle.extractall(destination, filter="data")
        exports = [verify_export(p.parent) for p in destination.rglob("complete.json") if p.parent.name == "extracted"]
        assert exports and all(e["passed"] for e in exports)
        result.update(all_published_parts_roundtrip_verified=True, export_checks=exports)
        Path("output").mkdir(exist_ok=True)
        Path("output/native-recovery-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    github.repo("PATCH", f"/releases/{release['id']}", {"draft": False,
                "body": "Recovered from Actions backup after original publication returned 403. Raw ODB and retained numerical JSON preserved; history tables regenerated and checked. Original reports/images may be missing: see recovery-receipt.json. Archive completeness is explicitly recorded, scientific quality remains review."})
    logger.emit("RESULT", release["html_url"])


if __name__ == "__main__":
    main()
