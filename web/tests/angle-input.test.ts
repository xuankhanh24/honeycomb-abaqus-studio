import assert from "node:assert/strict";
import test from "node:test";
import { updateAngleInput } from "../src/angle-input.ts";

test("angle/indent mode roundtrip preserves changed height and nondefault cell geometry", () => {
    const original = {reentrant_geometry: "angle", reentrant_delta_deg: 30,
        reentrant_indent: 1.25, reentrant_cell_height: 6};
    const indent = updateAngleInput(original, "reentrant_geometry", "indent");
    assert.ok(Math.abs(indent.reentrant_indent - Math.sqrt(3)) < 1e-12);
    const angle = updateAngleInput(indent, "reentrant_geometry", "angle");
    assert.ok(Math.abs(angle.reentrant_delta_deg - 30) < 1e-12);
    assert.equal(original.reentrant_indent, 1.25);
});

test("editing an active input keeps its requested value and other requested fields intact", () => {
    const original = {reentrant_geometry: "indent", reentrant_indent: 1.25, reentrant_cell_height: 5};
    const changed = updateAngleInput(original, "reentrant_indent", 2);
    const angle = updateAngleInput(changed, "reentrant_geometry", "angle");
    assert.ok(Math.abs(angle.reentrant_delta_deg - Math.atan(.8) * 180 / Math.PI) < 1e-12);
    assert.equal(changed.reentrant_indent, 2);
    assert.equal(original.reentrant_indent, 1.25);
});
