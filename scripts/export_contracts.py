"""Rebuild committed public schemas from executable models."""

import json
from pathlib import Path

from honeycomb_studio.contracts import PUBLIC_CONTRACTS
from honeycomb_studio.models import BatchSpec, catalogue

root = Path(__file__).resolve().parents[1] / "contracts"
for name, model in {"batch-spec": BatchSpec, **PUBLIC_CONTRACTS}.items():
    (root / (name + ".schema.json")).write_text(
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
(root / "parameters.json").write_text(json.dumps(catalogue(), ensure_ascii=False, indent=2), encoding="utf-8")
