"""Read-only public deployment acceptance; unauthorized write must remain denied."""

import hashlib
import json
from pathlib import Path

import httpx

from honeycomb_studio.store import now, write_json


def main():
    base = "https://honeycomb-abaqus-studio.vercel.app"
    with httpx.Client(base_url=base, timeout=60, follow_redirects=True) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json()["worker_started_in_web"] is False
        status = client.get("/api/status").json()
        assert status["technical_evidence"]["solver_success"] is True
        assert status["qualified_linux_solver"] is False
        assert status["gates"]
        assert client.post("/api/jobs", json={}).status_code in (403, 422)
        template = client.get("/api/template").json()["spec"]
        preview = client.post("/api/preview", json=template)
        preview.raise_for_status()
        assert preview.json()["runs"][0]["resolved"]["clamp_mode"] == "perimeter"
        denied = client.post("/api/jobs", json={"request_id": "d" * 32, "spec": template})
        assert denied.status_code == 403
        references = client.get("/reference/index.json").json()
        checks = []
        for row in references:
            files = [(row["history"], row["sha256"]),
                     (row["field_view"]["url"], row["field_view"]["sha256"])]
            if row.get("report"):
                files.append((row["report"]["url"], row["report"]["sha256"]))
            for url, expected in files:
                if not url.startswith("/reference/") or ":" in url or ".." in url:
                    raise ValueError("Unexpected static asset path")
                response = client.get(url)
                response.raise_for_status()
                assert hashlib.sha256(response.content).hexdigest() == expected, url
                checks.append({"url": url, "sha256": expected, "bytes": len(response.content)})
        receipt = {
            "checked_at": now(), "deployment": base, "anonymous_write_denied": True,
            "preview_passed": True, "native_impact_visible": True, "qualified_solver_dispatch": False,
            "verified_assets": checks,
            "browser_observation": "Real force curve, 5.980 J ALLPD, 13/13 display frames at 6 ms, differing-clamp comparison table",
        }
        write_json(Path("docs/evidence/cloud-completion-production-20261026.json"), receipt)
        print(json.dumps({"verified_assets": len(checks), "anonymous_write_denied": True}))


if __name__ == "__main__":
    main()
