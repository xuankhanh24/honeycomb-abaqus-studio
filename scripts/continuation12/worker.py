"""Claim before installing; extend once, then automatically recover checkpoints."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from contract import CASES, KEY, claim_segment, verify_plan

from honeycomb_studio.cloud_github import Catalog, Github


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("claim", "run", "finalize"))
    parser.add_argument("--design-id", choices=CASES)
    parser.add_argument("--segment", type=int, default=0)
    parser.add_argument("--root", type=Path, default=Path("/tmp/continuation12"))
    args = parser.parse_args()
    github = Github(token=os.environ["GITHUB_TOKEN"])
    catalog = Catalog(github)
    workflow, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
    if args.action == "finalize":
        states = {case: catalog.get(KEY + case)[0] for case in CASES}
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
            stream.write("## Native 8–12 ms continuation\n\n")
            for case, state in states.items():
                stream.write(f"- {case}: {state['status']} · {state.get('release_url', '')}\n")
        if any(s["status"] != "completed" or s.get("workflow_run_id") != workflow for s in states.values()):
            raise ValueError("Some cases require diagnosis or another verified recovery segment")
        return
    key = KEY + args.design_id
    source_sha = os.environ["TASK_CODE_SHA"]

    def claim(old):
        verify_plan(old, source_sha, Path.cwd())
        if old["repository"] != github.repository:
            raise ValueError("Repository differs")
        return claim_segment(old, segment=args.segment, workflow=workflow, attempt=attempt)

    if args.action == "claim":
        plan = catalog.update(key, claim)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("done=" + str(plan["status"] == "completed").lower() + "\n")
        return
    plan, _ = catalog.get(key)
    verify_plan(plan, source_sha, Path.cwd())
    if (
        plan.get("workflow_run_id") != workflow
        or plan.get("workflow_run_attempt") != attempt
        or plan.get("segment") != args.segment
        or plan["status"] != "preparing"
    ):
        raise ValueError("Missing exclusive claim for this segment")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "continuation98"))
    # The existing readers remain Python 2.7 and are copied by the native worker.
    import importlib.util

    spec = importlib.util.spec_from_file_location("native_8to12", Path(sys.path[0]) / "worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    sys.path.insert(0, str(Path.cwd() / "scripts"))
    from cloud_worker import require_qualification

    from honeycomb_studio.models import digest

    if digest(require_qualification(Path.cwd())) != plan["original_restart_receipt"]["runtime_hash"]:
        raise ValueError("Installed runtime policy differs from original native state")
    root = args.root.resolve()
    if root.exists():
        raise ValueError("Native output directory must be clean")
    root.mkdir(parents=True)

    def update(changes):
        def transform(old):
            if (
                old.get("workflow_run_id") != workflow
                or old.get("segment") != args.segment
                or old.get("workflow_run_attempt") != attempt
            ):
                raise ValueError("Continuation ownership changed")
            return {**old, **changes, "updated_epoch": time.time()}

        catalog.update(key, transform)
        worker.save(
            root / "status.json",
            {"design_id": args.design_id, "segment": args.segment, "workflow_run_id": workflow, **changes},
        )

    worker.execute(plan, root, github, update)
    print(json.dumps({"design_id": args.design_id, "segment": args.segment, "native_initial_solve": False}))


if __name__ == "__main__":
    main()
