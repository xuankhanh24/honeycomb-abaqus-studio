"""Exercise a missing deployment chunk; real catalog/results, only JS delivery is interrupted."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://honeycomb-abaqus-studio.vercel.app")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("output/native-result-recovery.json"))
    args = parser.parse_args()
    blocked = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()

        def interrupt(route):
            blocked.append(route.request.url)
            route.abort()

        page.route("**/assets/FieldView-*.js", interrupt)
        page.goto(args.base)
        page.get_by_role("button", name="Công việc", exact=True).click()
        page.get_by_role("combobox", name="Chọn bài đã lưu", exact=True).select_option(args.job_id)
        expect(page.get_by_role("button", name="Tải lại trang để mở kết quả", exact=True)).to_be_visible(timeout=30000)
        expect(page.get_by_role("heading", name="Công việc", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Thiết lập", exact=True)).to_be_visible()
        assert blocked, "No dynamic module was interrupted"
        page.unroute("**/assets/FieldView-*.js", interrupt)
        page.get_by_role("button", name="Tải lại trang để mở kết quả", exact=True).click()
        page.get_by_role("button", name="Công việc", exact=True).click()
        page.get_by_role("combobox", name="Chọn bài đã lưu", exact=True).select_option(args.job_id)
        expect(page.locator(".field-view canvas")).to_be_visible(timeout=30000)
        expect(page.get_by_role("button", name="Tải lại trang để mở kết quả", exact=True)).to_have_count(0)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"missing_chunk_contained": True, "management_preserved": True,
                                          "reload_restores_actual_result": True, "job_id": args.job_id}, indent=2))
        browser.close()
    print("PASS: Missing result module preserves management; reload restores the actual solver result")


if __name__ == "__main__":
    main()
