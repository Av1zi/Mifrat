"""Local Eilat price layout regression; build first, no vendor requests."""
from __future__ import annotations

import json
from itertools import product
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from screenshots import DIST, serve


def main() -> int:
    rows = json.loads((DIST / "data/site/cpu.json").read_text(encoding="utf-8"))
    part = next(p for p in rows if p.get("min_price") and p.get("eilat_min_price")
                and len(p.get("offers") or []) > 1)
    part_route = f"#/p/cpu/{quote(part['id'], safe='')}"
    category_route = f"#/c/cpu?q={quote(part['name'], safe='')}"
    server, port = serve()
    total = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for lang, theme, width, region in product(
                ("he", "en"), ("light", "dark"), (375, 1280), ("main", "eilat")
            ):
                context = browser.new_context(viewport={"width": width, "height": 812})
                page = context.new_page()
                page.add_init_script(
                    "localStorage.setItem('mifrat:view', 'cards');"
                    f"localStorage.setItem('mifrat:lang', {json.dumps(lang)});"
                    f"localStorage.setItem('mifrat:theme', {json.dumps(theme)});"
                    f"localStorage.setItem('mifrat:region', {json.dumps(region)});")
                try:
                    page.goto(f"http://127.0.0.1:{port}/{part_route}")
                    page.locator(".buybox__price .price-alt").wait_for()
                    layout = page.evaluate("""() => {
                        const group = document.querySelector('.buybox__price');
                        const main = group.querySelector('.price');
                        const alt = group.querySelector('.price-alt');
                        const amount = getComputedStyle(alt.querySelector('bdi'));
                        return {mainSize: parseFloat(getComputedStyle(main).fontSize),
                            altSize: parseFloat(amount.fontSize), weight: Number(amount.fontWeight),
                            below: alt.getBoundingClientRect().top >= main.getBoundingClientRect().bottom,
                            text: alt.textContent, overflow: document.documentElement.scrollWidth-innerWidth};
                    }""")
                    assert layout["altSize"] < layout["mainSize"], layout
                    assert layout["below"], layout
                    assert layout["overflow"] <= 1, layout
                    assert page.locator(".buybar .price-alt").count() == 1

                    offers = page.locator(".offers-table")
                    heading = "מחיר באילת" if lang == "he" else "Eilat price"
                    if region == "main":
                        assert ("באילת" if lang == "he" else "Eilat") in layout["text"]
                        assert layout["altSize"] >= 14 and layout["weight"] >= 600, layout
                        assert offers.locator("th.col-eilat-price").inner_text() == heading
                        assert offers.locator("td.col-eilat-price").count() == len(part["offers"])
                        assert offers.locator("td.col-eilat-price .price").count() > 0
                        label = offers.locator("td.col-eilat-price .offer-mobile-label").first
                        assert label.is_visible() == (width < 640)
                    else:
                        assert offers.locator(".col-eilat-price").count() == 0
                        assert offers.locator(".offer-price .price-alt").count() > 0

                    page.goto(f"http://127.0.0.1:{port}/{category_route}")
                    card = page.locator(f'.row[data-id="{part["id"]}"]')
                    card.locator(".row__price .price-alt").wait_for()
                    stores = card.locator(".stores > summary")
                    if stores.count():
                        stores.click()
                        assert card.locator(".stores__pop .price-alt").count() > 0
                    if width >= 1280:
                        page.locator('[data-view="table"]').click()
                        table = page.locator(".list-table")
                        table.wait_for()
                        if region == "main":
                            assert table.locator("th.col-eilat-price").inner_text() == heading
                            row = table.locator(f'tr[data-id="{part["id"]}"]')
                            assert row.locator("td.col-eilat-price .price").is_visible()
                            assert row.locator(".price-alt--eilat").count() == 0
                        else:
                            assert table.locator(".col-eilat-price").count() == 0
                        page.goto(f"http://127.0.0.1:{port}/#/c/cpu")
                        page.wait_for_url("**/#/c/cpu")
                        assert table.evaluate("""(table) => {
                            const wrap = table.closest('.table-wrap').getBoundingClientRect();
                            return [...table.querySelectorAll('thead .col-price')].every((cell) => {
                                const bounds = cell.getBoundingClientRect();
                                return bounds.left >= wrap.left - 1 && bounds.right <= wrap.right + 1;
                            });
                        }"""), "Price columns should fit without horizontal scrolling"
                    search = page.locator(".site-header [data-search-input]")
                    if search.count() and search.is_visible():
                        search.fill(part["name"])
                        page.locator(".search-hit__prices .price-alt").first.wait_for()
                    total += 1
                finally:
                    context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"{total} Eilat display browser cases passed (he/en, light/dark, mobile/desktop, both regions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
