"""Validation must retain every native history/rear frame without huge field exports."""

import io
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace as Obj

import numpy as np
import pytest

from honeycomb_studio.data import verify_export


def test_validation_reads_every_rear_frame_but_never_serializes_full_field_arrays(tmp_path, monkeypatch):
    frame_times = [0.0, 0.006, 0.012]
    visited = []

    class Metrics:
        def __init__(self, odb):
            self.rows = []

        def frame(self, frame, time):
            visited.append(time)
            self.rows.append({"time_s": time, "rear_downward_mm": time, "rear_deleted_elements": 0})

        def summary(self):
            return {"damage_fields_complete": True, "rear_skin_deleted": False}

    class Heavy:
        description = "Full stress field"
        componentLabels = ["S11", "S22", "S33"]
        type = "TENSOR"
        locations = []
        validInvariants = []

        @property
        def bulkDataBlocks(self):
            raise AssertionError("Validation export traversed the full stress/displacement field")

        @property
        def values(self):
            raise AssertionError("Validation export materialized the full FieldValueArray")

    class Contact:
        description = "Native impactor contact"
        componentLabels = ["F1", "F2", "F3"]

        def getSubset(self, region):
            assert region.name == "IMPACTOR-1"
            return Obj(bulkDataBlocks=[Obj(data=np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))])

    frames = [
        Obj(
            frameValue=time,
            fieldOutputs={
                "S": Heavy(),
                "U": Heavy(),
                "CNORMF General_Contact_Domain": Contact(),
                "CSHEARF General_Contact_Domain": Contact(),
            },
        )
        for time in frame_times
    ]
    series = Obj(description="Original history", data=[(0.0, 100.0), (0.006, 200.0), (0.012, 300.0)])
    instances = {name: Obj(name=name, nodes=[], elements=[]) for name in ["IMPACTOR-1", "BOTTOM-1"]}
    odb = Obj(
        jobData=Obj(version="2020"),
        rootAssembly=Obj(instances=instances, nodeSets={}, elementSets={}),
        sections={},
        close=lambda: None,
        steps={
            "Impact": Obj(
                totalTime=0.0,
                timePeriod=0.012,
                frames=frames,
                historyRegions={"Assembly ASSEMBLY": Obj(historyOutputs={"ALLPD": series})},
            )
        },
    )
    monkeypatch.setitem(sys.modules, "odbAccess", Obj(openOdb=lambda **kwargs: odb))
    monkeypatch.setitem(sys.modules, "cStringIO", Obj(StringIO=io.BytesIO))
    monkeypatch.setitem(sys.modules, "damage_metrics", Obj(RearMetrics=Metrics))
    monkeypatch.setitem(sys.modules, "rear_metrics_bulk", Obj(RearMetrics=Metrics))
    adapters = Path(__file__).parents[1] / "src/honeycomb_studio/adapters"
    monkeypatch.syspath_prepend(str(adapters))
    module = runpy.run_path(str(adapters / "extract.py"))
    module["run"](
        {
            "odb": "native.odb",
            "extract_directory": str(tmp_path),
            "full_fields": False,
            "damage_metrics": True,
            "validation_metrics": True,
        }
    )
    assert visited == frame_times
    history = json.loads((tmp_path / "histories.json").read_text())
    assert history[0]["data"] == [[0.0, 100.0], [0.006, 200.0], [0.012, 300.0]]
    records = [json.loads(p.read_text()) for p in (tmp_path / "reduced-fields").glob("*.json")]
    assert len(records) == 6
    assert all(record["impactor_force_z_N"] == 9.0 for record in records)
    assert {record["time_s"] for record in records} == set(frame_times)
    assert json.loads((tmp_path / "inventory.json").read_text())["export_profile"] == "validation_metrics"
    assert verify_export(tmp_path)["passed"]


@pytest.mark.parametrize("bulk_available", [True, False])
def test_bulk_rear_metrics_match_frozen_reference_for_deletion_and_detachment(bulk_available):
    import importlib.util

    adapters = Path(__file__).parents[1] / "src/honeycomb_studio/adapters"

    def load(name):
        spec = importlib.util.spec_from_file_location(name, adapters / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    instances = {
        name: Obj(
            name=name,
            nodes=[Obj(label=i) for i in range(1, 7)],
            elements=[
                Obj(label=1, connectivity=(1, 2, 3)),
                Obj(label=2, connectivity=(3, 4, 5)),
                Obj(label=3, connectivity=(4, 5, 6)),
            ],
            nodeSets={"PERIMETER_CLAMP": Obj(nodes=[Obj(label=1)])},
        )
        for name in ["CORE-1", "TOP-1", "BOTTOM-1"]
    }
    odb = Obj(rootAssembly=Obj(instances=instances))
    reference = load("damage_metrics").RearMetrics(odb)
    fast = load("rear_metrics_bulk").RearMetrics(odb)

    class Field:
        def __init__(self, values):
            self.values = values

        def getSubset(self, region):
            return Field([v for v in self.values if v.instance.name == region.name])

        @property
        def bulkDataBlocks(self):
            if not bulk_available:
                raise RuntimeError("Native double-precision bulk unavailable")
            values = self.values
            if hasattr(values[0], "nodeLabel"):
                return [Obj(nodeLabels=[v.nodeLabel for v in values], data=[v.data for v in values])]
            return [Obj(elementLabels=[v.elementLabel for v in values], data=[v.data for v in values])]

    for index, (deleted, displacement) in enumerate(
        [
            ([], [0.2] * 6),
            ([], [0.2, -0.8, -1.8, -0.8, -0.8, -0.8]),
            ([2], [0.2, -0.8, -1.8, -100.0, -100.0, -100.0]),
        ]
    ):
        status = Field(
            [
                Obj(
                    instance=instances[name],
                    elementLabel=i,
                    data=0.49 if name == "BOTTOM-1" and i in deleted else 0.5,
                )
                for name in instances
                for i in range(1, 4)
            ]
        )
        u = Field(
            [
                Obj(instance=instances["BOTTOM-1"], nodeLabel=i, data=(0.0, 0.0, z))
                for i, z in enumerate(displacement, 1)
            ]
        )
        frame = Obj(
            fieldOutputs={
                "STATUS": status,
                "U": u,
                **{name: status for name in ["PEEQ", "SDEG", "JCCRT", "TEMP"]},
            }
        )
        reference.frame(frame, index * 0.006)
        fast.frame(frame, index * 0.006)
        assert fast.rows == reference.rows
        assert fast.summary() == reference.summary()
    assert fast.summary()["max_rear_downward_mm"] == 2.0
    assert fast.summary()["deleted_elements_by_instance"]["BOTTOM-1"] == 1


def test_validation_rejects_skipping_rear_frames(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "odbAccess", Obj(openOdb=lambda **kwargs: None))
    adapters = Path(__file__).parents[1] / "src/honeycomb_studio/adapters"
    monkeypatch.syspath_prepend(str(adapters))
    module = runpy.run_path(str(adapters / "validation_metrics.py"))
    with pytest.raises(ValueError, match="every native"):
        module["run"]({"full_fields": False, "damage_metrics": True, "frame_indices": [0]})
