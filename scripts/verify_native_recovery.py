"""Verify recovered parts using canonical published asset URLs; retain the failed draft manifest."""

import json
import os
import tarfile
from pathlib import Path

from honeycomb_studio.actions_log import get_actions_log
from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import Github
from honeycomb_studio.cloud_release import canonical_manifest
from honeycomb_studio.cloud_restore import restore
from honeycomb_studio.contracts import QualityReport
from honeycomb_studio.data import verify_export


def main():
    source = os.environ["SOURCE_RUN_ID"]
    assert source.isdigit()
    logger = get_actions_log()
    github = Github(token=os.environ["GITHUB_TOKEN"])
    release = github.repo("GET", "/releases/tags/linux-impact-7j-" + source)
    assert release["draft"] is False
    with logger.stage("Đối chiếu asset ID/hash và sửa URL từ Release đã công bố"):
        manifest = json.loads(Path("output/impact-artifact-manifest.json").read_text())
        assets = []
        for page in range(1, 11):
            batch = github.repo("GET", f"/releases/{release['id']}/assets?per_page=100&page={page}")
            assets.extend(batch)
            if len(batch) < 100:
                break
        canonical_manifest(manifest, assets)
        corrected = Path("output/impact-recovered-artifact-manifest.json")
        corrected.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        ReleaseArchive(github, release["id"]).upload(corrected, corrected.name)
    with logger.stage("Tải lại mọi part và xác minh SHA-256 trên runner mới"):
        root = Path(os.environ["RUNNER_TEMP"]) / "recovered-verified"
        restore(manifest, root, allow_incomplete=True)
        with tarfile.open(root / "field-reductions.tar") as bundle:
            bundle.extractall(root, filter="data")
        receipt = json.loads((root / "recovery-receipt.json").read_text())
        assert receipt["source_run_id"] == source and receipt["solver_success"] is True
        exports = [verify_export(p.parent) for p in root.rglob("complete.json") if p.parent.name == "extracted"]
        assert exports and all(e["passed"] for e in exports)
        models = list(root.rglob("model_manifest.json"))
        assert len(models) == 1
        model = json.loads(models[0].read_text())
        assert model["energy_J"] == 7 and model["duration"] == .006 and model["cpus"] == 4
        assert model["clamp_mode"] == "perimeter" and model["mass_scaling"] is False
        qualities = list(root.glob("**/extracted/quality.json"))
        assert len(qualities) == 1
        quality = QualityReport.model_validate_json(qualities[0].read_text())
        assert quality.solver_completed and quality.physical_validation == "not_established"
        result = {**receipt, "verification_run_id": os.environ["GITHUB_RUN_ID"],
                  "all_published_parts_roundtrip_verified": True, "export_checks": exports,
                  "quality": quality.model_dump(), "original_full_6ms_input_verified": True}
        Path("output/native-recovery-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        logger.notices.append(f"Lưu trữ gốc chưa đầy đủ: {len(receipt['missing_original_files'])} tệp thiếu; xem recovery-receipt.json. ODB gốc và dữ liệu số giữ được đã kiểm tra checksum.")
    github.repo("PATCH", f"/releases/{release['id']}", {"body": "Recovered after original publication failed. Use impact-recovered-artifact-manifest.json (canonical URLs). Every retained part was downloaded and SHA-256 verified on a fresh Actions runner. Original retention remains incomplete: missing reports/images are listed in recovery-receipt.json; history tables were regenerated and matched against original hashes. Raw ODB is unchanged. Research status remains review, physical validation not established."})
    logger.summary()


if __name__ == "__main__":
    main()
