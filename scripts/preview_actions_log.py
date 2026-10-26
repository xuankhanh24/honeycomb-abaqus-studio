"""Exercise log presentation with real loopback transfers and explicitly labelled fixture progress."""

import hashlib
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from honeycomb_studio.actions_log import get_actions_log

PAYLOAD = b"Actions transport test only; no simulation data.\n" * 100000
EXPECTED = hashlib.sha256(PAYLOAD).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        for offset in range(0, len(PAYLOAD), 65536):
            self.wfile.write(PAYLOAD[offset:offset + 65536])
            self.wfile.flush()
            time.sleep(.01)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200 if hashlib.sha256(data).hexdigest() == EXPECTED else 400)
        self.end_headers()
        self.wfile.write(hashlib.sha256(data).hexdigest().encode())


def main():
    log = get_actions_log()
    if log is None:
        raise SystemExit("Enable HONEYCOMB_ACTIONS_LOG=1")
    log.emit("TEST", "CHỈ KIỂM TRA ĐỊNH DẠNG LOG · Không chạy Abaqus hoặc dùng license. Tốc độ bên dưới là HTTP nội bộ, không phải băng thông Internet.")
    log.notices.append("Chỉ dùng dữ liệu mẫu để kiểm tra hiển thị; phần trăm mô phỏng dưới đây không phải kết quả nghiên cứu.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/fixture"
    try:
        with log.stage("Tải xuống qua HTTP nội bộ · dữ liệu kiểm tra"):
            transfer = log.transfer("Tải xuống dữ liệu mẫu nội bộ", len(PAYLOAD))
            received = bytearray()
            with urllib.request.urlopen(url, timeout=10) as response:
                while block := response.read(65536):
                    received.extend(block)
                    transfer.advance(len(block))
            assert hashlib.sha256(received).hexdigest() == EXPECTED
            transfer.verified()
        with log.stage("Tải lên qua HTTP nội bộ · dữ liệu kiểm tra"):
            transfer = log.transfer("Tải lên dữ liệu mẫu nội bộ", len(received))
            def chunks():
                for offset in range(0, len(received), 65536):
                    block = received[offset:offset + 65536]
                    transfer.advance(len(block))
                    yield block
            request = urllib.request.Request(url, data=chunks(), headers={"Content-Length": str(len(received))}, method="POST")
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.read().decode() == EXPECTED
            transfer.verified()
        with log.stage("Kiểm tra bố cục tiến độ · các dòng FIXTURE là dữ liệu mẫu"):
            log.runs([
                {"id": "FIXTURE-solving", "status": "solving", "resolved": {"duration": .006},
                 "progress": {"solver_percent": 32.5, "simulation_time_s": .00195, "phase_elapsed_seconds": 1440, "eta_solver_seconds": 2990}},
                {"id": "FIXTURE-building", "status": "building", "progress": {}},
                {"id": "FIXTURE-review", "status": "review", "progress": {}},
            ])
            log.resources(Path.cwd())
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
