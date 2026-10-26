"""Prefer the verified private Drive ISO; original mirror is used only before configuration."""

import json
import os
from pathlib import Path

from honeycomb_studio.actions_log import get_actions_log
from honeycomb_studio.backup import SCOPES
from honeycomb_studio.media_cache import ISO_NAME, download_iso


def main():
    file_id = os.getenv("ABAQUS_MEDIA_DRIVE_FILE_ID", "")
    if not file_id:
        from inspect_linux_media import main as original

        return original()
    if not os.getenv("HONEYCOMB_DRIVE_CREDENTIALS_JSON"):
        raise ValueError("Đã chọn kho ISO riêng nhưng thiếu cấu hình đăng nhập Drive")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials

    logger = get_actions_log()
    credentials = Credentials.from_authorized_user_info(json.loads(os.environ["HONEYCOMB_DRIVE_CREDENTIALS_JSON"]), SCOPES)
    target = Path(os.environ["RUNNER_TEMP"]) / "abaqus-media-inspection/iso" / ISO_NAME
    with AuthorizedSession(credentials) as session:
        result = download_iso(session, file_id, target, logger=logger)
    output = Path("output/media-inspection")
    output.mkdir(parents=True, exist_ok=True)
    (output / "inspection.json").write_text(json.dumps({
        "kind": "private-drive-iso-download", "source": "private_google_drive",
        "iso": {"name": ISO_NAME, **result}, "passed_media_inventory": True,
        "publisher_authenticity_verified": False, "installer_executed": False,
        "verification": "Exact bytes and SHA-256 of the previously inventoried ISO; not a publisher signature",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print credential errors or resumable bearer URLs into public logs.
        logger = get_actions_log()
        if logger:
            logger.failure(type(exc).__name__, "Tải bộ cài", "Kiểm tra cấu hình Drive, dung lượng và checksum đã ghim")
        raise SystemExit(1) from None
