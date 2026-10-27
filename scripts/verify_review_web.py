"""Verify the actual production control plane and browser without owner credentials."""

import argparse
import hashlib
import json
import os
import re
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from playwright.sync_api import expect, sync_playwright

BASE = "https://honeycomb-abaqus-studio.vercel.app"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/production-web"))
    parser.add_argument("--browser-channel", default=None)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.expected_sha):
        parser.error("expected-sha must be an exact 40-character commit SHA")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"deployment": BASE, "expected_sha": args.expected_sha, "checks": [],
               "catalog_mocked": False, "solver_started": False, "owner_authenticated": False,
               "page_errors": [], "console_errors": [], "console_error_details": []}

    def passed(case, **details):
        receipt["checks"].append({"case": case, "status": "passed", **details})
        print("PASS:", case, flush=True)

    try:
        with httpx.Client(base_url=BASE, timeout=60, follow_redirects=True) as client:
            deadline = time.monotonic() + 240
            observed = None
            while True:
                response = client.get("/api/health", headers={"Cache-Control": "no-cache"})
                if response.status_code == 200:
                    health = response.json()
                    observed = health.get("revision")
                    if observed == args.expected_sha:
                        break
                if time.monotonic() >= deadline:
                    raise AssertionError(f"Production revision {observed!r} did not reach {args.expected_sha}")
                time.sleep(5)
            assert health["worker_started_in_web"] is False and health["test_solver"] is False
            passed("Production health identifies the exact tested commit", revision=observed)
            alias_login = client.get("https://web-swart-phi-64.vercel.app/auth/login", follow_redirects=False)
            assert alias_login.status_code in (302, 307)
            assert alias_login.headers["location"] == BASE + "/auth/login"
            assert "session=" not in alias_login.headers.get("set-cookie", "")
            login = client.get("/auth/login", follow_redirects=False)
            query = parse_qs(urlsplit(login.headers["location"]).query)
            assert query["redirect_uri"] == [BASE + "/auth/callback"] and query["state"][0]
            passed("Legacy web alias redirects before OAuth state; registered HTTPS callback is used")
            response = client.get("/api/session")
            response.raise_for_status()
            assert response.json()["owner"] is False
            response = client.get("/api/status")
            response.raise_for_status()
            run_gates = response.json()["gates"]
            response = client.get("/api/jobs")
            response.raise_for_status()
            jobs = response.json()["jobs"]
            assert isinstance(jobs, list)
            passed("Real management catalog is readable", jobs=len(jobs))
            response = client.get("/api/activity")
            response.raise_for_status()
            activity = response.json()
            assert activity["available"] is True
            for run in activity["runs"]:
                assert run["url"] == f"https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/{run['id']}"
                assert run["status"] in ("queued", "in_progress")
            passed("Live Actions API exposes owned run links without claiming drafts", run_ids=[r["id"] for r in activity["runs"]])
            response = client.get("/api/template")
            response.raise_for_status()
            template = response.json()["spec"]
            denied = client.post("/api/jobs", json={"request_id": args.expected_sha[:32], "spec": template})
            assert denied.status_code == 403
            passed("Anonymous management writes remain denied", http=denied.status_code)
            invalid = deepcopy(template)
            invalid.update(sampling="table", axes=[], designs=[{"energy_J": e} for e in (5, 7, 9)])
            invalid["model"]["loading"] = "velocity"
            response = client.post("/api/preview", json=invalid)
            assert response.status_code == 422 and "Dòng bảng 1:" in response.json()["detail"]
            passed("Production API rejects inactive table loading", http=response.status_code)
            valid = deepcopy(invalid)
            valid["designs"] = [{"loading": "energy", "energy_J": e} for e in (5, 7, 9)]
            response = client.post("/api/preview", json=valid)
            response.raise_for_status()
            data = response.json()
            assert data["count"] == 3
            assert [run["resolved"]["energy_J"] for run in data["runs"]] == [5, 7, 9]
            passed("Production API preserves explicit per-row modes and 5/7/9 J", runs=3)
            response = client.get("/reference/index.json")
            response.raise_for_status()
            references = response.json()
            assert references
            assets = 0
            for reference in references:
                files = [(reference["history"], reference["sha256"])]
                for key in ("field_view", "report"):
                    asset = reference.get(key)
                    if asset:
                        files.append((asset["url"], asset["sha256"]))
                for url, checksum in files:
                    assert url.startswith("/reference/") and ":" not in url and ".." not in url
                    response = client.get(url)
                    response.raise_for_status()
                    assert hashlib.sha256(response.content).hexdigest() == checksum, url
                    assets += 1
            passed("Existing production histories, fields and reports retain their hashes", assets=assets)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel=args.browser_channel)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(60000)
            page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
            def console_message(message):
                if message.type == "error":
                    receipt["console_errors"].append(message.text)
                    receipt["console_error_details"].append({"text": message.text, **message.location})

            page.on("console", console_message)
            try:
                # No routes or API responses are intercepted: use the actual catalog and deployed backend.
                page.goto(BASE, wait_until="networkidle", timeout=90000)
                expect(page.get_by_role("heading", name="Mô hình va chạm", exact=True)).to_be_visible()
                inventory = {"buttons": page.get_by_role("button").all_text_contents(),
                             "summaries": page.locator("summary").all_text_contents()}
                (out / "dom-inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
                summary = next(text for text in inventory["summaries"] if "Toàn bộ input" in text)
                page.get_by_text(summary, exact=True).click()
                editor = page.get_by_role("textbox", name="Input JSON", exact=True)
                preview = page.get_by_role("button", name="Kiểm tra đầu vào", exact=True).last

                def apply(spec):
                    editor.fill(json.dumps(spec, ensure_ascii=False))
                    page.get_by_role("button", name="Áp dụng JSON", exact=True).click()

                def submit():
                    with page.expect_response(lambda r: r.url.endswith("/api/preview")) as pending:
                        preview.click()
                    return pending.value

                assert submit().status == 200
                expect(page.get_by_role("heading", name="1 lượt hợp lệ", exact=True)).to_be_visible()
                passed("Deployed browser default input preview")
                apply(invalid)
                assert submit().status == 422
                expect(page.get_by_role("alert")).to_contain_text("Dòng bảng 1:")
                expect(page.locator(".preview-result")).to_have_count(0)
                page.screenshot(path=str(out / "table-error-desktop.png"), full_page=True)
                passed("Deployed browser shows the wrong loading row and clears stale preview")
                apply(valid)
                assert submit().status == 200
                expect(page.get_by_role("heading", name="3 lượt hợp lệ", exact=True)).to_be_visible()
                expect(page.locator(".preview-result tbody tr")).to_have_count(3)
                expect(page.get_by_role("alert")).to_have_count(0)
                passed("Deployed browser recovers to exactly three valid runs")
                wrong_geometry = deepcopy(template)
                wrong_geometry.update(sampling="table", designs=[{}, {"reentrant_indent": 1}])
                apply(wrong_geometry)
                assert submit().status == 422
                expect(page.get_by_role("alert")).to_contain_text("Dòng bảng 2:")
                passed("Deployed browser identifies the inactive geometry on row two")
                with page.expect_response(lambda r: r.url.endswith("/api/geometry")) as geometry:
                    apply(valid)
                    assert submit().status == 200
                assert geometry.value.status == 200 and len(geometry.value.json()["walls"]) == 234
                page.wait_for_load_state("networkidle")
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(out / "table-valid-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.get_by_role("heading", name="3 lượt hợp lệ", exact=True)).to_be_visible()
                expect(page.locator(".preview-result tbody tr")).to_have_count(3)
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(out / "table-valid-mobile.png"), full_page=True)
                passed("Deployed geometry and mobile preview")
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.get_by_role("button", name="Công việc", exact=True).click()
                expect(page.get_by_role("heading", name="Danh sách bài", exact=True)).to_be_visible()
                expect(page.get_by_role("heading", name="Bắt đầu mô phỏng từ web", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Chạy mô phỏng", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Chạy mô phỏng", exact=True)).to_be_disabled()
                expect(page.get_by_role("button", name="Đăng nhập để chạy", exact=True)).to_be_visible()
                expect(page.locator("#run-start-reason")).to_contain_text("Bạn chưa đăng nhập quản trị")
                if run_gates:
                    page.locator(".run-blockers summary").click()
                    expect(page.locator(".run-blockers")).to_contain_text("điều kiện của backend")
                    for gate in run_gates:
                        expect(page.locator(".run-blockers")).to_contain_text(gate["message"])
                passed("Run action is visible with login guidance and actual backend blockers")
                expect(page.locator("main tbody tr")).to_have_count(len(jobs))
                expect(page.get_by_role("heading", name="Actions đang chạy", exact=True)).to_be_visible()
                page.wait_for_load_state("networkidle")
                links = page.locator(".activity-run a")
                observed_links = []
                for link in links.all():
                    href = link.get_attribute("href")
                    assert re.fullmatch(r"https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/[1-9][0-9]*", href or "")
                    assert link.get_attribute("target") == "_blank"
                    observed_links.append(href)
                passed("Management web renders direct live Actions links", urls=observed_links)
                if jobs:
                    with page.expect_response(lambda r: "/api/jobs/" in r.url) as detail:
                        page.get_by_role("button", name="Mở bài", exact=True).first.click()
                    assert detail.value.status == 200
                    expect(page.locator(".job-detail")).to_be_visible()
                page.screenshot(path=str(out / "management-catalog.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=str(out / "management-actions-mobile.png"), full_page=True)
                passed("Management Actions links fit the mobile viewport")
                page.set_viewport_size({"width": 1440, "height": 1000})
                passed("Real management job list and existing job detail", jobs=len(jobs))
                page.get_by_role("button", name="Dữ liệu", exact=True).click()
                expect(page.get_by_role("heading", name="Kết quả mô phỏng", exact=True)).to_be_visible()
                expect(page.locator(".recharts-line-curve")).to_be_visible()
                canvas = page.locator(".field-view canvas")
                expect(canvas).to_be_visible()
                timeline = page.get_by_role("slider", name="Thời điểm kết quả", exact=True)
                last_frame = timeline.get_attribute("max")
                assert last_frame is not None and int(last_frame) > 0
                timeline.focus()
                timeline.press("End")
                expect(timeline).to_have_value(last_frame)
                expect(canvas).to_have_attribute("aria-label", re.compile(r"6\.000 ms"))
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(out / "management-data.png"), full_page=True)
                passed("Existing force curve and result viewer load; final frame is interactive",
                       displayed_frames=int(last_frame) + 1)
                assert not receipt["page_errors"], receipt["page_errors"]
                # Chrome may request an optional favicon that the application does not declare.
                optional = [e for e in receipt["console_error_details"]
                            if e.get("url") == BASE + "/favicon.ico" and "404" in e["text"]]
                receipt["optional_resource_errors"] = optional
                unexpected = [e for e in receipt["console_error_details"] if e not in optional
                              and not (e.get("url") == BASE + "/api/preview" and "422" in e["text"])]
                assert not unexpected, unexpected
            except Exception:
                page.screenshot(path=str(out / "browser-failure.png"), full_page=True)
                raise
            finally:
                browser.close()
        receipt["status"] = "passed"
    except Exception as error:
        receipt.update(status="failed", error=str(error))
        raise
    finally:
        (out / "production-acceptance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write(f"## Production web: {receipt['status']}\n\nCommit: `{args.expected_sha}`\n\n")
                stream.write("No catalog mocks, owner session or solver dispatch.\n\n")
                for check in receipt["checks"]:
                    stream.write(f"- PASS: {check['case']}\n")
                if receipt.get("error"):
                    stream.write("\nError: " + receipt["error"] + "\n")


if __name__ == "__main__":
    main()
