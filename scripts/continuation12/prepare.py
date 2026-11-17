"""Build offline plans from verified V14 archives; never dispatch or solve."""

import argparse
import hashlib
import json
from pathlib import Path

from contract import CASES, RUNTIME_SHA, verify_plan

PINS = {
    "V14-01": "49ae9a10214ec0776a493d3e5383a641714bbc97da8397202d8d593a8d296896",
    "V14-02": "b1261dba54c3b7428fedec29f97632daf1665047ff1b1738b0afaa9897281739",
    "V14-03": "dd70df8e16be5222ceb8f4607471a4692091eaab77916f07c53bcc0b875728d7",
    "V14-04": "cd7138d42aa2469f47ca370766cd6399e1beb7bfe28a966dd2f2df16bf766775",
    "V14-05": "92660cdad72ee3d76b59282eb43c2ff525e1fa7c4e0c6c1cc85be5f8e7b3970f",
    "CTRL-0245": "54137fa1bd959ab0250c9397663e2c9a0f00f88897d65c83360bb8b3fe9ff2ad",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-sha", required=True)
    parser.add_argument("--design-ids", nargs="+", choices=CASES, default=list(CASES))
    args = parser.parse_args()
    policy = read(Path(__file__).resolve().parents[2] / "docs/validation/v14-automatic-continuation.json")
    for case in args.design_ids:
        source = args.source_study / case / "verified_source"
        manifest = read(source / "artifact-manifest.json")
        receipt_path = next((args.output / case / "preflight").rglob("restart-state.json"))
        if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != PINS[case]:
            raise ValueError("Restart receipt differs: " + case)
        receipt = read(receipt_path)
        raw = receipt_path.parent / "raw"
        job = receipt["job_name"]
        inp = raw / (job + ".inp")
        by_name = {Path(f["path"]).name: f for f in manifest["files"]}
        hashes = {name: record["sha256"] for name, record in receipt["files"].items()}
        for suffix in ("inp", "sta"):
            path = raw / (job + "." + suffix)
            expected = by_name[path.name]["sha256"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Original input/status differs")
            hashes[path.name] = expected
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "continuation98"))
        from continuation_contract import restart_deck

        (args.output / case / "restart_8to12ms.inp").write_text(restart_deck(inp.read_text("ascii")), "ascii")
        data = args.source_study / "tong_hop/data" / case
        resolved = read(data / "resolved.json")
        verification = read(source / "verification.json")
        native = verification["independent_native_history_checks"]
        if (
            not native["independent_history_check_passed"]
            or native["rear_skin_deleted"]
            or native["history_samples"] != 4001
        ):
            raise ValueError("Original 8 ms evidence not verified")
        history = next(
            f["path"] for f in manifest["files"] if f["path"].endswith("/extracted/impact_history.csv")
        )
        plan = {
            "design_id": case,
            "repository": policy["repository"],
            "status": "ready",
            "expected_task_sha": args.task_sha,
            "runtime_source_sha": RUNTIME_SHA,
            "physics_sha256": policy["physics_sha256"],
            "job_name": job,
            "original_restart_receipt": receipt,
            "original_restart_receipt_sha256": PINS[case],
            "restart_source": {"kind": "release", "manifest": manifest},
            "source_native_sha256": hashes,
            "require_all_source_files": True,
            "original_resolved": resolved,
            "original_8ms_manifest": manifest,
            "original_history_path": history,
            "core_mass_kg": native["core_mass_kg"],
            "SEA_8ms_J_kg": native["SEA_core_J_kg"],
            "continuation_attempt": 0,
            "publication_prefix": "continue-v14-12ms-20261117-",
            "automatic_training": False,
            "new_initial_solve_allowed": False,
        }
        verify_plan(plan, args.task_sha, Path.cwd())
        destination = args.output / case / "plan.json"
        if destination.exists():
            raise ValueError("Plan already exists; preserve the original request")
        destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2), "utf-8")
        print(case, "verified original state; prepared native restart deck and immutable plan")


if __name__ == "__main__":
    main()
