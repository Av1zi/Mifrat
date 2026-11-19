#!/usr/bin/env python
"""Local header icon/layout regressions. Build first; needs Playwright Chromium.

Run: python site/scripts/header_smoke.py [--out <screenshot-directory>]
Only serves dist locally; dropdown selections never contact vendor sites.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from screenshots import DIST, serve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="optional 375px before/after review shots")
    args = parser.parse_args()
    if not (DIST / "index.html").exists():
        print("Build first: npm --prefix site run build")
        return 2
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    server, port = serve()
    problems: list[str] = []
    total = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for lang in ("he", "en"):
                for theme in ("light", "dark"):
                    for width in (320, 360, 375, 390, 414, 639, 640, 768, 900, 1280):
                        for route in ("#/", "#/c/cpu"):
                            total += 1
                            tag = f"{route}/{lang}/{theme}/{width}"
                            context = browser.new_context(viewport={"width": width, "height": 812})
                            page = context.new_page()
                            errors: list[str] = []
                            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                            try:
                                page.add_init_script(
                                    f"localStorage.setItem('mifrat:lang', {json.dumps(lang)});"
                                    f"localStorage.setItem('mifrat:theme', {json.dumps(theme)});"
                                )
                                page.goto(f"http://127.0.0.1:{port}/{route}")
                                page.locator("main > *").first.wait_for()
                                page.evaluate("document.fonts.ready")
                                layout = page.evaluate("""() => {
                                    const controls = [...document.querySelectorAll('.site-controls > *')];
                                    const brand = document.querySelector('.hdr-top .brand').getBoundingClientRect();
                                    return {
                                        overflow: document.documentElement.scrollWidth - innerWidth,
                                        controls: controls.map(el => {
                                            const button = el.matches('a, button') ? el : el.querySelector('button');
                                            const rect = button.getBoundingClientRect();
                                            return {
                                                rect: rect.toJSON(),
                                                name: button.getAttribute('aria-label') || button.textContent.trim(),
                                                overlapsBrand: rect.left < brand.right && rect.right > brand.left,
                                                icons: [...button.querySelectorAll('.ic')].map(icon => ({
                                                    rect: icon.getBoundingClientRect().toJSON(),
                                                    nominalWidth: Number(icon.getAttribute('width')),
                                                    nominalHeight: Number(icon.getAttribute('height')),
                                                    chevron: icon.classList.contains('ic-chevron'),
                                                    visible: getComputedStyle(icon).display !== 'none',
                                                })),
                                            };
                                        }),
                                        valuesVisible: [...document.querySelectorAll('.select-menu__value')]
                                            .every(el => getComputedStyle(el).display !== 'none'),
                                    };
                                }""")
                                assert layout["overflow"] <= 1, f"horizontal overflow: {layout['overflow']}px"
                                assert len(layout["controls"]) == 5, "missing header control"
                                assert layout["valuesVisible"] == (width >= 900), "desktop label breakpoint changed"
                                for control in layout["controls"]:
                                    assert control["name"], "control has no accessible name"
                                    assert not control["overlapsBrand"], "control overlaps brand"
                                    rect = control["rect"]
                                    assert rect["left"] >= 0 and rect["right"] <= width, "control outside viewport"
                                    if width < 640:
                                        assert rect["width"] == rect["height"] == 40, "uneven mobile touch target"
                                    for icon in control["icons"]:
                                        assert icon["visible"] == (not icon["chevron"] or width >= 640), "wrong icon visibility"
                                        if not icon["visible"]:
                                            continue
                                        glyph = icon["rect"]
                                        expected_width = 18 if width < 640 else icon["nominalWidth"]
                                        expected_height = 18 if width < 640 else icon["nominalHeight"]
                                        assert abs(glyph["width"] - expected_width) < 0.1, "squeezed SVG width"
                                        assert abs(glyph["height"] - expected_height) < 0.1, "distorted SVG height"
                                        assert glyph["left"] >= rect["left"] and glyph["right"] <= rect["right"], "glyph outside button"

                                if args.out and width == 375 and route == "#/":
                                    page.screenshot(path=str(args.out / f"after-{lang}-{theme}.png"))
                                for dropdown in ("region", "currency", "lang"):
                                    button = page.locator(f"#{dropdown}-btn")
                                    menu = page.locator(f'[data-dropdown="{dropdown}"] [role="listbox"]')
                                    button.click()
                                    assert button.get_attribute("aria-expanded") == "true", "dropdown does not open"
                                    assert menu.is_visible(), "listbox remains hidden"
                                    assert page.locator('.select-menu [role="listbox"]:visible').count() == 1, "two open menus"
                                    menu_rect = menu.bounding_box()
                                    assert menu_rect and menu_rect["x"] >= 0 and menu_rect["x"] + menu_rect["width"] <= width, "menu outside viewport"
                                if args.out and width == 375 and route == "#/":
                                    page.screenshot(path=str(args.out / f"after-{lang}-{theme}-open.png"))
                                page.keyboard.press("Escape")
                                assert page.locator('.select-menu [role="listbox"]:visible').count() == 0, "Escape does not close menu"

                                # Exercise a real selection using the keyboard in both directions.
                                language = page.locator("#lang-btn")
                                language.focus()
                                language.press("ArrowDown")
                                page.keyboard.press("ArrowDown")
                                page.keyboard.press("Enter")
                                expected_lang = "en" if lang == "he" else "he"
                                page.wait_for_function("lang => document.documentElement.lang === lang", arg=expected_lang)
                                assert page.locator(f'[data-dropdown="lang"] [data-value="{expected_lang}"]').get_attribute("aria-selected") == "true"
                                assert not errors, f"page errors: {errors}"
                            except Exception as error:
                                problems.append(f"{tag}: {str(error).splitlines()[0]}")
                            finally:
                                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"{total} header checks, {len(problems)} problems")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
