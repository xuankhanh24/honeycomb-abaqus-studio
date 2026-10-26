"""Private reusable installer ISO; the pinned hash does not prove publisher authenticity."""

import hashlib
import re
from pathlib import Path

ISO_NAME = "DS.SIMULIA.Suite.2020.Linux64_Softgozar.com.iso"
DRIVE_NAME = "SIMULIA_Abaqus_2020_Linux64.iso"
ISO_BYTES = 10066642944
ISO_SHA256 = "d0b227290b5f62ea826b08c18bde222417817fc0d04b91abb0072cb52ebe43ad"
MEDIA_KEY = "abaqus2020-linux-" + ISO_SHA256[:16]


def verify_iso(path, *, expected_bytes=ISO_BYTES, expected_sha256=ISO_SHA256):
    if path.stat().st_size != expected_bytes:
        raise ValueError("Kích thước ISO không khớp bản đã thử nghiệm")
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            sha.update(block)
            md5.update(block)
    if sha.hexdigest() != expected_sha256:
        raise ValueError("SHA-256 của ISO không khớp; không được chạy bộ cài")
    return {"bytes": expected_bytes, "sha256": sha.hexdigest(), "md5": md5.hexdigest()}


def download_iso(session, file_id, destination: Path, *, logger=None,
                 expected_bytes=ISO_BYTES, expected_sha256=ISO_SHA256):
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,128}", file_id):
        raise ValueError("Mã file Google Drive không hợp lệ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return verify_iso(destination, expected_bytes=expected_bytes, expected_sha256=expected_sha256)
    partial = destination.with_suffix(destination.suffix + ".part")
    transfer = logger.transfer("Tải trực tiếp ISO từ Google Drive riêng", expected_bytes) if logger else None
    count, digest = 0, hashlib.sha256()
    try:
        with session.get("https://www.googleapis.com/drive/v3/files/" + file_id,
                         params={"alt": "media"}, stream=True, timeout=(30, 120)) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Tải ISO từ Drive không thành công (HTTP {response.status_code}); kiểm tra tài khoản và quyền truy cập file")
            with partial.open("wb") as output:
                for block in response.iter_content(8 * 1024**2):
                    count += len(block)
                    if count > expected_bytes:
                        raise ValueError("ISO tải về vượt kích thước đã ghim")
                    output.write(block)
                    digest.update(block)
                    if transfer:
                        transfer.advance(len(block))
        if count != expected_bytes or digest.hexdigest() != expected_sha256:
            raise ValueError("ISO tải về không khớp kích thước/SHA-256; không được chạy bộ cài")
        partial.replace(destination)
        if transfer:
            transfer.verified()
        return {"bytes": count, "sha256": digest.hexdigest()}
    finally:
        partial.unlink(missing_ok=True)
