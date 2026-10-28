"""Prepare bounded Actions matrix and finalize interrupted runners without a solver."""

import argparse
import json
import os

from honeycomb_studio.cloud_github import JOB_ID, Catalog, Github
from honeycomb_studio.cloud_matrix import finalize, prepare, recover
from honeycomb_studio.cloud_release import reserve_release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "finalize"])
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if not JOB_ID.fullmatch(args.job_id):
        raise ValueError("Invalid job ID")
    github = Github(token=os.environ["GITHUB_TOKEN"])
    catalog = Catalog(github)
    workflow = int(os.environ["GITHUB_RUN_ID"])
    transform = (recover if args.recover else prepare) if args.phase == "prepare" else finalize
    value = catalog.update("jobs/" + args.job_id, lambda old: transform(old, workflow))
    if args.phase == "prepare":
        reserve_release(github, tag=f"training-{workflow}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}",
                        sha=os.environ["GITHUB_SHA"], name=f"Dữ liệu huấn luyện tổng hợp · {workflow}")
        reservations = {}
        for shard in value["shards"]:
            if shard["status"] != "draft":
                continue
            release = reserve_release(github, tag="simulation-" + shard["id"],
                                      sha=os.environ["GITHUB_SHA"], name=shard["name"])
            reservations[shard["id"]] = release["id"]

        def retain_reservations(old):
            if old["workflow_run_id"] != workflow:
                raise ValueError("Workflow no longer owns this batch")
            return {**old, "shards": [{**s, "reserved_release_id": reservations[s["id"]]}
                                      if s["id"] in reservations else s for s in old["shards"]]}

        value = catalog.update("jobs/" + args.job_id, retain_reservations)
        matrix = {"include": [{"child_id": s["id"], "index": s["index"], "display_index": s["index"] + 1}
                              for s in value["shards"] if s["status"] == "draft"]}
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("matrix=" + json.dumps(matrix) + "\n")
            out.write("max_parallel=" + str(value["execution"]["effective_parallel_runs"]) + "\n")


if __name__ == "__main__":
    main()
