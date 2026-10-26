"""Prepare bounded Actions matrix and finalize interrupted runners without a solver."""

import argparse
import json
import os

from honeycomb_studio.cloud_github import JOB_ID, Catalog, Github
from honeycomb_studio.cloud_matrix import finalize, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "finalize"])
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    if not JOB_ID.fullmatch(args.job_id):
        raise ValueError("Invalid job ID")
    catalog = Catalog(Github(token=os.environ["GITHUB_TOKEN"]))
    workflow = int(os.environ["GITHUB_RUN_ID"])
    transform = prepare if args.phase == "prepare" else finalize
    value = catalog.update("jobs/" + args.job_id, lambda old: transform(old, workflow))
    if args.phase == "prepare":
        matrix = {"include": [{"child_id": s["id"], "index": s["index"]} for s in value["shards"]]}
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("matrix=" + json.dumps(matrix) + "\n")
            out.write("max_parallel=" + str(value["execution"]["effective_parallel_runs"]) + "\n")


if __name__ == "__main__":
    main()
