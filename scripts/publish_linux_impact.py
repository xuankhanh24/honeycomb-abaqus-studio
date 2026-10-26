"""Publish only checksum-verified real Linux display products alongside old references."""

import hashlib
import json
from pathlib import Path

from honeycomb_studio.cloud_restore import restore, validate_manifest

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "output/impact-7j-manifest/impact-artifact-manifest.json").read_text(encoding="utf-8"))
    validate_manifest(manifest)
    names = ("impact_history.csv", "field-view.json", "summary.json", "quality.json", "run-report.pdf")
    selected = [f for f in manifest["files"] if Path(f["path"]).name in names]
    if sorted(Path(f["path"]).name for f in selected) != sorted(names):
        raise ValueError("Expected exactly one verified source for each display product")
    restored = ROOT / "output/linux-impact-display-source"
    restore(dict(manifest, files=selected, complete=False), restored, allow_incomplete=True)
    paths = {Path(f["path"]).name: restored / f["path"] for f in selected}
    summary = json.loads(paths["summary.json"].read_text(encoding="utf-8"))
    quality = json.loads(paths["quality.json"].read_text(encoding="utf-8"))
    dest = ROOT / "web/static/reference"
    products = {}
    for name, target in (("impact_history.csv", "linux-perimeter-7j.csv"),
                         ("field-view.json", "linux-perimeter-7j-fields.json"),
                         ("run-report.pdf", "linux-perimeter-7j-report.pdf")):
        data = paths[name].read_bytes()
        if name == "impact_history.csv":
            data = data.decode("utf-8-sig").replace("\r\n", "\n").encode("utf-8")
        (dest / target).write_bytes(data)
        products[name] = {"url": "/reference/" + target, "sha256": hashlib.sha256(data).hexdigest(),
                          "bytes": len(data)}
    odbs = [f for f in manifest["files"] if f["path"].endswith("/hc6e049e8eea1.odb")]
    if len(odbs) != 1:
        raise ValueError("Original ODB provenance is missing")
    row = {
        "id": "linux-perimeter-7j", "name": "Re-entrant · 0° · 7 J · Linux · ngàm bốn cạnh",
        "history": products["impact_history.csv"]["url"],
        "sha256": products["impact_history.csv"]["sha256"],
        "source_sha256": odbs[0]["sha256"], "platform": "Linux Abaqus 2020 · CentOS 7 / Ubuntu 22.04",
        "clamp_mode": "perimeter", "energy_J": 7, "duration_ms": 6,
        "cloud_qualification": False, "status": "review", "summary": summary, "quality": quality,
        "field_view": products["field-view.json"], "report": products["run-report.pdf"],
        "source": "GitHub Actions run 40206764997",
        "release_url": "https://github.com/xuankhanh24/honeycomb-abaqus-studio/releases/tag/linux-impact-7j-40206764997",
        "comparison_note": "Ngàm bốn cạnh; các bài Windows cũ dùng ngàm tròn, chưa phải đối chiếu cùng điều kiện.",
    }
    index = json.loads((dest / "index.json").read_text(encoding="utf-8"))
    index = [r for r in index if r["id"] != row["id"]]
    index.insert(0, row)
    (dest / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

