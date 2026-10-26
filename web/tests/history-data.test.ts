import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import test from "node:test";
import { decodeHistory } from "../src/history-data.ts";

test("all published real histories expose measured contact force, matching summary peak", async () => {
    const root = new URL("../static/", import.meta.url);
    const index = JSON.parse(await readFile(new URL("reference/index.json", root), "utf8"));
    for (const reference of index) {
        const raw = await readFile(new URL(reference.history.slice(1), root));
        const rows = await decodeHistory(Uint8Array.from(raw).buffer, reference.sha256);
        const peak = Math.max(...rows.map(row => row.contact_force_N!));
        assert.ok(Math.abs(peak - reference.summary.peak_raw_contact_force_N) < 0.001, reference.id);
        assert.ok(rows.at(-1)!.time_ms! >= 6);
        if (reference.id === "linux-perimeter-7j") assert.equal(rows.at(-1)!.ALLFD_J, null);
    }
});

test("verify exact transport bytes before decoding and reject changed history", async () => {
    const raw = new TextEncoder().encode("\ufefftime_ms,contact_force_N\r\n0,10\r\n");
    const hash = createHash("sha256").update(raw).digest("hex");
    assert.equal((await decodeHistory(raw.buffer, hash))[0].contact_force_N, 10);
    await assert.rejects(decodeHistory(raw.buffer, "0".repeat(64)), /Checksum/);
});
