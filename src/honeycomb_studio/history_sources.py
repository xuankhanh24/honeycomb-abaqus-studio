"""Find original histories by run and attempt, including retained research copies."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def candidates(run):
    attempts = run.get("attempts", [])
    if attempts:
        yield Path(attempts[-1]["path"]) / "extracted", "attempt"
    data_root = next((p.parent for p in Path(run["path"]).parents if p.name == "projects"), None)
    if data_root is None:
        return
    retained = data_root.parent / (data_root.name + "-retained") / run["batch_id"]
    metadata = list(retained.glob("*/training/dataset.json"))
    metadata += list((data_root / "datasets").glob("*/dataset.json"))
    metadata.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    attempt = attempts[-1]["number"] if attempts else None
    for file in metadata:
        try:
            item = json.loads(file.read_text(encoding="utf-8"))
            sources = {r["run_id"]: r["attempt"] for r in item.get("source_attempts", [])}
            if run["id"] not in item.get("run_ids", []) or sources.get(run["id"], -1) != attempt:
                continue
            resolved = file.parent / "provenance" / run["id"] / "resolved-input.json"
            if resolved.exists() and json.loads(resolved.read_text(encoding="utf-8")) != run["resolved"]:
                continue
        except (OSError, ValueError, KeyError):
            continue
        yield file.parent / "curves" / run["id"], "retained" if file.is_relative_to(retained) else "dataset"


def load_history(run):
    for directory, kind in candidates(run):
        for name in ("impact_history.csv", "impact_history.parquet"):
            source = directory / name
            if not source.exists():
                continue
            try:
                if source.suffix == ".csv":
                    with source.open(encoding="utf-8-sig", newline="") as stream:
                        raw = list(csv.DictReader(stream))
                else:
                    import pyarrow.parquet as pq

                    raw = pq.read_table(source).to_pylist()
                rows = []
                for row in raw:
                    try:
                        t = (
                            float(row["time_ms"])
                            if row.get("time_ms") not in (None, "")
                            else float(row["time_s"]) * 1000
                        )
                        f = float(row["contact_force_N"])
                        u = float(row["impactor_displacement_mm"])
                        if all(math.isfinite(v) for v in (t, f, u)):
                            rows.append({"time_ms": t, "contact_force_N": f, "impactor_displacement_mm": u})
                    except (ValueError, TypeError, KeyError):
                        continue
                if rows:
                    return {"path": source, "directory": directory, "kind": kind, "rows": rows}
            except (OSError, ValueError):
                continue
    return None
