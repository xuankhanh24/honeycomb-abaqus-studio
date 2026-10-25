"""Fail closed until a checked-in, independently inspectable Linux qualification exists."""

import json
import os
import re
from pathlib import Path


def qualification(path=None):
    path = Path(path) if path else Path(__file__).with_name("runtime-lock.json")
    reasons = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    runtime_ok = all(data.get(k) for k in ("release", "python", "image_digest"))
    runtime_ok = runtime_ok and bool(re.fullmatch(r"[a-f0-9]{64}", data.get("installer_sha256", "")))
    smoke = data.get("smoke_receipt", {})
    runtime_ok = runtime_ok and smoke.get("solver_success") is True and smoke.get("platform") == "linux"
    runtime_ok = runtime_ok and str(smoke.get("evidence_url", "")).startswith("https://github.com/")
    if not runtime_ok:
        reasons.append(
            {
                "status": "blocked_environment",
                "message": "Chưa có nghiệm thu bộ cài và lượt chạy Abaqus Linux thật.",
            }
        )
    license = data.get("license_receipt", {})
    if not (
        runtime_ok
        and license.get("linux_checkout") is True
        and set(license.get("features", [])) >= {"cae", "explicit"}
        and str(license.get("evidence_url", "")).startswith("https://github.com/")
    ):
        reasons.append(
            {
                "status": "blocked_license",
                "message": "Chưa kiểm chứng token CAE/Explicit Linux qua mạng riêng.",
            }
        )
    if not os.getenv("PLATFORM_POLICY_EVIDENCE_URL", "").startswith("https://"):
        reasons.append(
            {
                "status": "blocked_platform_policy",
                "message": "Chưa xác nhận phạm vi dùng Actions cho backend nghiên cứu đầy đủ.",
            }
        )
    return data, reasons
