import assert from "node:assert/strict";
import { test } from "node:test";
import { actionRunUrl } from "../src/action-links.ts";

test("Actions links use the owned repository and a valid run ID", () => {
    assert.equal(actionRunUrl(40336942943), "https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40336942943");
    for (const value of [null, undefined, {}, true, 0, -1, 1.5, Infinity, "javascript:alert(1)", "1/../../evil", "https://evil.test"]) {
        assert.equal(actionRunUrl(value), null);
    }
});
