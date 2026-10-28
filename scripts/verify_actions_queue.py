"""Actions scheduler acceptance fixtures. Never publish these as simulation data."""

import argparse
import hashlib
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["run", "aggregate"])
    parser.add_argument("--range", dest="batch", required=True)
    parser.add_argument("--delta", type=int)
    parser.add_argument("--expected", type=int)
    args = parser.parse_args()
    root = Path("queue-fixtures")
    root.mkdir(exist_ok=True)
    if args.mode == "run":
        start = time.time()
        # Different durations exercise slot reuse; no licensed solver is invoked.
        time.sleep(15 if args.delta == 25 else 2)
        record = {"kind": "scheduler-test-only", "batch": args.batch, "delta": args.delta,
                  "started": start, "finished": time.time(), "simulation_data": False}
        content = json.dumps(record, sort_keys=True).encode()
        path = root / f"{args.batch}-{args.delta}.json"
        path.write_bytes(content)
        path.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest(), encoding="utf-8")
        print(f"Lượt kiểm thử {args.batch} · δ={args.delta}° đã lưu bản ghi và SHA-256; không phải mô phỏng.")
    else:
        paths = sorted(root.rglob(f"{args.batch}-*.json"))
        assert len(paths) == args.expected, f"Thiếu dữ liệu: {len(paths)}/{args.expected}"
        records = []
        for path in paths:
            content = path.read_bytes()
            assert hashlib.sha256(content).hexdigest() == path.with_suffix(".sha256").read_text()
            records.append(json.loads(content))
        assert len({r["delta"] for r in records}) == args.expected
        assert all(r["batch"] == args.batch and not r["simulation_data"] for r in records)
        summary = {"kind": "scheduler-test-only", "batch": args.batch, "runs": records,
                   "aggregated_at": time.time(), "count": len(records)}
        assert summary["aggregated_at"] >= max(r["finished"] for r in records)
        (root / f"summary-{args.batch}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Đợt {args.batch}: tổng hợp sau khi {len(records)}/{args.expected} job kết thúc; SHA-256 hợp lệ.")


if __name__ == "__main__":
    main()
