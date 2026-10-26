"""Keep one pinned ISO in the project's existing private Drive account."""

import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession

from honeycomb_studio.actions_log import get_actions_log
from honeycomb_studio.cloud_drive import CloudDriveBackup
from honeycomb_studio.media_cache import (
    DRIVE_NAME,
    ISO_BYTES,
    ISO_NAME,
    ISO_SHA256,
    MEDIA_KEY,
    download_iso,
    verify_iso,
)
from honeycomb_studio.store import Store, write_json


def request(session, method, path, **kwargs):
    response = session.request(method, "https://www.googleapis.com/drive/v3/" + path, timeout=60, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Google Drive trả HTTP {response.status_code}; kiểm tra đăng nhập, quyền truy cập hoặc dung lượng")
    return response.json()


def record(info, folder=None):
    value = {"kind": "private-abaqus-installer-mirror", "source": "Softgozar third-party ISO",
             "publisher_authenticity_verified": False, "bytes": ISO_BYTES, "sha256": ISO_SHA256,
             "drive_file_id": info.get("drive_file_id") or info["id"],
             "web_url": info.get("web_url") or info.get("webViewLink"),
             "verified": True, "public_sharing_enabled": False}
    if folder:
        value["folder_url"] = "https://drive.google.com/drive/folders/" + folder
    write_json(Path("output/media-mirror-receipt.json"), value)
    return value


def upload(backup, path, parent, identity, logger):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    with path.open("rb") as stream:
        md5 = hashlib.file_digest(stream, "md5").hexdigest()
    state_path = backup.states / (identity + ".json")
    state = {"id": identity, "batch_id": "private-installer-media", "file": str(path),
             "bytes": path.stat().st_size, "sha256": sha, "md5": md5,
             "drive_name": path.name, "parent_id": parent, "status": "prepared",
             "mime_type": "application/octet-stream", "offset": 0}
    write_json(state_path, state)
    transfer = logger.transfer("Tải lên Drive riêng · " + path.name, state["bytes"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(backup._upload_file, state_path)
        reported = 0
        while not future.done():
            try:
                offset = json.loads(state_path.read_text(encoding="utf-8")).get("offset", 0)
                transfer.advance(max(0, offset - reported))
                reported = max(reported, offset)
            except (OSError, ValueError):
                pass
            time.sleep(1)
        try:
            result = future.result()
        except Exception:
            raise RuntimeError("Upload Drive bị gián đoạn; giữ state riêng và kiểm tra cấu hình/dung lượng. Không công bố phiên upload hoặc token.") from None
    transfer.advance(state["bytes"] - transfer.count)
    transfer.verified()  # DriveBackup checked remote MD5 and size against the local file.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    logger = get_actions_log()
    if logger is None or not os.getenv("HONEYCOMB_DRIVE_CREDENTIALS_JSON"):
        raise RuntimeError("Cần cấu hình Drive đã đăng nhập và bật log Actions")
    private = Path(os.environ["RUNNER_TEMP"]) / "private-installer-upload-state"
    store = Store(private)
    backup = CloudDriveBackup(store, private / "config", recover=False)
    try:
        with AuthorizedSession(backup.credentials()) as session:
            if args.preflight:
                with logger.stage("Kiểm tra bản ISO đã lưu và dung lượng Drive trước khi tải"):
                    found = request(session, "GET", "files", params={
                        "q": "trashed=false and appProperties has { key='honeycomb_backup' and value='" + MEDIA_KEY + "' }",
                        "fields": "files(id,size,md5Checksum,sha256Checksum,webViewLink)", "pageSize": 100})["files"]
                    present = False
                    for item in found:
                        if int(item.get("size", 0)) != ISO_BYTES:
                            continue
                        if item.get("sha256Checksum") != ISO_SHA256:
                            # Older Drive metadata may omit SHA-256; read actual bytes before reuse.
                            target = private / "verify-existing.iso"
                            download_iso(session, item["id"], target, logger=logger)
                        record(item)
                        present = True
                        logger.emit("CACHE", "Đã có ISO đúng SHA-256 trong Drive; không tải mirror hoặc upload trùng")
                        break
                    if not present:
                        quota = request(session, "GET", "about", params={"fields": "storageQuota"})["storageQuota"]
                        if quota.get("limit") and int(quota["limit"]) - int(quota.get("usage", 0)) < ISO_BYTES + 16 * 1024**2:
                            raise RuntimeError("Drive không đủ dung lượng cho ISO 10.066.642.944 byte và tệp hướng dẫn; chưa tải hoặc upload bộ cài")
                        logger.emit("PLAN", "Drive đủ dung lượng; sẽ lưu một ISO riêng tư, không tạo quyền chia sẻ công khai")
                    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
                        output.write("present=" + str(present).lower() + "\n")
                return
            source = Path(os.environ["RUNNER_TEMP"]) / "abaqus-media-inspection/iso" / ISO_NAME
            with logger.stage("Kiểm tra ISO đúng bản đã thử nghiệm và chuẩn bị thư mục riêng"):
                verify_iso(source)
                folder = backup._folder(session, "Honeycomb · Bộ cài riêng", "private-installer-media-v1")
                permissions = request(session, "GET", "files/" + folder, params={"fields": "permissions(type,role)"}).get("permissions", [])
                if not permissions or any(p.get("role") != "owner" for p in permissions):
                    raise RuntimeError("Thư mục kho bộ cài có quyền chia sẻ hoặc chưa xác minh được riêng tư; không upload vào đó")
            with logger.stage("Upload ISO vào Google Drive riêng và đối chiếu MD5/kích thước"):
                # A hard link gives the user a clean filename without duplicating the 10 GB ISO.
                named = source.with_name(DRIVE_NAME)
                if not named.exists():
                    os.link(source, named)
                info = upload(backup, named, folder, MEDIA_KEY, logger)
                receipt = record(info, folder)
            with logger.stage("Lưu checksum và hướng dẫn cạnh bộ cài"):
                docs = private / "documents"
                docs.mkdir(exist_ok=True)
                checksum = docs / "SHA256SUMS.txt"
                checksum.write_text(ISO_SHA256 + "  " + DRIVE_NAME + "\n", encoding="utf-8")
                readme = docs / "HUONG_DAN.md"
                readme.write_text(
                    "# Kho ISO Abaqus 2020 Linux64 riêng\n\n"
                    "Tải một file ISO, không cần ghép 5 phần RAR. Dùng SHA256SUMS.txt để kiểm tra trước khi cài.\n"
                    "Linux: sha256sum -c SHA256SUMS.txt\nWindows PowerShell: Get-FileHash .\\" + DRIVE_NAME + " -Algorithm SHA256\n\n"
                    "Nguồn: mirror Softgozar. Hash chỉ ghim đúng ISO đã thử nghiệm, chưa xác minh nguồn phát hành chính hãng.\n"
                    "GitHub Actions của project dùng Ubuntu với môi trường CentOS 7 cách ly để chạy bộ cài nguyên bản. "
                    "License nằm trên máy chủ riêng; thư mục này không chứa file kích hoạt/license.\n"
                    "Cấu hình ABAQUS_MEDIA_DRIVE_FILE_ID=" + receipt["drive_file_id"] + " trong biến repo; giữ thông tin OAuth trong secret HONEYCOMB_DRIVE_CREDENTIALS_JSON.\n",
                    encoding="utf-8")
                upload(backup, checksum, folder, MEDIA_KEY + "-checksums", logger)
                upload(backup, readme, folder, MEDIA_KEY + "-guide", logger)
            logger.emit("RESULT", receipt["web_url"] or "ISO đã lưu và xác minh trong thư mục Drive riêng")
    finally:
        store.db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger = get_actions_log()
        if logger:
            logger.failure(type(exc).__name__, "Lưu kho bộ cài riêng", "Kiểm tra cấu hình Drive, dung lượng trống và checksum. State upload chỉ nằm trong thư mục riêng của runner.")
        raise SystemExit(1) from None
