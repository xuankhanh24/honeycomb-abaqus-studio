"""Import measured solver timings between local catalogs, never simulation files."""

import argparse
import platform
import re
from datetime import datetime
from pathlib import Path

from honeycomb_studio.store import Store, now, write_json

parser = argparse.ArgumentParser()
parser.add_argument("--source", required=True)
parser.add_argument("--target", required=True)
args = parser.parse_args()
source = Store(Path(args.source))
records = []
for run in source.list("runs"):
    if run.get("test_only") or run["status"] not in ("completed", "review"):
        continue
    for attempt in run["attempts"]:
        durations = dict(attempt.get("durations", {}))
        timing_source = "engine monotonic phase measurement"
        if not durations.get("solving"):
            log = Path(attempt["path"]) / "logs/solving.log"
            if log.exists():
                dates = re.findall(
                    r"(?m)^(\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M)\s*$",
                    log.read_text(errors="replace"),
                )
                if len(dates) >= 2:
                    durations["solving"] = (
                        datetime.strptime(dates[-1], "%m/%d/%Y %I:%M:%S %p")
                        - datetime.strptime(dates[0], "%m/%d/%Y %I:%M:%S %p")
                    ).total_seconds()
                    timing_source = (
                        "first/last local timestamp in solver stdout; includes solver input/packager/cleanup"
                    )
        if durations.get("solving", 0) > 1:
            records.append(
                {
                    "model": run["resolved"],
                    "durations": durations,
                    "timing_source": timing_source,
                    "source_run_id": run["id"],
                    "input_hash": run["input_hash"],
                }
            )
if not records:
    raise SystemExit("No completed real solver timings found")
target = Path(args.target)
target.mkdir(parents=True, exist_ok=True)
write_json(
    target / "calibration.json",
    {
        "created_at": now(),
        "machine": platform.processor(),
        "records": records,
        "note": "Measured wall-clock phases on this machine; solver time depends on concurrent load and RAM.",
    },
)
print("Imported", len(records), "measured records")
