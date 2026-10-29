import { test } from "node:test";
import assert from "node:assert/strict";
import { jobState, shardLabel } from "../src/job-state.ts";

test("queue counts include installing runners without claiming saved solver data", () => {
    const state = jobState({shards: [
        {status: "draft", action_status: "queued"},
        {status: "draft", action_status: "in_progress"},
        {status: "running"}, {status: "completed", archive_verified: true}, {status: "failed"},
    ]});
    assert.equal(state.waiting, 1);
    assert.equal(state.processing, 2);
    assert.equal(state.complete, 1);
    assert.equal(state.failed, 1);
    assert.equal(state.canPackage, true);
    assert.equal(shardLabel({status: "draft", action_status: "in_progress"}), "Đang xử lý trên runner");
});

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

test("a successful later collection clears the old packaging failure only for the same source", () => {
    const job = {status: "completed", workflow_run_id: 12,
        shards: [{status: "completed", archive_verified: true}],
        workflow: {status: "completed", conclusion: "failure"},
        data_collection: {source_complete: true, workflow_run_id: 12, source_status: "completed"}};
    assert.equal(jobState(job).packed, true);
    assert.equal(jobState(job).packagingFailed, false);
    assert.equal(jobState({...job, workflow_run_id: 13}).packed, false);
    assert.equal(jobState({...job, status: "running"}).packed, false);
});
