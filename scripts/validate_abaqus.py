"""Real licensed acceptance run. Separate catalog; never touches the source model."""

import argparse
import json
import sys
import time
from pathlib import Path

from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec, ModelSpec
from honeycomb_studio.store import Store, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="C:/UET/DO_AN/honeycomb-validation")
    parser.add_argument("--convergence", action="store_true")
    parser.add_argument(
        "--resume", action="store_true", help="Reuse earlier cases and completed solver output"
    )
    parser.add_argument("--smoke", action="store_true", help="Short duration; not scientific validation")
    parser.add_argument("--min-ram-gb", type=float, default=2)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    store = Store(Path(args.root))
    engine = Engine(store)
    presets = ["quick", "reference", "fine"] if args.convergence else ["reference"]
    results = []
    for preset in presets:
        spec = BatchSpec(
            name="Acceptance " + preset,
            model=ModelSpec(
                mesh_preset=preset,
                duration=0.0001 if args.smoke else 0.006,
                field_intervals=4 if args.smoke else 120,
            ),
            render_images=not args.smoke,
            min_available_ram_gb=args.min_ram_gb,
        )
        existing = (
            next(
                (
                    b
                    for b in store.list("batches")
                    if b["name"] == spec.name and b["spec"]["model"]["duration"] == spec.model.duration
                ),
                None,
            )
            if args.resume
            else None
        )
        batch = existing or store.create(spec)
        run = store.list("runs", batch["id"])[0]
        print("BEGIN", preset, batch["id"], flush=True)
        # _execute remains synchronous while progress is durably available in SQLite.
        started = time.monotonic()
        if run["status"] not in ("completed", "review"):
            engine._execute(run, batch)
        finished = store.get("runs", run["id"])
        results.append(
            {
                "preset": preset,
                "batch_id": batch["id"],
                "run_id": run["id"],
                "wall_seconds": time.monotonic() - started,
                "status": finished["status"],
                "error": finished.get("error"),
                "summary": finished.get("summary"),
            }
        )
        write_json(store.root / "acceptance-results.json", results)
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        if finished["status"] not in ("completed", "review"):
            raise SystemExit(1)
    if len(results) == 3:
        keys = ["peak_raw_contact_force_N", "max_top_centre_downward_mm", "contact_duration_ms"]
        comparisons = {
            key: {
                "quick_vs_reference_percent": 100
                * abs(results[0]["summary"][key] - results[1]["summary"][key])
                / max(abs(results[1]["summary"][key]), 1e-12),
                "reference_vs_fine_percent": 100
                * abs(results[1]["summary"][key] - results[2]["summary"][key])
                / max(abs(results[2]["summary"][key]), 1e-12),
            }
            for key in keys
        }
        write_json(
            store.root / "mesh-comparison.json",
            {
                "metrics": comparisons,
                "converged": all(v["reference_vs_fine_percent"] < 5 for v in comparisons.values()),
                "criterion": "5% on peak force, top displacement, duration; not the paper's 2% stress criterion",
            },
        )


if __name__ == "__main__":
    main()
