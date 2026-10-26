"""Pin the source tag before a long job lets the default branch advance."""


def reserve_release(github, *, tag, sha, name):
    path = "/git/ref/tags/" + tag
    ref = github.repo("GET", path, allow_missing=True)
    if ref is None:
        head = github.repo("GET", "/git/ref/heads/main")["object"]["sha"]
        if head != sha:
            raise RuntimeError("Source moved before release reservation; no solver started. Reserve a source tag before running the job.")
        ref = github.repo("POST", "/git/refs", {"ref": "refs/tags/" + tag, "sha": sha})
    if ref["object"]["sha"] != sha or ref["object"]["type"] != "commit":
        raise ValueError("Release source tag differs from the exact workflow commit")
    release = github.repo("GET", "/releases/tags/" + tag, allow_missing=True)
    # The by-tag endpoint only finds published releases. Drafts must be found by ID.
    if release is None:
        for page in range(1, 11):
            releases = github.repo("GET", f"/releases?per_page=100&page={page}")
            release = next((r for r in releases if r["tag_name"] == tag), None)
            if release is not None or len(releases) < 100:
                break
        else:
            raise RuntimeError("Release inventory exceeds bounded search; retain artifact and inspect the source tag")
    if release is None:
        release = github.repo("POST", "/releases", {
            "tag_name": tag, "target_commitish": sha, "name": name, "draft": True, "prerelease": True,
            "body": "Reserved before execution. Outputs and scientific quality are not yet established.",
        })
    return release
