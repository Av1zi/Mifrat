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
python -m scraper.mfr corsair --offline     # re-parse the cached pages only (any age), no network
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
| Seasonic, G.Skill, Kingston, ADATA, Crucial | <100 each | **not evaluated** | each is a long tail of <60 products; not worth a fetcher before the larger brands. |

### Round 2 verdicts (checked 2026-10-18)

| Brand | Catalog | Verdict | Why |
| :--- | ---: | :--- | :--- |
| AMD (CPUs) | 111 | **built** | robots disallow only onboarding / search; the English sitemap lists every Ryzen / Threadripper / EPYC page; server-rendered `<dt>/<dd>` spec list (cores, threads, clocks, caches, TDP, socket, architecture, max memory, ECC, iGPU, boxed/tray product ids). Join on (model number, PRO flag) when exactly one page claims it. Older SKUs (Ryzen 5 5600, 3300X, most 7000-series Threadripper PRO) are not in the sitemap and stay unmatched. |
| Intel (ARK + intel.com) | 125 | **fail** | HTTP 403 on `robots.txt` for both `www.intel.com` and `ark.intel.com` with browser headers (WAF). Stop signal: not retried, no workaround. Intel CPU gaps stay on the curated table + reference tiers. |
| NZXT | 37 | **built (cases, fans, AIO)** | Shopify storefront, robots allow products, sitemap lists ~100 handles; server-rendered `tech-specs__row` table with a "Model Number" row naming every colour variant's part number + UPC/EAN, so products join exactly on the identifiers they already carry. A barcode two pages both claim (a multipack repeating the single fan's UPC) is dropped as ambiguous by `store._index`. |
| Thermalright | 49 | **built (narrow)** | robots only block cart/admin; server-rendered `<th>/<td>` spec rows. Slug = model name, so products join on part number == slug or whole-token slug prefix; ~11 pages / ~15 products match (the rest are 2024+ models with no page or no part number). |
| GAMDIAS | 43 | **skip** | robots allow everything and the spec table is embedded in the page as JSON, but the current-lineup pages (Apollo / Argus / Athena / Mars / Talos, Boreas, Chione E1-E2) cover only 5 of the 43 catalog products - the retail names (Aura GCxx, Atlas, Chione E4) have no page. Not worth a fetcher. |
| Fractal Design | 56 | **built (owner override)** | `robots.txt` allows `*` everywhere but `/studio/` and `/api/`, and disallows ClaudeBot / anthropic-ai / GPTBot / CCBot / Google-Extended by name. The fetcher is a plain polite script; on 2026-10-22 the owner chose to read the `/products/` pages anyway (`client.ROBOTS_OVERRIDES`; remove on Fractal's request). `/api/` stays untouched. 40 pages; where maker and retailer disagree the maker is right (Epoch XL sold under Epoch dimensions). |
| SilverStone | 59 | **built** | robots allow; sitemap lists 1,248 pages, 1,050 in scope (PSU wattage variants split per column). Joins on the printed `SST-` code. `model` is not read (short code vs retailer name). Maker PSU connector counts disagree with a retailer in ~10% of 70 overlaps, the maker side being right in the cases checked (EX650R is SFX). |
| Cougar | 20 | **fail** | the server closes the TCP connection without any HTTP answer to a standard browser-header client (`RemoteDisconnected` on `robots.txt`, on both `cougargaming.com` and `www.`, two attempts). Treated as a block; no retry, no workaround. |
| DeepCool | 10 | **skip** | no `robots.txt` and no `sitemap.xml` (404); product URLs are not derivable from names. 10 products. |
| Arctic | 40 | **skip** | `sitemap.xml` is an HTML page, not a machine sitemap, and listing pagination (`?p=`) is disallowed by `robots.txt` (`Disallow: */?`), so the ~40 catalog products cannot be enumerated politely. |
| Maxsun | 102 | **skip** | maxsun.com is a crawlable Shopify store, but the board pages are marketing prose (feature slides) with no spec table in the server HTML. |
| ASUS ROG (rog.asus.com) | ~100 boards | **skip** | host allows crawling, but its product sitemap stops at 2020-era boards (no B650 / X870 / Z890 ROG pages), so the 65 unmatched ASUS boards (mostly ROG Strix / Crosshair / Maximus) have no page to join. |
| Noctua | 96 | **fail (re-checked)** | the product page is a 2 MB Next.js payload without the performance table; the numbers come from `/api/`, which robots.txt disallows. |
| Seasonic | 41 | **skip** | one page per SERIES with several wattages side by side (same problem as Cooler Master PSUs): a wrong-wattage row would outrank the retailer's right one. |
| FSP | 33 PSU | **not evaluated** | long tail; robots allow, but sitemaps are huge / php listings and each is <35 products. |

### Round 3: every field the pages print (re-parsed 2026-10-20)

No new brands and no new hosts: the eight built fetchers re-parse their pages
for every schema field the page states (`python -m scraper.mfr <brand> --offline`
re-parses the cache without touching the network). Measured with
`scripts/fill_report.py` on the same catalog: overall fill 69.2% -> 71.0%,
+1,471 cells, no previously filled cell lost except three that came from a
wrong join (below).

| Brand | Verdict | Now read | Pages do not print (stays null) |
| :--- | :--- | :--- | :--- |
| Antec | **built, extended** | case fan mounts per position, radiator sizes, 3.5"/2.5" bays (separate rows only), lighting (bundled ARGB/RGB fans); PSU connector list (24-pin, EPS, PCIe 6+2/6-pin/8-pin, 12V-2x6, 12VHPWR, SATA, Molex), length, model, colour; AIO radiator length/thickness, connectors, fan rpm/noise from the *Fan* block (the pump's speed was read before); air coolers (rpm, airflow, noise, fan size, TDP, height, lighting); fan PWM. **Joins:** the UPC regex expected 1-5-5-1 digits but Antec prints 0-761345-11647-3, and a rowspan "UPC#" list was read only to its first row - 259 entries gained barcodes. A slug with an `-atx3` revision next to it (ne850-platinum / ne850-platinum-atx3-1) is no longer a part-number key: the retail code names both revisions | case volume, case/AIO colour, combined "3.5\" / 2.5\"" bay rows (combo vs dedicated not said) |
| Corsair | **built, extended** | fan rpm_min (a "±10%" was read as the minimum), static pressure ("mm-H2O" was read as 2.0 on 32 pages), fan quantity (title pack word, or Package Quantity >= 2), case fan positions incl. "None" -> "No", radiator compatibility row, drive bays, lighting, colour; AIO radiator length (Product Length, 1.0-1.25x the size class), colour; PSU length, ATX "v2.4", cable-table connector counts (5 pages); memory lighting and colour. A colour row that contradicts the page title is dropped (the white 2800X page says BLACK) | fan connector, AIO thickness/connectors, PSU PCIe counts on pages without a cable table, case volume |
| Cooler Master | **built, extended** | case fan mounts, radiator sizes (sizes written "280mm" were missed), volume, weight, bays, clearances (alt labels), lighting; every part number / UPC / EAN in the product-number rows (comma lists were joined into one junk key). **AIO series pages** ("360: 394 x 119.6 x 27.2 mm", "(240 LCD Black) MLX-...") are split into one block per radiator size joined on that size's part numbers - the old parse gave a 240 product the 360's radiator; airflow is the CFM figure, not m³/h; connectors | air-cooler TDP |
| ASUS (boards) | **built, extended** | memory speeds (incl. "(O.C.)" lists), physical x16 / x1 slot counts incl. 0, slot kinds, storage interfaces, RAID, audio codec, rear USB ports, Thunderbolt count (0 only when the page names no Thunderbolt / USB4 / 40Gbps port), ECC on any memory line | board lighting (only RGB headers are listed), colour |
| be quiet! | **built, extended** | case fan mounts and radiator sizes (the repeated "Top / Front (mm)" block), expansion slots, GPU length (HDD cage removed), drive bays (max.), lighting (positive only: "LED illumination: -" ignores bundled ARGB fans), model and colour; fan LED; cooler TDP, noise, height (taller of the two dimension rows); AIO radiator dimensions, fan count, connectors | fan min rpm (only 100% PWM is printed) |
| Lian Li | **built, extended** | case fan mounts per position, radiator sizes (thickness footnotes excluded), alternate clearance / slot / I/O labels, volume, weight, lighting, model; PSU connector lists, length, model, ATX version | multi-spot drive descriptions (mounts shared between sizes, no total stated) |
| NZXT | **built, extended** | case fan mounts, volume; AIO fan rpm, airflow, noise, radiator length/thickness, fan count ("3 fans in one frame"), connectors | radiator rows written "Up to N mm" (a partial list would outrank the retailer's full one) |
| Thermalright | **built, extended** | AIO connectors; cooling_other height, fan size, rpm, noise | fan min rpm, TDP |

Values that say a position takes no fan ("None", "N/A", "-") are stored as
"No" (values.coerce reads "None" as unknown, as for lighting). A PSU's full
connector list states the PCIe kinds it lacks, so those are 0. Since schema
v3 (Oct 2026) 12V-2x6 and 12VHPWR are one column (`pcie16_connectors`, the
same 16-pin plug that retailers file under either name); a list naming
neither sets it to 0. A schema bump must run `scripts/migrate_mfr_schema.py`:
`store.py` ignores a file at another version, and the raw page cache is not
committed.

## Adding a brand

1. Run the checklist above by hand (robots, one product page, static values?).
2. `scraper/mfr/<brand>.py` with `BRAND`, `BASE_URL`, `CATEGORIES`, `index(client)`,
   `match(entries_by_key, product)` and `parse(page, category)`; register it in
   `__init__.BRANDS`.
3. `--dry-run` first: the matched/unmatched split tells you whether it is worth fetching.
4. Add the verdict row here and one line to `decisions.md`.

## Sources that need the Nano's home IP (Oct 2026)

Probed with an honestly identified client (`scripts/probe_sources.py`, `MifratSpecBot/1.0`),
from the cloud and from the Nano. Gigabyte, MSI, Kingston, Noctua and Newegg refuse even
a plain `wget` with that name (403 / 429): dropped. Spoofing a browser to get past that is
not done. Newegg also restricts automated access in its terms.

| Source | Cloud | Nano | Verdict |
| :--- | :--- | :--- | :--- |
| LDLC (French retailer) | refused | 200 | **built** (robots.txt disallows `/en/search/` for `*`; narrow `ROBOTS_OVERRIDES` entry under the owner's policy, removable on LDLC's request) as `scraper/xref/ldlc.py`, run by `nano/run_xref.sh`; coolers and case fans so far, more categories as their pages are saved (`nano/save_fixtures.sh`) |
| Supermicro | refused | 200 | **not built**: 23 products (17 boards, 6 cases), 3-4 missing fields each; the page layout differs per product family, so the gain does not cover the maintenance |
