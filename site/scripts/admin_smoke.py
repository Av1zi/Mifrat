#!/usr/bin/env python
"""Local admin browser regressions; all APIs are stubbed, no live dispatches.

Build first, then run: python site/scripts/admin_smoke.py
Requires Playwright Chromium (same prerequisite as screenshots.py).
"""
from __future__ import annotations

import copy
import functools
import http.server
import json
import socketserver
import threading
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parent.parent
NOW = "2026-11-19T12:00:00Z"
STATUS = {
    "schema": 1, "generated_at": NOW, "window_days": 120,
    "vendors": [{"id": "ksp", "label": "KSP", "host": "home", "active": True,
                 "min_rows": 800, "due_utc": "04:00", "dropped": None}],
    "first_snapshot": {}, "crawls": {},
    "catalog": {"generated_at": NOW, "products": 1, "listings": 1,
                "skipped_vendors": [], "review_queue": 0,
                "vendors": {"ksp": {"listings": 1, "stale": 0, "last_seen": "2026-11-19"}},
                "categories": {"cpu": 1}, "qa": {}, "spec_counts": {}},
}
CHANGES = {
    "schema": 1, "generated_at": NOW, "event_days": 30, "dropped": {}, "absent": [],
    "events": [{"type": "new_product", "at": NOW, "pid": "model:cpu:ryzen-test",
                "product": "Ryzen test processor", "category": "cpu", "vendors": ["ksp"], "price": 100}],
}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> int:
    if not (SITE / "dist" / "admin" / "index.html").exists():
        print("Build first: npm --prefix site run build")
        return 2
    handler = functools.partial(Quiet, directory=str(SITE / "dist"))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/admin/"
    problems: list[str] = []
    total = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        def setup(width: int = 1280, theme: str = "light"):
            context = browser.new_context(viewport={"width": width, "height": 900})
            page = context.new_page()
            page.clock.install(time=datetime(2026, 11, 19, 12, tzinfo=timezone.utc))
            page.add_init_script(f"localStorage.setItem('mifrat:theme', {json.dumps(theme)})")
            calls = {"rebuild": 0, "status": 0, "fail_status": False,
                     "rebuild_status": 202, "rebuild_body": {"ok": True, "started_at": NOW},
                      "stamp": NOW, "paused": None}
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

            def respond(route):
                path = route.request.url.split("?", 1)[0]
                status = 200
                if path.endswith("/status.json"):
                    calls["status"] += 1
                    status = 503 if calls["fail_status"] else 200
                    body = copy.deepcopy(STATUS)
                    body["generated_at"] = calls["stamp"]
                    if calls["paused"]:
                        body["vendors"][0]["paused"] = calls["paused"]
                elif path.endswith("/changes.json"):
                    body = CHANGES
                elif path.endswith("/checks.json"):
                    body = {"schema": 1, "generated_at": NOW, "night": "2026-11-19",
                            "suite": "publish", "escalate_nights": 3, "blocked": False, "checks": []}
                elif path.endswith("/runs"):
                    body = {"runs": []}
                elif path.endswith("/alerts"):
                    body = {"alerts": []}
                else:
                    calls["rebuild"] += 1
                    status, body = calls["rebuild_status"], calls["rebuild_body"]
                route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

            page.route("**/admin/data/*.json", respond)
            page.route("**/api/admin/*", respond)
            return context, page, calls, errors

        def check(name, run, width=1280, theme="light"):
            nonlocal total
            total += 1
            context, page, calls, errors = setup(width, theme)
            try:
                run(page, calls)
                # A handled HTTP failure may be logged by Chromium itself.
                expected_http = {"503"} if calls["fail_status"] else set()
                if calls["rebuild_status"] == 429:
                    expected_http.add("429")
                unexpected = [e for e in errors if not (
                    "Failed to load resource" in e and any(code in e for code in expected_http))]
                assert not unexpected, f"console: {unexpected}"
            except Exception as error:
                problems.append(f"{name}: {str(error).splitlines()[0]}")
            finally:
                context.close()

        def open_page(page, hash_="#new"):
            page.goto(base + hash_)
            page.locator("#reload").filter(has_text="Reload").wait_for()
            page.locator("#main h2").first.wait_for()

        for width in (320, 375, 768, 1280):
            for theme in ("light", "dark"):
                for tab in ("tonight", "calendar", "new", "gone", "prices", "catalog", "log"):
                    def route_check(page, calls, tab=tab):
                        open_page(page, "#" + tab)
                        assert page.locator('#main').inner_text().strip(), "empty screen"
                        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                        assert overflow <= 1, f"horizontal overflow: {overflow}px"
                    check(f"{tab}/{theme}/{width}", route_check, width, theme)

        def search_spaces(page, calls):
            open_page(page)
            search = page.get_by_role("searchbox", name="Search")
            search.fill("Ryzen ")
            page.clock.fast_forward(250)
            assert search.input_value() == "Ryzen ", "search removes spaces while typing"
            assert page.evaluate("document.activeElement.name") == "q", "search lost focus"
        check("search spaces/focus", search_spaces)

        def tab_during_search(page, calls):
            open_page(page)
            page.get_by_role("searchbox", name="Search").fill("Ryzen")
            page.get_by_role("link", name="Prices", exact=True).click()
            page.clock.fast_forward(250)
            assert page.evaluate("location.hash.startsWith('#prices')"), "old search timer changed the current tab"
        check("navigate during search", tab_during_search)

        def paused_source(page, calls):
            calls["paused"] = (
                "Recovery failed (stream HTTP 403); listing/detail timers remain disabled. "
                "Owner-reviewed cooldown and protocol evidence are required before recovery.")
            open_page(page, "#tonight")
            text = page.locator("#main").inner_text()
            assert "KSP collection paused" in text
            assert "Not scraped" not in text and "Nano down" not in text
            assert page.locator(".vcard__state").inner_text() == "Paused"
            assert page.locator(".nb__due").count() == 0
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"paused-source horizontal overflow: {overflow}px"
        for width in (320, 375, 1280):
            check(f"paused source/{width}", paused_source, width)

        def rebuild_once(page, calls):
            open_page(page)
            page.locator("#rebuild").evaluate("b => { b.click(); b.click(); }")
            page.get_by_role("status").wait_for()
            assert calls["rebuild"] == 1, f"dispatched {calls['rebuild']} rebuild requests"
        check("rebuild double click", rebuild_once)

        def reload_failure(page, calls):
            open_page(page)
            calls["fail_status"] = True
            page.locator("#reload").click()
            page.get_by_role("alert").wait_for(timeout=2000)
            assert page.get_by_role("heading", name="New products 1", exact=True).count() == 1, "reload error discarded existing report"
        check("failed reload preserves report", reload_failure)

        def storage_failure(page, calls):
            open_page(page)
            page.evaluate("() => { Storage.prototype.setItem = function() { throw new Error('storage disabled'); }; }")
            page.locator("#rebuild").click()
            page.get_by_role("status").wait_for(timeout=2000)
            assert page.locator("#rebuild").is_disabled(), "rebuild state did not render without session storage"
        check("rebuild without session storage", storage_failure)

        def auth_limit(page, calls):
            calls["rebuild_status"] = 429
            calls["rebuild_body"] = {"error": "Too many login attempts"}
            open_page(page)
            page.locator("#rebuild").click()
            page.get_by_role("alert").wait_for()
            assert page.get_by_role("alert").inner_text() == "Too many login attempts", "auth limit mistaken for running rebuild"
            assert page.locator("#rebuild").is_enabled()
        check("auth rate limit is not a rebuild", auth_limit)

        def cooldown(page, calls):
            calls["rebuild_status"] = 429
            calls["rebuild_body"] = {"error": "Already rebuilding", "retry_in_s": 100}
            open_page(page)
            page.locator("#rebuild").click()
            page.get_by_role("status").filter(has_text="Rebuilding").wait_for()
            assert page.locator("#rebuild").is_disabled()
        check("dispatch cooldown waits for existing rebuild", cooldown)

        def completed_rebuild(page, calls):
            open_page(page)
            page.locator("#rebuild").click()
            page.get_by_role("status").filter(has_text="Rebuilding").wait_for()
            calls["stamp"] = "2026-11-19T12:01:00Z"
            page.clock.fast_forward(20_000)
            page.wait_for_function("document.querySelector('#rebuild')?.disabled === false")
            assert page.evaluate("sessionStorage.getItem('mifrat:ops-rebuild')") is None
        check("rebuild polls and completes", completed_rebuild)

        def older_report(page, calls):
            open_page(page)
            page.locator("#rebuild").click()
            page.get_by_role("status").filter(has_text="Rebuilding").wait_for()
            before = calls["status"]
            calls["stamp"] = "2026-11-19T11:00:00Z"
            page.clock.fast_forward(20_000)
            page.wait_for_function("() => document.querySelector('[role=status]')?.innerText.includes('0:20')")
            assert calls["status"] > before, "poll did not run"
            assert page.locator("#rebuild").is_disabled(), "older report falsely completed rebuild"
        check("older report does not finish rebuild", older_report)
        browser.close()
    server.shutdown()
    server.server_close()
    print(f"{total} admin browser checks, {len(problems)} problems")
    for problem in problems:
        print("  " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
