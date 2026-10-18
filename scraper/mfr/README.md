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
| Cooler Master | 137 | **built (coolers, AIO, cases)** | server-rendered label/value spans; legacy products are absent from the current sitemap. Round 2: every page is fetched and joined on the `product number` / `model number` row it prints (name matching alone reached ~16 products). PSU pages are series pages (several wattages per page): skipped. |
| Antec | 304 | **built (cases, PSU, fans, AIO)** | static HTML + `UPC#` row; the sitemap is stale (2021), so pages are discovered from the category listings too. Round 2: every in-scope page (~300) is fetched and joined on the UPC / slug-as-part-number the page states (name matching alone left 167 of 301 products without a page). |
| Gigabyte | 433 | **fail** | HTTP 403 on `robots.txt` itself with browser headers (WAF). Stop signal: no retry, no workaround. |
| MSI | 141 | **fail** | HTTP 403 on `robots.txt` (WAF). Same rule. |
| Lian Li | 200 | **built (round 2 - the Phase-1 "fail" was wrong)** | the Phase-1 check looked at a page whose tab did not render. robots.txt only blocks cart/log paths, `product-sitemap.xml` lists 135 products and the product pages carry the spec as server-rendered `<th>/<td>` rows (MODEL NO., FAN SPEED, GPU LENGTH CLEARANCE, MAX. DC OUTPUT ...). A family page holds one row block per model, so the runner stores one entry per block (`url#n`) keyed on the MODEL NO. the retailers use as part number. |
| Noctua | 96 | **fail** | Specs ("Performance specifications" tab) load client-side from the CMS; `/api/` is disallowed by robots. |
| be quiet! | 115 | **built (round 2 - category listings, not the sitemap)** | robots allow all; `/en/case`, `/casefans`, `/cpucooler`, `/watercooler`, `/powersupply` link every product as `./<category>/<id>`; each page is a server-rendered technical-data table ending in the Article number (BGW39) and EAN, so products join exactly on identifiers they already carry. |
| Maxsun | 102 | **skip** | one board family, English pages thin; revisit if boards stay the biggest gap. |
| SilverStone, Seasonic, G.Skill, Kingston, ADATA, Crucial | <100 each | **not evaluated** | each is a long tail of <60 products; not worth a fetcher before the larger brands. |

### Round 2 verdicts (checked 2026-10-18)

| Brand | Catalog | Verdict | Why |
| :--- | ---: | :--- | :--- |
| AMD (CPUs) | 111 | **built** | robots disallow only onboarding / search; the English sitemap lists every Ryzen / Threadripper / EPYC page; server-rendered `<dt>/<dd>` spec list (cores, threads, clocks, caches, TDP, socket, architecture, max memory, ECC, iGPU, boxed/tray product ids). Join on (model number, PRO flag) when exactly one page claims it. Older SKUs (Ryzen 5 5600, 3300X, most 7000-series Threadripper PRO) are not in the sitemap and stay unmatched. |
| Intel (ARK + intel.com) | 125 | **fail** | HTTP 403 on `robots.txt` for both `www.intel.com` and `ark.intel.com` with browser headers (WAF). Stop signal: not retried, no workaround. Intel CPU gaps stay on the curated table + reference tiers. |
| NZXT | 37 | **built (cases, fans, AIO)** | Shopify storefront, robots allow products, sitemap lists ~100 handles; server-rendered `tech-specs__row` table with a "Model Number" row naming every colour variant's part number + UPC/EAN, so products join exactly on the identifiers they already carry. A barcode two pages both claim (a multipack repeating the single fan's UPC) is dropped as ambiguous by `store._index`. |
| Thermalright | 49 | **built (narrow)** | robots only block cart/admin; server-rendered `<th>/<td>` spec rows. Slug = model name, so products join on part number == slug or whole-token slug prefix; ~11 pages / ~15 products match (the rest are 2024+ models with no page or no part number). |
| GAMDIAS | 43 | **skip** | robots allow everything and the spec table is embedded in the page as JSON, but the current-lineup pages (Apollo / Argus / Athena / Mars / Talos, Boreas, Chione E1-E2) cover only 5 of the 43 catalog products - the retail names (Aura GCxx, Atlas, Chione E4) have no page. Not worth a fetcher. |
| Fractal Design | 56 | **skip (policy)** | `robots.txt` allows `*` but names ClaudeBot / anthropic-ai / GPTBot / CCBot / Google-Extended and disallows them: the site has asked AI crawlers not to read it. The fetcher is a plain script, not an AI crawler, but the owner has not been asked to override an explicit anti-AI-agent policy, so it is not built. Re-open on the owner's word. |
| Cougar | 20 | **fail** | the server closes the TCP connection without any HTTP answer to a standard browser-header client (`RemoteDisconnected` on `robots.txt`, on both `cougargaming.com` and `www.`, two attempts). Treated as a block; no retry, no workaround. |
| DeepCool | 10 | **skip** | no `robots.txt` and no `sitemap.xml` (404); product URLs are not derivable from names. 10 products. |
| Arctic | 40 | **skip** | `sitemap.xml` is an HTML page, not a machine sitemap, and listing pagination (`?p=`) is disallowed by `robots.txt` (`Disallow: */?`), so the ~40 catalog products cannot be enumerated politely. |
| Maxsun | 102 | **skip** | maxsun.com is a crawlable Shopify store, but the board pages are marketing prose (feature slides) with no spec table in the server HTML. |
| ASUS ROG (rog.asus.com) | ~100 boards | **skip** | host allows crawling, but its product sitemap stops at 2020-era boards (no B650 / X870 / Z890 ROG pages), so the 65 unmatched ASUS boards (mostly ROG Strix / Crosshair / Maximus) have no page to join. |
| Noctua | 96 | **fail (re-checked)** | the product page is a 2 MB Next.js payload without the performance table; the numbers come from `/api/`, which robots.txt disallows. |
| Seasonic | 41 | **skip** | one page per SERIES with several wattages side by side (same problem as Cooler Master PSUs): a wrong-wattage row would outrank the retailer's right one. |
| SilverStone, FSP | 24 / 33 PSU | **not evaluated** | long tail; robots allow, but sitemaps are huge / php listings and each is <35 products. |

## Adding a brand

1. Run the checklist above by hand (robots, one product page, static values?).
2. `scraper/mfr/<brand>.py` with `BRAND`, `BASE_URL`, `CATEGORIES`, `index(client)`,
   `match(entries_by_key, product)` and `parse(page, category)`; register it in
   `__init__.BRANDS`.
3. `--dry-run` first: the matched/unmatched split tells you whether it is worth fetching.
4. Add the verdict row here and one line to `decisions.md`.
