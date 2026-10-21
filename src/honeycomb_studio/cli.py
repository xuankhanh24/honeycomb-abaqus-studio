from __future__ import annotations

import argparse
import io
import json
import os
import secrets
import socket
import sys
from pathlib import Path

from .store import Store, write_json


def config_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "HoneycombStudio"


def main():
    parser = argparse.ArgumentParser(description="Honeycomb Studio local engine")
    parser.add_argument("action", choices=["serve", "schema", "reindex"], nargs="?", default="serve")
    parser.add_argument("--data-root", default="C:/UET/DO_AN/honeycomb-data")
    parser.add_argument("--abaqus", default="C:/SIMULIA/Commands/abaqus.bat")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--fake-solver", action="store_true", help="TEST ONLY: no physical simulation")
    args = parser.parse_args()
    if not args.data_root.isascii() or any(c in args.data_root for c in '&|<>^%!"\r\n'):
        parser.error("Abaqus 2017: chọn đường dẫn dữ liệu ASCII, không chứa ký tự điều khiển shell")
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.action == "schema":
        from .models import BatchSpec

        print(json.dumps(BatchSpec.model_json_schema(), ensure_ascii=False, indent=2))
        return
    store = Store(Path(args.data_root))
    if args.action == "reindex":
        print(store.reindex())
        return
    # Single engine per Windows user prevents duplicate workers sharing one catalog.
    settings = config_directory()
    settings.mkdir(parents=True, exist_ok=True)
    lock = (settings / "engine.lock").open("a+b")
    if os.name == "nt":
        import msvcrt

        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit("Honeycomb engine đang chạy; mở lại ứng dụng để kết nối.") from None
    import uvicorn

    from .api import make_app
    from .engine import Engine

    engine = Engine(store, args.abaqus, args.fake_solver)
    token = secrets.token_urlsafe(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    port = sock.getsockname()[1]
    session = settings / "session.json"
    write_json(
        session,
        {
            "url": "http://127.0.0.1:" + str(port),
            "token": token,
            "pid": os.getpid(),
            "data_root": str(store.root),
            "version": "0.1.0",
        },
    )
    print("Honeycomb local engine: http://127.0.0.1:" + str(port), flush=True)
    app = make_app(store, engine, token, settings)
    server = uvicorn.Server(uvicorn.Config(app, log_level="info", access_log=False))
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    try:
        server.run(sockets=[sock])
    finally:
        if session.exists():
            current = json.loads(session.read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid():
                session.unlink()
        lock.close()


if __name__ == "__main__":
    main()
