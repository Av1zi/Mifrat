"""
scraper/xref - foreign retailers' spec tables, joined by exact part number.

A retailer abroad that prints a structured spec table AND the manufacturer part
number / EAN on every product page is a second retailer source for products
Israeli vendors describe thinly (case fan mounts, cooler airflow, radiator
lists). Merged at the vendor tier (`vendor`, source `xref:<site>`), so the
brand's own page, Open Icecat and reference rows all outrank it.

    python -m scraper.xref overclockers --dry-run
    python -m scraper.xref overclockers --limit 400
    python -m scraper.xref overclockers --offline

Same politeness contract as scraper/mfr (it uses mfr.client.PoliteClient):
robots.txt obeyed, one request per second, cached pages, 403 / 429 stops the
run. A page is used only when the MPN or EAN it prints equals one of ours.
"""
