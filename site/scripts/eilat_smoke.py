"""Local Eilat-secondary-price regression; build first, no vendor requests."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from screenshots import DIST, serve


def main() -> int:
    rows = json.loads((DIST / "data/site/cpu.json").read_text(encoding="utf-8"))
    product = next(p for p in rows if p.get("min_price") and p.get("eilat_min_price")
                   and len(p.get("offers") or []) > 1)
    server, port = serve()
    total = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for lang in ("he", "en"):
                for width in (375, 1280):
                    for region in ("main", "eilat"):
                        context = browser.new_context(viewport={"width": width, "height": 812})
                        page = context.new_page()
                        page.add_init_script(
                            "localStorage.setItem('mifrat:view', 'cards');"
                            f"localStorage.setItem('mifrat:lang', {json.dumps(lang)});"
                            f"localStorage.setItem('mifrat:region', {json.dumps(region)});")
                        try:
                            route = f"#/p/cpu/{quote(product['id'], safe='')}"
                            page.goto(f"http://127.0.0.1:{port}/{route}")
                            page.locator(".buybox__price .price-alt").wait_for()
                            layout = page.evaluate("""() => {
                                const group = document.querySelector('.buybox__price');
                                const main = group.querySelector('.price').getBoundingClientRect();
                                const alt = group.querySelector('.price-alt');
                                const rect = alt.getBoundingClientRect();
                                return {mainSize: parseFloat(getComputedStyle(group.querySelector('.price')).fontSize),
                                    altSize: parseFloat(getComputedStyle(alt).fontSize), below: rect.top >= main.bottom,
                                    text: alt.textContent, overflow: document.documentElement.scrollWidth-innerWidth};
                            }""")
                            assert layout["altSize"] < layout["mainSize"], layout
                            assert layout["below"], layout
                            assert layout["overflow"] <= 1, layout
                            if region == "main":
                                assert ("באילת" if lang == "he" else "Eilat") in layout["text"]
                            assert page.locator(".buybar .price-alt").count() == 1
                            page.goto(f"http://127.0.0.1:{port}/#/c/cpu")
                            page.locator('.row[data-id]').first.wait_for()
                            card = page.locator(f'.row[data-id="{product["id"]}"]')
                            if card.count():
                                stores = card.locator(".stores > summary")
                                if stores.count():
                                    stores.click()
                                    assert card.locator(".stores__pop .price-alt").count() > 0
                            search = page.locator(".site-header [data-search-input]")
                            if search.count() and search.is_visible():
                                search.fill(product["name"])
                                page.locator(".search-hit__prices .price-alt").first.wait_for()
                            total += 1
                        finally:
                            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"{total} Eilat display browser cases passed (he/en, mobile/desktop, both regions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
