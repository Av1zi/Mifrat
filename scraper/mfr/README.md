# `scraper/mfr/` - manufacturer spec pages (Tier 0.5)

Retailer pages publish thin spec tables; the brand's own product page usually states
what a buyer compares (case clearances, fan airflow, PSU connectors, board slots).
This package fetches those pages politely and writes `data/mfr/<brand>.json`;
`specs/build.py` merges that file as the `manufacturer` tier (above the retailer
payload, below the PCPartPicker reference rows and `data/specs/overrides.json`).

```bash
python -m scraper.mfr --list
python -m scraper.mfr corsair --dry-run     # match catalog products to pages, fetch nothing
python -m scraper.mfr corsair               # fetch (cached 7 days), parse, write data/mfr/corsair.json
python scripts/fill_report.py               # measure
```

## Rules (binding, same as AGENTS.md scraping politeness)

- `robots.txt` obeyed for `*`; a disallowed URL is skipped, never fetched.
- One request per second per host, browser-like headers, no proxies, no evasion.
- A **403 / 429 is a stop signal**: `client.Blocked` ends that brand's run, nothing
  retries. A brand that blocks is dropped (see the verdict table).
- Only pages a catalog product actually matched are fetched; raw HTML is cached under
  `data/mfr/.cache/` (gitignored); only the extracted JSON is committed.
- Matching is **exact**: MPN/UPC when the page URL or body carries one (Corsair,
  Antec), otherwise a unique slug/name-token match. Ambiguous names are skipped - a
  wrong manufacturer row would outrank the retailer's correct one.
- Values go through `common.typed()` (coerce + canonical form + validator), so a
  fetcher cannot ship anything the spec pipeline would have dropped as invalid.
- Run from a home IP / locally; cloud runners are not used for this (no scheduled
  workflow exists on purpose).

## Per-brand feasibility verdicts (checked 2026-10-17)

Catalog share = products carrying that manufacturer name (3,821 products total).

| Brand | Catalog | Verdict | Why |
| :--- | ---: | :--- | :--- |
| Corsair | 383 | **built** | robots allow `/us/en/p/`; product sitemap embeds the MPN; server-rendered `TechSpecItem` tables. Region suffix (-EU/-NA/-WW) dropped for the join. MP600 storage pages have no table (skipped). |
| ASUS | 246 | **built (motherboards)** | robots only block search/filter URLs; global sitemaps list `.../techspec/` pages; server-rendered `rowTableTitle` sections. Graphics cards skipped: catalog names are 90YV... order codes that do not map to slugs. |
| Cooler Master | 137 | **built (coolers, AIO, cases)** | server-rendered label/value spans; legacy products are absent from the current sitemap so only ~16 products match. PSU pages are series pages (several wattages per page): skipped. |
| Antec | 304 | **built (cases)** | static HTML + `UPC#` row; the sitemap is stale (2021) and omits most current models, so only ~23 cases match. |
| Gigabyte | 433 | **fail** | HTTP 403 on `robots.txt` itself with browser headers (WAF). Stop signal: no retry, no workaround. |
| MSI | 141 | **fail** | HTTP 403 on `robots.txt` (WAF). Same rule. |
| Lian Li | 200 | **fail** | WooCommerce pages render the spec tab client-side; the static HTML has no spec values. |
| Noctua | 96 | **fail** | Specs ("Performance specifications" tab) load client-side from the CMS; `/api/` is disallowed by robots. |
| be quiet! | 115 | **skip** | no sitemap (404) and product URLs are not derivable from names; would need category crawling. |
| Maxsun | 102 | **skip** | one board family, English pages thin; revisit if boards stay the biggest gap. |
| SilverStone, Seasonic, Thermalright, G.Skill, Kingston, ADATA, Crucial | <100 each | **not evaluated** | each is a long tail of <60 products; not worth a fetcher before the larger brands. |

## Adding a brand

1. Run the checklist above by hand (robots, one product page, static values?).
2. `scraper/mfr/<brand>.py` with `BRAND`, `BASE_URL`, `CATEGORIES`, `index(client)`,
   `match(entries_by_key, product)` and `parse(page, category)`; register it in
   `__init__.BRANDS`.
3. `--dry-run` first: the matched/unmatched split tells you whether it is worth fetching.
4. Add the verdict row here and one line to `decisions.md`.
