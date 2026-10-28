import { test } from "node:test";
import assert from "node:assert/strict";
import { jobState } from "../src/job-state.ts";

test("solver success plus packaging timeout offers packaging without rerunning solver", () => {
    const state = jobState({shards: [{status: "completed", archive_verified: true}],
        workflow: {status: "completed", conclusion: "cancelled"}});
    assert.equal(state.packagingFailed, true);
    assert.equal(state.canRecover, false);
    assert.equal(state.canPackage, true);
});
test("recovery preserves success and waits until the workflow ends", () => {
    const job = {shards: [{status: "completed", archive_verified: true}, {status: "failed"}],
        workflow: {status: "in_progress"}};
    assert.equal(jobState(job).canRecover, false);
    job.workflow.status = "completed";
    assert.equal(jobState(job).canRecover, true);
    assert.equal(jobState(job).complete, 1);
    assert.equal(jobState({...job, recovery_dispatch_pending: true}).canRecover, false);
});
