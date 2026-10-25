"""Optional secondary readable backup; cloud credentials stay in process memory."""

import json
import os
from pathlib import Path

from .backup import SCOPES, DriveBackup


class CloudDriveBackup(DriveBackup):
    def credentials(self):
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_info(
            json.loads(os.environ["HONEYCOMB_DRIVE_CREDENTIALS_JSON"]), SCOPES
        )

    def _save_token(self, text):
        os.environ["HONEYCOMB_DRIVE_CREDENTIALS_JSON"] = text


def backup_readable(store, batch_id, private_temp: Path):
    if not os.getenv("HONEYCOMB_DRIVE_CREDENTIALS_JSON"):
        return {"status": "not_configured"}
    try:
        backup = CloudDriveBackup(store, private_temp, recover=False)
        state = backup.backup_readable(batch_id)
        return {"status": state.get("status"), "readable_verified": bool(state.get("readable_verified"))}
    except Exception:
        return {
            "status": "backup_failed",
            "error": "Drive backup unavailable; verified GitHub archive remains primary.",
        }
