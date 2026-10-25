"""Small GitHub App transport and compare-and-swap catalog, independent of the solver."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

import httpx

REPOSITORY = "xuankhanh24/honeycomb-abaqus-studio"
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


class Github:
    def __init__(self, token: str | None = None, client=None):
        self.token = token
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self.expiry = 0.0

    @property
    def configured(self) -> bool:
        return bool(
            self.token
            or all(
                os.getenv(k)
                for k in (
                    "GITHUB_APP_ID",
                    "GITHUB_APP_PRIVATE_KEY",
                    "GITHUB_APP_INSTALLATION_ID",
                )
            )
        )

    def access_token(self) -> str | None:
        if self.token and (not self.expiry or time.time() < self.expiry):
            return self.token
        if not self.configured:
            return None
        import jwt

        now = int(time.time())
        signed = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": os.environ["GITHUB_APP_ID"]},
            os.environ["GITHUB_APP_PRIVATE_KEY"],
            algorithm="RS256",
        )
        response = self.client.post(
            f"https://api.github.com/app/installations/{os.environ['GITHUB_APP_INSTALLATION_ID']}/access_tokens",
            headers={"Authorization": "Bearer " + signed, "Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        self.token = response.json()["token"]
        self.expiry = time.time() + 3000
        return self.token

    def request(self, method: str, path: str, body=None, *, allow_missing=False) -> Any:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = self.access_token()
        if token:
            headers["Authorization"] = "Bearer " + token
        response = self.client.request(method, "https://api.github.com" + path, headers=headers, json=body)
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else None

    def repo(self, method: str, path: str, body=None, **kwargs):
        return self.request(method, f"/repos/{REPOSITORY}" + path, body, **kwargs)


class Catalog:
    branch = "cloud-data"

    def __init__(self, github: Github):
        self.github = github

    def ensure_branch(self):
        if self.github.repo("GET", "/git/ref/heads/" + self.branch, allow_missing=True):
            return
        head = self.github.repo("GET", "/git/ref/heads/main")
        try:
            self.github.repo(
                "POST", "/git/refs", {"ref": "refs/heads/" + self.branch, "sha": head["object"]["sha"]}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422:
                raise

    def get(self, key: str):
        response = self.github.repo(
            "GET", f"/contents/catalog/{key}.json?ref={self.branch}", allow_missing=True
        )
        if response is None:
            return None, None
        return json.loads(base64.b64decode(response["content"])), response["sha"]

    def write(self, key: str, value: dict, sha=None):
        self.ensure_branch()
        body = {
            "branch": self.branch,
            "message": "Update cloud catalog: " + key,
            "content": base64.b64encode(
                json.dumps(value, ensure_ascii=True, allow_nan=False).encode()
            ).decode(),
        }
        if sha:
            body["sha"] = sha
        return self.github.repo("PUT", f"/contents/catalog/{key}.json", body)

    def update(self, key: str, transform):
        for _ in range(5):
            value, sha = self.get(key)
            try:
                updated = transform(value)
                if updated == value:
                    return updated
                self.write(key, updated, sha)
                if key.startswith("jobs/") and (value or {}).get("status") != updated.get("status"):
                    row = {k: updated[k] for k in ("id", "name", "status", "profile")}

                    def index(old):
                        rows = (old or {}).get("jobs", [])
                        return {"jobs": [row] + [r for r in rows if r["id"] != row["id"]]}

                    try:
                        self.update("index", index)
                    except (httpx.HTTPError, RuntimeError):
                        # The job document is authoritative; an index failure must not retry a claim.
                        pass
                return updated
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (409, 422):
                    raise
        raise RuntimeError("Catalog is busy; retry without changing the request ID")

    def jobs(self):
        index, _ = self.get("index")
        return (index or {}).get("jobs", [])
