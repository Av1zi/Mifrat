#!/usr/bin/env python
"""Screenshot + smoke matrix for the built site.

Serves ``site/dist`` (run ``npm run build`` first), then visits every route in
he/en x light/dark x 375/768/1280 and records, per shot:

* console errors / uncaught page errors,
* horizontal overflow (document wider than the viewport),
* a PNG under ``--out`` (default ``site/screenshots/<label>``).

Exit code is non-zero when any console error, horizontal scroll or empty/404
route is found, so the same script doubles as the smoke test.

    python site/scripts/screenshots.py --label before
    python site/scripts/screenshots.py --label after --routes home,category-cpu --langs he

Smoke check (no PNGs; every route in he+en, light theme, 375px and 1280px):

    npm --prefix site run build
    python site/scripts/screenshots.py --smoke     # or: npm --prefix site run smoke

Needs ``pip install playwright`` and ``python -m playwright install chromium``.
Not run in CI (browser install cost); run it before a release or a UI change.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parent.parent
DIST = SITE / "dist"

WIDTHS = {"375": (375, 812), "768": (768, 1024), "1280": (1280, 800)}

# A draft that fills every builder slot (ids from data/site/*.json).
BUILD = {
    "cpu": ["model:cpu:ryzen79800x3d-tray"],
    "motherboard": ["mpn:motherboard:90mb1gc0m0eay0"],
    "memory": ["mpn:memory:f43200c16d32gvk"],
    "storage": ["mpn:storage:snv3s1000g"],
    "gpu": ["mpn:gpu:n506taerooc8gd"],
    "case": ["mpn:case:cc9011296ww"],
    "psu": ["mpn:psu:srpcgx851a5a32sfw"],
}

ROUTES = {
    "home": ("#/", None),
    "categories": ("#/categories", None),
    "category-cpu": ("#/c/cpu", None),
    "category-gpu": ("#/c/gpu?q=rtx", None),
    "category-filtered": ("#/c/motherboard?f.socket=AM5&sort=price_desc", None),
    "category-pick": ("#/c/cpu?pick=cpu", BUILD),
    "product-gpu": ("#/p/gpu/mpn%3Agpu%3An506taerooc8gd", None),
    "product-cpu": ("#/p/cpu/model%3Acpu%3Aryzen79800x3d-tray", None),
    "builder-empty": ("#/build", None),
    "builder-full": ("#/build", BUILD),
    "qa": ("#/qa", None),
    "privacy": ("#/privacy", None),
    "terms": ("#/terms", None),
    "cookies": ("#/cookies", None),
    "notfound": ("#/nope/nothing", None),
}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence request log
        pass


def serve() -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(Quiet, directory=str(DIST))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="shots")
    ap.add_argument("--out", default=None)
    ap.add_argument("--routes", default=",".join(ROUTES))
    ap.add_argument("--langs", default=None, help="default he,en")
    ap.add_argument("--themes", default=None, help="default light,dark (smoke: light)")
    ap.add_argument("--widths", default=None, help="default 375,768,1280 (smoke: 375,1280)")
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="fast pass/fail check: no PNGs, light theme, 375+1280 widths (flags still override)",
    )
    ap.add_argument("--no-images", action="store_true", help="check only, skip PNGs")
    ap.add_argument("--viewport", action="store_true", help="capture the first screen only, not the full page")
    args = ap.parse_args()
    args.langs = args.langs or "he,en"
    args.themes = args.themes or ("light" if args.smoke else "light,dark")
    args.widths = args.widths or ("375,1280" if args.smoke else "375,768,1280")
    if args.smoke:
        args.no_images = True

    unknown = [r for r in args.routes.split(",") if r not in ROUTES]
    if unknown:
        print(f"unknown routes: {', '.join(unknown)} (known: {', '.join(ROUTES)})", file=sys.stderr)
        return 2

    if not (DIST / "index.html").exists():
        print("site/dist missing: run `npm --prefix site run build` first", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else SITE / "screenshots" / args.label
    if not args.no_images:
        out.mkdir(parents=True, exist_ok=True)

    server, port = serve()
    base = f"http://127.0.0.1:{port}/"
    problems: list[dict] = []
    total = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for lang in args.langs.split(","):
            for theme in args.themes.split(","):
                for width in args.widths.split(","):
                    w, h = WIDTHS[width]
                    ctx = browser.new_context(
                        viewport={"width": w, "height": h},
                        locale="he-IL" if lang == "he" else "en-US",
                        color_scheme=theme,
                    )
                    for name in args.routes.split(","):
                        hash_, seed = ROUTES[name]
                        errors: list[str] = []
                        page = ctx.new_page()
                        page.on(
                            "console",
                            lambda m, errors=errors: errors.append(m.text)
                            if m.type == "error"
                            else None,
                        )
                        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                        init = (
                            f"localStorage.setItem('mifrat:lang','{lang}');"
                            f"localStorage.setItem('mifrat:theme','{theme}');"
                        )
                        if seed:
                            init += f"localStorage.setItem('mifrat:build',{json.dumps(json.dumps(seed))});"
                        else:
                            init += "localStorage.removeItem('mifrat:build');"
                        page.add_init_script(init)
                        page.goto(base + hash_, wait_until="networkidle")
                        page.evaluate("document.fonts.ready")
                        page.wait_for_timeout(500)
                        overflow = page.evaluate(
                            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                        )
                        total += 1
                        tag = f"{name} {lang}/{theme}/{width}"
                        if overflow > 1:
                            problems.append({"shot": tag, "overflow_px": overflow})
                        # "Loads" = the shell mounted real content, and only the
                        # notfound route may render the 404 view.
                        rendered = page.evaluate(
                            "({text: (document.getElementById('main-content') || document.body).innerText.trim().length,"
                            " notfound: !!document.querySelector('.notfound')})"
                        )
                        if rendered["text"] == 0:
                            problems.append({"shot": tag, "render": "empty page"})
                        if rendered["notfound"] != (name == "notfound"):
                            problems.append({"shot": tag, "render": "unexpected 404 view" if rendered["notfound"] else "expected 404 view"})
                        for e in errors:
                            # Short links need the Worker; the static server answers POST /api with 501
                            # (expected, the build link falls back to the long URL).
                            if "Failed to load resource" in e and "501" in e:
                                continue
                            problems.append({"shot": tag, "console": e})
                        if not args.no_images:
                            page.screenshot(
                                path=str(out / f"{name}.{lang}.{theme}.{width}.png"),
                                full_page=not args.viewport,
                            )
                        page.close()
                    ctx.close()
        browser.close()
    server.shutdown()

    print(f"{total} shots, {len(problems)} problems")
    for p in problems:
        print("  ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
