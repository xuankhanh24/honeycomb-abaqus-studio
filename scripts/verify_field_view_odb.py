"""Run with Abaqus Python (2.7 compatible): verify display samples against ODB.

This is a read-only cross-check of actual recorded values, not a solver run or
physical validation. Coordinates, U and unsmoothed element maxima are checked.
"""

from __future__ import print_function

# ruff: noqa: B905
# zip(strict=...) is unavailable in Abaqus Python 2.7.
import hashlib
import json
import math
import sys


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(odb, data):
    comparisons = []
    for frame_index in sorted(set([0, len(data["frames"]) // 2, len(data["frames"]) - 1])):
        displayed = data["frames"][frame_index]
        frame = odb.steps[str(displayed["step"])].frames[displayed["frame"]]
        assert abs(float(frame.frameValue) - displayed["time_s"]) < 1e-12
        for index, mesh in enumerate(data["instances"]):
            inst = odb.rootAssembly.instances[str(mesh["name"])]
            labels = [
                mesh["node_labels"][i]
                for i in sorted(set([0, len(mesh["node_labels"]) // 2, len(mesh["node_labels"]) - 1]))
            ]
            nodes = dict((n.label, n) for n in inst.nodes if n.label in labels)
            for label, node in nodes.items():
                shown = mesh["coordinates"][mesh["node_labels"].index(label)]
                assert all(abs(float(v) - s) < 1e-8 for v, s in zip(node.coordinates, shown))
            if "U" in frame.fieldOutputs:
                for value in frame.fieldOutputs["U"].getSubset(region=inst).values:
                    if value.nodeLabel not in labels:
                        continue
                    try:
                        actual = value.dataDouble
                    except Exception:
                        actual = value.data
                    shown = displayed["instances"][index]["u"][mesh["node_labels"].index(value.nodeLabel)]
                    assert shown is not None
                    error = max(abs(float(v) - s) for v, s in zip(actual, shown))
                    assert all(
                        abs(float(v) - s) <= 1e-7 * max(1.0, abs(float(v))) for v, s in zip(actual, shown)
                    )
                    comparisons.append(
                        {
                            "instance": mesh["name"],
                            "frame": displayed["frame"],
                            "node_label": value.nodeLabel,
                            "field": "U",
                            "max_error_mm": error,
                        }
                    )
            chosen = [
                mesh["elements"][i]
                for i in sorted(set([0, len(mesh["elements"]) // 2, len(mesh["elements"]) - 1]))
            ]
            element_labels = set(e["label"] for e in chosen)
            for field, key in [("S", "mises"), ("PEEQ", "peeq")]:
                if field not in frame.fieldOutputs:
                    continue
                maxima = {}
                for value in frame.fieldOutputs[field].getSubset(region=inst).values:
                    if value.elementLabel not in element_labels:
                        continue
                    if field == "S":
                        actual = float(value.mises)
                    else:
                        try:
                            actual = float(value.dataDouble)
                        except Exception:
                            actual = float(value.data)
                    if not math.isnan(actual) and not math.isinf(actual):
                        maxima[value.elementLabel] = max(maxima.get(value.elementLabel, actual), actual)
                for element in chosen:
                    actual = maxima.get(element["label"])
                    shown = displayed["instances"][index][key][mesh["elements"].index(element)]
                    assert (actual is None) == (shown is None)
                    if actual is not None:
                        assert abs(actual - shown) <= 1e-7 * max(1.0, abs(actual))
                    comparisons.append(
                        {
                            "instance": mesh["name"],
                            "frame": displayed["frame"],
                            "element_label": element["label"],
                            "field": key,
                            "odb_value": actual,
                            "display_value": shown,
                        }
                    )
    return comparisons


if __name__ == "__main__":
    from odbAccess import openOdb

    config = json.load(open(sys.argv[-1]))
    data = json.load(open(config["output"]))
    odb = openOdb(path=str(config["odb"]), readOnly=True)
    try:
        comparisons = verify(odb, data)
    finally:
        odb.close()
    receipt = {
        "kind": "actual-odb-display-cross-check",
        "passed": True,
        "solver_executed": False,
        "linux_qualification": False,
        "scope": "sampled coordinates and U plus element maxima at first/middle/final displayed frames",
        "odb_sha256": sha256(config["odb"]),
        "display_sha256": sha256(config["output"]),
        "comparisons": comparisons,
    }
    with open(config["output"] + ".verification.json", "w") as report:
        json.dump(receipt, report, indent=2)
    print("Verified %d ODB display comparisons" % len(comparisons))
