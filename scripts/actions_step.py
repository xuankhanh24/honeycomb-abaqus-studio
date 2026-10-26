"""Run an environment command with a heartbeat, redacted details and actionable errors."""

import argparse
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

# Also works before uv installs the project; this logger only needs the stdlib.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honeycomb_studio.actions_log import ActionsLog, clean, duration, get_actions_log  # noqa: E402


class StepFailed(RuntimeError):
    def __init__(self, code, details, tail):
        super().__init__(f"Lệnh kết thúc với mã lỗi {code} (exit code {code})")
        self.code, self.details, self.tail = code, str(details), "\n".join(tail)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--heartbeat", type=float, default=15)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.heartbeat <= 0:
        parser.error("Provide a command after -- and a positive heartbeat interval")
    log = get_actions_log() or ActionsLog()
    process = None
    messages = queue.Queue(maxsize=1024)
    tail = deque(maxlen=25)
    child_summary = args.details.with_suffix(".summary.md")
    previous_summary = log.summary_path.read_text(encoding="utf-8") if log.summary_path and log.summary_path.exists() else ""
    try:
        with log.stage(args.title):
            args.details.parent.mkdir(parents=True, exist_ok=True)
            with args.details.open("w", encoding="utf-8") as output:
                child_env = dict(os.environ, GITHUB_STEP_SUMMARY=str(child_summary.resolve()))
                process = subprocess.Popen(command, env=child_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace",
                                           start_new_session=os.name != "nt")

                def consume():
                    for record in process.stdout:
                        messages.put(record)
                    messages.put(None)

                reader = threading.Thread(target=consume, daemon=True)
                reader.start()
                log.emit("PROCESS", f"{args.title} | PID {process.pid} | {Path(command[0]).name} | log: {args.details}")
                started = last_output = time.monotonic()
                next_tick = started
                ended = False
                while not ended:
                    try:
                        record = messages.get(timeout=0.5)
                        if record is None:
                            ended = True
                        else:
                            safe = clean(record)
                            output.write(safe)
                            output.flush()
                            tail.append(safe.rstrip())
                            if re.match(r"^\[\d+:\d+:\d+\] \[[A-Z]+\] ", safe):
                                print(safe, end="", flush=True)
                            last_output = time.monotonic()
                    except queue.Empty:
                        pass
                    now = time.monotonic()
                    if now >= next_tick:
                        log.emit("HEARTBEAT", f"{args.title} | PID {process.pid} | đã chạy {duration(now - started)} | "
                                 f"thông báo gần nhất cách {duration(now - last_output)} | tiến độ: chưa đo được %")
                        log.resources(containers=True)
                        next_tick = now + args.heartbeat
                code = process.wait()
                reader.join(timeout=2)
                if code:
                    raise StepFailed(code, args.details, tail)
                log.emit("DETAILS", f"Log đầy đủ đã che thông tin riêng: {args.details}")
    except StepFailed as error:
        return error.code if error.code > 0 else 128 - error.code
    except KeyboardInterrupt:
        return 130
    except OSError:
        return 1
    finally:
        if process and process.poll() is None:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
        if log.summary_path:
            try:
                current = log.summary_path.read_text(encoding="utf-8") if log.summary_path.exists() else ""
                child = child_summary.read_text(encoding="utf-8") if child_summary.exists() else ""
                log.summary_path.write_text(previous_summary + current + "\n" + child, encoding="utf-8")
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
