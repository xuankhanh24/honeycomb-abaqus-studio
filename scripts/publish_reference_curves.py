"""Retain real Windows reference curves with hashes, explicitly separate from cloud acceptance."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = root.parent / "mo_phong"
dest = root / "web/static/reference"
dest.mkdir(parents=True, exist_ok=True)
cases = [
    ("hexagonal", "Tổ ong lục giác · 7 J", "Honeycomb-paper-7J"),
    ("reentrant0", "Re-entrant · 0° · 7 J", "Auxetic-2-orientations-7J/01_image1_0deg"),
    ("reentrant90", "Re-entrant · 90° · 7 J", "Auxetic-2-orientations-7J/02_image2_90deg"),
]
index = []
for identity, name, folder in cases:
    source = base / folder
    history = (source / "impact_history.csv").read_bytes()
    summary = json.loads((source / "simulation_summary.json").read_text())
    if not summary.get("solver_completed"):
        raise ValueError("Only completed reference solver outputs can be published")
    (dest / (identity + ".csv")).write_bytes(history)
    index.append(
        {
            "id": identity,
            "name": name,
            "history": "/reference/" + identity + ".csv",
            "sha256": hashlib.sha256(history).hexdigest(),
            "source": "mo_phong/" + folder,
            "platform": "Windows Abaqus 2017",
            "clamp_mode": "circular",
            "clamp_diameter_mm": 76.4,
            "energy_J": 7,
            "duration_ms": 6,
            "cloud_qualification": False,
            "summary": summary,
        }
    )
(dest / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
