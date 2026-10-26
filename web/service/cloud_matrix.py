"""One expanded design per hosted runner; atomic parent catalog aggregation."""

from copy import deepcopy

from .models import BatchSpec, digest, expand

TERMINAL = {"completed", "review", "failed", "archive_failed", "cancelled", "timed_out",
            "blocked_license", "blocked_environment", "blocked_platform_policy"}


def matrix_plan(spec):
    spec = BatchSpec.model_validate(spec)
    runs = expand(spec.model_copy(update={"max_runs": 10}))
    if any(r["resolved"]["cpus"] > 4 for r in runs):
        raise ValueError("Mỗi runner cloud có 4 CPU; CPU mỗi lượt phải nằm trong khoảng 1–4.")
    slots = min(len(runs), spec.max_parallel_runs if spec.execution_mode == "parallel" else 1)
    return {"requested_parallel_runs": spec.max_parallel_runs if spec.execution_mode == "parallel" else 1,
            "effective_parallel_runs": slots, "cpu_per_run": runs[0]["resolved"]["cpus"],
            "runner_cpus": 4, "runner_count": len(runs), "architecture": "github-job-per-run",
            "estimate_only": True,
            "note": "Mỗi lượt dùng runner riêng có 4 CPU. Quota GitHub và license có thể làm lượt chờ; RAM/đĩa được kiểm tra trên từng runner."}


def prepare(old, workflow_id):
    if old.get("cancel_requested") or old["status"] not in ("draft", "dispatching"):
        raise ValueError("Batch cannot be claimed; duplicate dispatches and reruns require a new request ID")
    if old.get("workflow_run_id") and old["workflow_run_id"] != workflow_id:
        raise ValueError("Batch belongs to another workflow")
    if digest(old["spec"]) != old["input_hash"]:
        raise ValueError("Requested input digest does not match the catalog")
    plan = matrix_plan(old["spec"])
    expanded = expand(BatchSpec.model_validate(old["spec"]).model_copy(update={"max_runs": 10}))
    shards = []
    for index, run in enumerate(expanded):
        spec = deepcopy(old["spec"])
        spec.update(model=run["requested"], sampling="grid", axes=[], designs=[], max_runs=1,
                    execution_mode="sequential")
        identity = digest({"parent": old["id"], "index": index})[:32]
        shards.append({"id": identity, "name": old["name"], "profile": old["profile"],
                       "parent_job_id": old["id"], "parent_input_hash": old["input_hash"],
                       "index": index, "status": "draft", "spec": spec, "input_hash": digest(spec)})
    return {**old, "workflow_run_id": workflow_id, "status": "running", "phase": "matrix queued",
            "execution": plan, "shards": shards, "runs": []}


def aggregate(parent):
    shards = parent["shards"]
    runs = [{**r, "matrix_index": s["index"], "release_url": s.get("release_url")}
            for s in shards for r in s.get("runs", [])]
    releases = [{"index": s["index"], "url": s["release_url"]} for s in shards if s.get("release_url")]
    statuses = [s["status"] for s in shards]
    status = "running"
    if all(s in TERMINAL for s in statuses):
        status = next((s for s in statuses if s not in ("completed", "review")),
                      "review" if "review" in statuses else "completed")
    return {**parent, "runs": runs, "releases": releases, "status": status,
            "release_url": releases[0]["url"] if releases else None,
            "archive_verified": all(s.get("archive_verified", False) for s in shards),
            "phase": ", ".join(f"{s['index'] + 1}: {s.get('phase', s['status'])}" for s in shards)}


class ShardCatalog:
    """Present one shard to the existing single-run worker, merging via parent CAS.

    Cancellation is inherited from the parent; writes never replace sibling data.
    Child records stay embedded so the public job index has one row per batch.
    """

    def __init__(self, catalog, parent_id, child_id, workflow_id):
        self.catalog, self.key = catalog, "jobs/" + parent_id
        self.child_id, self.workflow_id = child_id, workflow_id

    def _child(self, parent):
        if parent["workflow_run_id"] != self.workflow_id:
            raise ValueError("Matrix worker does not own this workflow")
        return next(s for s in parent["shards"] if s["id"] == self.child_id)

    def get(self, key):
        if key != "jobs/" + self.child_id:
            raise ValueError("Shard cannot access another catalog record")
        parent, sha = self.catalog.get(self.key)
        return {**self._child(parent), "cancel_requested": parent.get("cancel_requested", False)}, sha

    def update(self, key, transform):
        if key == "index":
            return None  # The underlying parent CAS maintains its public index.
        if key != "jobs/" + self.child_id:
            raise ValueError("Shard cannot modify another catalog record")

        def merge(parent):
            child = {**self._child(parent), "cancel_requested": parent.get("cancel_requested", False)}
            updated = transform(deepcopy(child))
            return aggregate({**parent, "shards": [updated if s["id"] == self.child_id else s
                                                   for s in parent["shards"]]})

        parent = self.catalog.update(self.key, merge)
        return self._child(parent)


def finalize(old, workflow_id):
    if not old.get("workflow_run_id") and old["status"] in ("draft", "dispatching"):
        # Preparation can fail before the matrix was created (including qualification).
        return {**old, "workflow_run_id": workflow_id,
                "status": "cancelled" if old.get("cancel_requested") else "blocked_environment",
                "error": "Preparation ended before runners were admitted; inspect the prepare job logs.",
                "archive_verified": False}
    if old.get("workflow_run_id") != workflow_id:
        raise ValueError("Finalizer does not own this batch")
    shards = [{**s, "status": "cancelled" if old.get("cancel_requested") else "blocked_environment",
               "error": "Runner ended before a durable final result; inspect its Actions logs."}
              if s["status"] not in TERMINAL else s for s in old["shards"]]
    return aggregate({**old, "shards": shards})
