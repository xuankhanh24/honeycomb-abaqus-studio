import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
    elementValue,
    validateFieldData,
    verifiedFieldData,
} from "../src/field-data.ts";

const original = JSON.parse(
    readFileSync(
        new URL("../static/reference/reentrant_0-fields.json", import.meta.url),
        "utf8",
    ),
);
test("actual ODB display export retains bounded mesh, labels and null values", () => {
    const d = validateFieldData(original);
    assert.equal(d.frames.length, 13);
    assert.equal(d.source.cloud_qualification, false);
    assert.equal(d.source.clamp_mode, "circular");
    assert.ok(d.sampling.display_elements <= 1000);
    assert.ok(d.frames.at(-1)!.time_s > 0.00599);
    const m = d.instances[0],
        f = structuredClone(d.frames[0].instances[0]);
    f.u[m.elements[0].nodes[0]] = null;
    assert.equal(elementValue(m, f, 0, "u3"), null);
    f.mises[0] = null;
    assert.equal(elementValue(m, f, 0, "mises"), null);
});
test("reject corrupt connectivity, frame length, units and nonfinite values", () => {
    const mutate = (change: (d: any) => void) => {
        const d = structuredClone(original);
        change(d);
        assert.throws(() => validateFieldData(d));
    };
    mutate((d) => (d.instances[0].elements[0].nodes[0] = -1));
    mutate((d) => d.frames[0].instances[0].u.pop());
    mutate((d) => (d.frames[0].instances[0].mises[0] = Infinity));
    mutate((d) => (d.units.coordinates = "m"));
    mutate((d) => d.sampling.display_elements++);
});
test("refuse a payload with the wrong SHA-256", async () => {
    const bytes = new TextEncoder().encode(JSON.stringify(original)).buffer;
    await assert.rejects(verifiedFieldData(bytes, "0".repeat(64)), /SHA-256/);
    const crypto = await import("node:crypto");
    const expected = crypto
        .createHash("sha256")
        .update(new Uint8Array(bytes))
        .digest("hex");
    assert.equal(
        (await verifiedFieldData(bytes, expected)).kind,
        "honeycomb-field-view",
    );
});
