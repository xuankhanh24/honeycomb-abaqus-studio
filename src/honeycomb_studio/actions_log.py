"""Measured, redacted Actions console/summary output; never controls the solver."""

from __future__ import annotations

import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

PHASES = {
    "queued": "Chờ chạy", "building": "Dựng mô hình và chia lưới", "checking": "Kiểm tra mô hình trước khi tính",
    "solving": "Đang tính mô phỏng Abaqus/Explicit", "extracting": "Đọc kết quả ODB", "verifying_export": "Kiểm tra dữ liệu xuất",
    "analyzing": "Tính chỉ số", "rendering": "Xuất hình", "reporting": "Tạo báo cáo",
    "cataloguing": "Lưu manifest", "completed": "Hoàn tất", "review": "Hoàn tất · cần xem xét",
    "failed": "Thất bại", "interrupted": "Đã dừng", "waiting_license": "Chờ license",
    "recovering": "Khôi phục tiến trình",
}

CATEGORIES = {
    "START": "BẮT ĐẦU", "OK": "HOÀN TẤT BƯỚC", "FAIL": "CÓ LỖI", "FIX": "CÁCH KIỂM TRA",
    "PROCESS": "TIẾN TRÌNH", "HEARTBEAT": "VẪN ĐANG CHẠY", "DETAILS": "LOG CHI TIẾT",
    "TRANSFER": "TRUYỀN DỮ LIỆU", "RUN": "TIẾN ĐỘ MÔ PHỎNG", "PHASE": "GIAI ĐOẠN MỚI",
    "HOST": "TÀI NGUYÊN MÁY CHẠY", "CONTAINER": "TÀI NGUYÊN MÔI TRƯỜNG ABAQUS",
    "CACHE": "DÙNG LẠI DỮ LIỆU ĐÃ KIỂM TRA", "ARCHIVE": "LƯU KẾT QUẢ", "RESULT": "KẾT QUẢ",
    "TEST": "KIỂM TRA", "PLAN": "THÔNG TIN LƯỢT CHẠY",
}
PHASE_HELP = {
    "building": "Tạo hình học, vật liệu, điều kiện biên và lưới; chưa bắt đầu tính va chạm.",
    "checking": "Abaqus kiểm tra input và lưới; nếu lỗi, mở checking.log của lần thử này.",
    "solving": "Đang tính va chạm thật. Phần trăm = thời gian vật lý đã tính / thời gian yêu cầu; thời gian chờ thực tế có thể dài hơn.",
    "extracting": "Solver đã kết thúc; đang đọc các frame trong ODB và xuất dữ liệu số.",
    "verifying_export": "Đối chiếu số frame và số mẫu đã xử lý với danh mục trong ODB.",
    "analyzing": "Tính lực, chuyển vị, năng lượng và kiểm tra chất lượng số.",
    "rendering": "Đang tạo hình kết quả; chưa hoàn tất toàn bộ công việc.",
    "reporting": "Đang tạo báo cáo và ghi nguồn gốc dữ liệu.",
    "review": "Đã có kết quả nhưng cần xem quality.json; không tự chứng nhận dữ liệu đủ điều kiện ML.",
    "completed": "Đã hoàn tất xử lý kết quả; vẫn cần xem chất lượng và bằng chứng kiểm chứng vật lý.",
    "waiting_license": "Chưa lấy được quyền dùng Abaqus; kiểm tra máy chủ license và kết nối riêng.",
    "failed": "Lượt chạy gặp lỗi; xem thông báo lỗi và log chi tiết của đúng giai đoạn.",
}


def size(value):
    if value is None:
        return "—"
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(number) < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}"
        number /= 1024


def duration(value):
    if value is None or not math.isfinite(value):
        return "—"
    seconds = max(0, int(value))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"


def bar(value):
    if value is None or not math.isfinite(value):
        return "[                    ]   —"
    value = min(100, max(0, value))
    filled = int(value / 5)
    return "[" + "#" * filled + "-" * (20 - filled) + f"] {value:5.1f}%"


def clean(text):
    text = str(text)
    values = [value for key, value in os.environ.items() if value and
              (key.endswith(("_TOKEN", "_SECRET", "_PASSWORD", "_PRIVATE_KEY")) or
               key in ("HONEYCOMB_DRIVE_CREDENTIALS_JSON", "ABAQUS_LICENSE_ENDPOINT", "HONEYCOMB_LICENSE_HOST"))]
    endpoint = os.getenv("ABAQUS_LICENSE_ENDPOINT", "")
    if "@" in endpoint:
        values.append(endpoint.split("@", 1)[1])
    for value in sorted(values, key=len, reverse=True):
        for part in [value, *value.splitlines()]:
            if len(part) >= 4:
                text = text.replace(part, "<redacted>")
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r"(https?://[^\s?'\"<>]+)[?#][^\s'\"<>]+", r"\1?<redacted>", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+", r"\1<redacted>", text)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def line(text):
    return " ".join(clean(text).split())


def markdown(text):
    return html.escape(line(text)).replace("|", "\\|").replace("`", "'").replace("[", "&#91;").replace("]", "&#93;")


def safe_data(value):
    if isinstance(value, dict):
        return {line(k): safe_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_data(v) for v in value]
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def command_data(text):
    return clean(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def snapshot(run):
    phase = run.get("status", "queued")
    progress = run.get("progress") or {}
    value = progress.get("solver_percent") if phase == "solving" else (
        progress.get("extraction_percent") if phase == "extracting" else
        progress.get("analysis_percent") if phase in ("verifying_export", "analyzing") else None)
    if value is not None and not math.isfinite(value):
        value = None
    physical = progress.get("simulation_time_s")
    target = run.get("resolved", {}).get("duration")
    physical_text = f"{physical * 1000:.3f}/{target * 1000:g} ms" if physical is not None and target else "—"
    attempts = run.get("attempts") or []
    process = (attempts[-1].get("process") or {}) if attempts else {}
    return {"id": run.get("id", "run"), "phase": phase, "label": PHASES.get(phase, phase),
            "percent": value, "physical": physical_text, "pid": process.get("pid"),
            "elapsed": duration(progress.get("phase_elapsed_seconds")),
            "eta": duration(progress.get("eta_solver_seconds") if phase == "solving" else
                            progress.get("eta_extraction_seconds") if phase == "extracting" else
                            progress.get("eta_analysis_seconds") if phase in ("analyzing", "verifying_export") else None),
            "ram": size(progress.get("process_ram_bytes"))}


def runs_markdown(runs):
    rows = ["| Lượt | Giai đoạn | Tiến độ của giai đoạn | Thời gian vật lý | Đã chạy | Còn khoảng (ước tính) | Mã tiến trình (PID) |",
            "|---|---|---|---|---|---|---|"]
    for run in runs:
        item = snapshot(run)
        percent = f"{item['percent']:.1f}%" if item["percent"] is not None else "Chưa có % đo được"
        rows.append("| " + " | ".join(markdown(x) for x in
                    (item["id"], item["label"], percent, item["physical"], item["elapsed"], item["eta"], item["pid"] or "—")) + " |")
    return "\n".join(rows)


def hint(text):
    lower = str(text).lower()
    if "403" in lower and "release" in lower:
        return "Kiểm tra quyền ghi Releases và tag mã nguồn đã được giữ chỗ từ đầu lượt chạy. Xem phản hồi GitHub; không chạy lại solver chỉ để sửa bước tải lên."
    if "404" in lower and "github.com" in lower:
        return "Kiểm tra Release đã công bố và URL asset đúng tag, không dùng URL bản nháp untagged. Giữ lại dữ liệu trước khi thử tải lại."
    if any(k in lower for k in ("license", "flexnet", "checkout", "blocked_license")):
        return "Kiểm tra máy license online/Tailscale, hai cổng manager/vendor và log checking.log/solving.log."
    if any(k in lower for k in ("sha256", "checksum", "digest", "truncated")):
        return "Đối chiếu kích thước và SHA-256; tải lại phần lỗi. Không bỏ kiểm tra checksum."
    if any(k in lower for k in ("disk", "no space", "ram", "memory", "resource")):
        return "Kiểm tra RAM/đĩa còn trống và mức dự phòng; xem log của phase bị dừng."
    if any(k in lower for k in ("timeout", "timed_out", "budget")):
        return "Xem mốc tiến độ cuối và ngân sách thời gian; giữ dữ liệu attempt trước khi chạy lại."
    return "Mở log chi tiết của đúng giai đoạn và dòng lỗi cuối; kiểm tra input/attempt tương ứng trước khi chạy lại."


class ActionsLog:
    def __init__(self, *, stream=None, clock=None, summary_path=None, events_path=None):
        self.stream = stream or sys.stdout
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.summary_path = Path(summary_path) if summary_path else (
            Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.getenv("GITHUB_STEP_SUMMARY") else None)
        self.events_path = Path(events_path) if events_path else None
        self.lock = threading.RLock()
        self.stages = {}
        self.transfers = {}
        self.current_runs = []
        self.notices = []
        self.resource_rows = []
        self.cpu_primed = False
        self.last_phases = {}
        self.title = os.getenv("HONEYCOMB_LOG_TITLE", "Theo dõi công việc Honeycomb Studio")

    def emit(self, category, text, **data):
        with self.lock:
            text = line(text)
            try:
                label = CATEGORIES.get(category, category)
                print(f"[{duration(self.clock() - self.started)}] [{category}] {label} | {text}", file=self.stream, flush=True)
            except (OSError, UnicodeError):
                pass
            if self.events_path:
                try:
                    self.events_path.parent.mkdir(parents=True, exist_ok=True)
                    record = safe_data({"elapsed_s": self.clock() - self.started,
                                        "kind": category, "message": text, **data})
                    with self.events_path.open("a", encoding="utf-8") as output:
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
                except (OSError, ValueError):
                    pass  # Auxiliary diagnostics must not stop a real solver/transfer.

    def summary(self):
        if not self.summary_path:
            return
        with self.lock:
            rows = ["## " + markdown(self.title), "",
                    "Phần trăm thuộc từng giai đoạn, không phải toàn bộ công việc. Thời gian còn lại chỉ là ước tính. Solver chạy xong chưa đồng nghĩa đã kiểm chứng vật lý.", ""]
            if self.stages:
                rows += ["| Bước | Trạng thái | Thời gian |", "|---|---|---|"]
                rows += [f"| {markdown(name)} | {markdown(state)} | {duration(elapsed)} |"
                         for name, (state, elapsed) in self.stages.items()]
                rows += [""]
            if self.current_runs:
                rows += [runs_markdown(self.current_runs), ""]
            if self.transfers:
                rows += ["### Tải lên / tải xuống", "", "| Tệp | Trạng thái | Đã truyền / tổng | Tốc độ trung bình |", "|---|---|---|---|"]
                rows += [f"| {markdown(name)} | {markdown(t['state'])} | {size(t['done'])} / {size(t['total'])} | {size(t['rate'])}/s |"
                         for name, t in list(self.transfers.items())[-12:]]
            if self.resource_rows:
                rows += ["", "### Tài nguyên đo được", "", *["- " + markdown(r) for r in self.resource_rows]]
            if self.notices:
                rows += ["", "### Cần kiểm tra", "", *["- " + markdown(n) for n in self.notices[-12:]]]
            try:
                self.summary_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            except OSError:
                pass

    @contextmanager
    def stage(self, title):
        started = self.clock()
        self.stages[title] = ("Đang chạy · chưa có % đo được", 0)
        self.emit("START", title)
        self.summary()
        try:
            yield
        except BaseException as exc:
            self.stages[title] = ("Thất bại", self.clock() - started)
            self.failure(exc, title, getattr(exc, "details", ""), getattr(exc, "tail", ""))
            raise
        else:
            self.stages[title] = ("Đã hoàn tất bước", self.clock() - started)
            self.emit("OK", f"{title} | {duration(self.clock() - started)}")
        finally:
            self.summary()

    def failure(self, exc, phase, details="", tail=""):
        message = f"{line(phase)}: {line(exc)}"
        advice = hint(message + " " + str(tail))
        self.notices.append(message + " · " + advice + (" · Log: " + line(details) if details else ""))
        self.emit("FAIL", message)
        self.emit("FIX", advice + (" | Log: " + line(details) if details else ""))
        if os.getenv("GITHUB_ACTIONS") == "true":
            print("::error title=Honeycomb::" + command_data(message + " · " + advice), file=self.stream, flush=True)
        if tail:
            print("::group::Chi tiết lỗi (đã che thông tin riêng)", file=self.stream)
            for entry in clean(tail).splitlines()[-25:]:
                print("  " + entry, file=self.stream)
            print("::endgroup::", file=self.stream, flush=True)
        self.summary()

    def runs(self, runs, *, scope="nhóm tiến trình"):
        self.current_runs = runs
        for index, run in enumerate(runs, 1):
            item = snapshot(run)
            if self.last_phases.get(item["id"]) != item["phase"]:
                self.emit("PHASE", f"=== {item['label']} · lượt {index}/{len(runs)} === " + PHASE_HELP.get(item["phase"], ""))
                self.last_phases[item["id"]] = item["phase"]
                if item["phase"] == "review":
                    for finding in (run.get("quality") or {}).get("findings", []):
                        self.notices.append(f"{item['id']}: {line(finding)}")
                        self.emit("RESULT", "Cần xem xét kết quả: " + line(finding))
            self.emit("RUN", f"Lượt {index}/{len(runs)} · {item['id']} | {item['label']} | {bar(item['percent'])} | "
                      f"thời gian vật lý {item['physical']} | đã chạy giai đoạn {item['elapsed']} | còn khoảng {item['eta']} | "
                      f"PID {item['pid'] or '—'} | RAM {scope}: {item['ram']}")
        self.summary()

    def resources(self, root=None, *, containers=False):
        root = root or Path.cwd()
        try:
            import psutil
            memory = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=None)
            cpu_text = f"{cpu:.1f}%" if self.cpu_primed else "— (đang lấy mẫu)"
            self.cpu_primed = True
            host = (f"Máy chạy: CPU {cpu_text} | RAM {size(memory.used)}/{size(memory.total)} | "
                    f"RAM khả dụng {size(memory.available)} | Đĩa trống {size(shutil.disk_usage(root).free)}")
            self.resource_rows = [host]
            self.emit("HOST", host)
        except (ImportError, OSError):
            pass
        if containers:
            try:
                result = subprocess.run(["docker", "ps", "-q", "--filter", "label=honeycomb.actions=true"],
                                        capture_output=True, text=True, timeout=3)
                ids = result.stdout.split() if result.returncode == 0 else []
                if not ids or not all(re.fullmatch(r"[a-f0-9]{12,64}", value) for value in ids):
                    self.summary()
                    return
                result = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for record in result.stdout.splitlines():
                        item = json.loads(record)
                        measured = (f"{item.get('Name')} | CPU {item.get('CPUPerc', '—')} "
                                    f"(100%=1 lõi CPU) | RAM {item.get('MemUsage', '—')} | Số tiến trình {item.get('PIDs', '—')}")
                        self.resource_rows.append(measured)
                        self.emit("CONTAINER", measured)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass
        self.summary()

    def transfer(self, label, total):
        return Transfer(self, label, total)


class Transfer:
    def __init__(self, log, label, total):
        self.log, self.label, self.total = log, line(label), total
        self.count = 0
        self.started = self.last = log.clock()
        self.last_count = 0
        self.closed = False

    def advance(self, count):
        self.count += count
        if self.log.clock() - self.last >= 15:
            self.report("Đang truyền · chưa xác minh")

    def report(self, state, *, force=False):
        now = self.log.clock()
        elapsed = now - self.started
        rate = self.count / elapsed if elapsed > 0 else None
        percent = 100 * self.count / self.total if self.total else None
        eta = (self.total - self.count) / rate if self.total and rate else None
        with self.log.lock:
            self.log.transfers[self.label] = {"done": self.count, "total": self.total, "rate": rate, "state": state}
            if force or self.total is None or self.total >= 1024**2:
                self.log.emit("TRANSFER", f"{self.label} | {bar(percent)} | {size(self.count)}/{size(self.total)} "
                              f"| tốc độ trung bình {size(rate)}/s | còn khoảng {duration(eta)} | {state}")
            self.log.summary()
        self.last, self.last_count = now, self.count

    def verified(self):
        if self.total is not None and self.count != self.total:
            raise ValueError("Transfer byte count does not match verified size")
        self.closed = True
        self.report("Đã xác minh", force=False)

    def failed(self, error):
        self.closed = True
        self.report("Lỗi · chưa xác minh", force=True)
        self.log.failure(error, self.label)


_LOGGER = None
_CONFIG = None


def get_actions_log():
    global _LOGGER, _CONFIG
    if os.getenv("HONEYCOMB_ACTIONS_LOG") != "1":
        return None
    config = (os.getenv("GITHUB_STEP_SUMMARY"), os.getenv("HONEYCOMB_LOG_DIR", "output/actions-logs"))
    if _LOGGER is None or _CONFIG != config:
        directory = Path(config[1])
        step = Path(config[0]).name if config[0] else str(os.getpid())
        _LOGGER = ActionsLog(events_path=directory / (step + ".jsonl"))
        _CONFIG = config
    return _LOGGER
