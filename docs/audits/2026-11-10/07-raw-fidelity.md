# Lane 07: raw fidelity (raw snapshots vs `data/catalog.json`)

- HEAD: `1e353d17` ("docs: CI split, Worker limits, image fetch limits, scoped gh token")
- generated_at: `2026-11-09T22:13:04.288166+00:00` (7095 listings, 4383 products, 0 skipped vendors)
- Pin re-checked at the end: HEAD and generated_at unchanged.
- Note: the pin was first taken at `1534928e`. HEAD moved during the lane; the lane was re-pinned to `1e353d17` and every scan was rerun against it. The generated_at was the same at both pins.

Question: does `data/catalog.json` faithfully carry what the vendors showed?

Short answer: mostly yes for row counts, keys, links and detail joins. Not for TMS prices on 2026-11-09, where two crawls from one day were merged silently.

## Summary

| ID | Finding | Severity | Confidence | Silent or flagged | Scan script |
|---|---|---|---|---|---|
| F1 | TMS 2026-11-09 raw file holds two full crawls; the catalog shows a price from either, 25 listings with an older lower price than the newest crawl | S1 | high (counts), high (cause traced) | silent | `s02c_tms_two_crawls.py` |
| F2 | In-run dedupe keeps the lowest price across TMS rows without a log line; this is the rule that produced F1's prices | S2 | high | silent | `s02_tms_dupes.py`, `s02b_tms_price_conflicts.py` |
| F3 | 112 products hold two offers from the same vendor; `vendor_count` hides it | S2 | high | flagged (111 of 112 as `duplicate_vendor`), 1 silent | `s03_keys_links.py`, `s07_flags.py` |
| F4 | HTML entities (`&#39;&#39`) reach product model text and the public site JSON, though decisions line 117 says they were decoded | S2 | high | silent | `s05_text.py`, `s05b_site_entities.py` |
| F5 | Yahav `vendor_sku` and `mpn` carry U+200E on two listings, from the detail `real_sku` | S3 | high | silent | `s05_text.py` |
| F6 | NBSP and RLM marks in raw titles (TMS, 1PC, Ivory) | S3 | high | silent | `s05_text.py` |

KSP cooler-tag order dependence (scan 8) is a latent risk, not a live error. It is listed under suspicions.

## Method

Pin: `git rev-parse HEAD`, and `generated_at` read from `data/catalog.json`. Both are unchanged at the end.

Shell: PowerShell. Python ran as `python -X utf8 -P` with `PYTHONDONTWRITEBYTECODE=1`. No normalize, spider, download, QA tool, promote, refresh or report run. No npm. Git used only for status, log and show.

Scratch scripts: `tmp/data-audit/07-raw-fidelity/`. Each finding cites its script and output JSON.

- Scan 1, snapshot choice: `s01_snapshot_rows.py` → `s01_out.json`. Each vendor's newest snapshot on disk within 14 days, against the snapshot the listings carry (`last_seen`, `stale`). Result: tms, onepc, ivory and yahav use 2026-11-09. KSP uses 2026-11-07, marked stale. That KSP staleness is accepted in the lane brief and is not a finding.
- Scan 2, row accounting: `s01_snapshot_rows.py`, `s02_tms_dupes.py`. Raw rows to listing keys per vendor. The strict JSON parse and the `load_listings` recovery give the same counts for every vendor (0 bad lines). Zero raw keys missing from listings for every vendor. TMS: 4430 raw rows on 2216 keys, 2214 extra rows.
- Scan 2 (two crawls): `s02c_tms_two_crawls.py` → `s02c_out.json`. Splits the TMS file at the 21:xx hour change into crawl A (2213 rows, 03:32–03:38 UTC) and crawl B (2217 rows, 21:25–21:31 UTC). Git: commit `28cfe190` (2213 items, 05:38 IL) and `4440d3f5` (4430 items, 23:31 IL, +2217 lines).
- Scan 3 and 5, keys and links: `s03_keys_links.py` → `s03_out.json`. Key collisions in raw and catalog, every listing's product id, every offer's listing, every product's offers, aliases.
- Scan 4, field fidelity: `s04_fields.py` → `s04_out.json`. Each listing against its raw row, field by field.
- Scan 6, detail joins: `s06_detail.py` → `s06_out.json`, and `s06b_detail_conflicts.py` → `s06b_out.json`. Mirrors `_merge_detail_specs` (keyed on vendor and `vendor_sku`, last line wins for specs and images).
- Scan 7, text: `s05_text.py` → `s05_out.json`, and `s05b_site_entities.py` → `s05b_out.json` for the public site JSON.
- Scan 8, KSP tags: `s08_ksp_tags.py` → `s08_out.json`. Re-runs `KspSpider._refine_guess` for each cooling tag guess against each raw row.
- Flags: `s07_flags.py` → `s07_out.json`. Checks the 112 same-vendor products and the TMS conflicts against `data/site/qa.json` and `data/review_queue.json`.

Rules used: every raw key, link and field counted in code, not by eye. Examples are 3 to 5 per finding, with product_id, listing_key, vendor, field, observed and verbatim evidence.

## Findings

### F1 (S1): TMS 2026-11-09 holds two crawls; the catalog shows a price from either

- Count: 2216 keys in both crawls. 72 keys differ on price, stock or promo. Of those 72, the catalog takes the B (21:xx) row in 45 and the A (03:xx) row in 27. In 25 keys the newer B price is higher and the catalog shows the older A price (`catalog_price_is_not_B_count` = 25, `s02c_out.json`). In 42 keys the newer B price is lower. Catalog `scraped_at`: 2161 listings at 03:xx, 55 at 21:xx.
- Also: 4 keys appear only in crawl A and 8 only in crawl B. The catalog lists all of them, so presence also differs between the two crawls.
- Examples:
  - `tms:11348-03-20G`, product `model:gpu:9070-amd-pulse-radeon-rx-xt-16gb`, vendor tms, field `price_ils`. Observed: catalog 3750 (A, line 202, `scraped_at` 03:33:08). B (line 2415, 21:25:47) shows 4573. Verbatim, line 2415: `"vendor_sku": "11348-03-20G", ... "price_ils": 4573, "in_stock": false`.
  - `tms:CSSD-F8000GBMP600PLP`, product `model:storage:cssd-f8000gbmp600plp-lpx-mp600-pro-8000gb-pciex4m2-m22280`, field `price_ils`. Catalog 7780; B 8201.
  - `tms:CSSD-F8000GBMP600PXT`, product `model:storage:mp600-pcie4-pro-x4-xt-8000gb-m2pcie-m22280`, field `price_ils`. Catalog 7570; B 7990.
  - `tms:GAMSG532GB5600C38ADC`, product `model:memory:2x16gb-5600-amd-cl38-gemini-32gb-x2-5600mhz-cl38-rgb-grey`, field `price_ils`. Catalog 1958; B 2017.
  - `tms:CP32G56C46U5`, product `model:memory:ddr5-pro-32gb-x1-5600mhz-cl46-black-dimm`, field `price_ils`. Catalog 2079; B 2167.
- Expected: the price from the newest complete crawl of the day, or the day's single crawl. Source for expected: `decisions.md` line 7 (TMS 1 run/day) and the stated rule that a snapshot is one day's vendor view (`GLOSSARY.md`, Snapshot).
- Cause, traced: `nano/run_tms.sh` runs `scrapy crawl tms -s FEEDS=…` straight into `data/raw/<date>/tms.jsonl`, with no `.part` file and no replace step. `nano/pc-parts-il-tms.timer` fires at 21:15 UTC. The success-marker check in `run_tms.sh` runs only when `RUN_TMS_FALLBACK=1`, so the night run does not stop when the 02:50 fallback already wrote the day's crawl. `scraper/run_spider.py` (lines 78–111) does replace atomically, so the append comes from the Nano script path.
- Flagged: no. QA shows 20 of these 72 products under other kinds (variant, duplicate_vendor, identity), none about price (`s07_out.json`).
- Fix direction: stop the second TMS run on the same day (the timer must honour the success marker, or the night run must write `.part` and replace), then have normalize take the newest complete crawl per key instead of the lowest price (see F2).

### F2 (S2): the in-run dedupe keeps the lowest price and logs nothing

- Count: 2216 TMS keys on 4430 raw rows. 2214 extra rows. 2122 duplicate pairs are byte-identical. 82 divergent groups: 67 price, 5 stock, 7 URL (`s02_out.json`, `s02b_out.json`). Every one of the 67 price groups is an across-crawl pair, and the catalog kept the minimum (`catalog=min` 67 of 67).
- Examples:
  - `tms:CD8068904571901`, product `model:cpu:8360y-tray`, vendor tms, lines 1 and 2214, identical, bundle-only, price null. Shows the identical-pair pattern.
  - `tms:SST-HA2500R-PM`, product `model:psu:2500rz-fully-hela-modular-2500w-full`, lines 101, 1615, 2314, 3828, identical price 2949.
  - `tms:11348-03-20G` (see F1): min rule keeps 3750 over 4573.
- Expected: one row per key from the newest crawl. Source: `scraper/matching.py` `dedupe_enriched_listings` keeps the lowest price, not the newest `scraped_at`.
- Cause, traced: `dedupe_enriched_listings` (line ~1898) sorts by price. It has no log for the rows it drops.
- Flagged: no.
- Fix direction: dedupe on newest `scraped_at` per key, and log dropped rows with their count.

### F3 (S2): 112 products hold two offers from one vendor

- Count: 112 products, `products_same_vendor_twice` in `s03_out.json`. Mix: ksp 43, 1pc 29, yahav 20, tms 12, 1pc+tms 3, ivory 4, 1pc+ksp 1. `vendor_count` equals the distinct vendor count, so this is invisible in `vendor_count`.
- Flagged: 111 of 112 are QA cases `duplicate_vendor` in `data/site/qa.json` (checked by exact product id). The one unflagged is listed below.
- Examples:
  - `model:memory:3-32gbx2-6000mhz-64gb-beast-certified-cl30-ddr5-expo-fury-rgb-xmp-64gb-6000mhz-cl30-rgb`, vendor yahav, listing_keys `yahav:10617` (price 4790) and `yahav:11789` (price 4830). Same MPN `KF560C30BBEA-32X2`. Unflagged.
  - `model:aio:17-2dba-85-85cfm-le520-240mm-white`, vendor yahav, `yahav:9343` and `yahav:9466`. Flagged.
  - `model:aio:1cfm-63-aio-h150i-icue-lcd-link-360mm-white`, vendor yahav, `yahav:9877` and `yahav:9499`. Flagged.
- Expected: one offer per vendor per product, or the two offers flagged as variants. Source: `decisions.md` line 28 (ambiguous identity evidence merges and is flagged on the QA page).
- Cause: not traced. Merge logic, not this lane.
- Fix direction: flag the yahav pair as `duplicate_vendor`; decide whether `vendor_count` should count offers instead of vendors.

### F4 (S2): HTML entities reach product text and the public site

- Count: 99 Ivory listing titles keep `&#39;` in `title_raw` (raw carries it too, `s05_out.json`). 21 product `model` fields hold `&#39;&#39` with no closing semicolon. Public site JSON: `data/site/case_fan.json` (36 string values: 18 `model`, 18 `specs/model`), `cpu_cooler.json` (6), `qa.json` (15), `spec_report.json` (6), per `s05b_out.json`.
- Examples:
  - `model:aio:240-a24-alpha2-se-240mm-black`, field `product.model`, value `ALPHA2 SE A24 240 &#39;&#39`.
  - `model:case_fan:1-12-3-za-120mm-3-rgb-black`, field `product.model`, value `3 -1 Jonsbo ZA- 12 &#39;&#39`.
  - `ivory:112283`, product `model:case_fan:a14x25r-g2-nf-pwm-140mm-1-brown`, field `title_raw`, verbatim `מאוורר למארז 14 ס&#39;&#39;מ Noctua NF-A14x25r G2 PWM`.
  - `ivory:124272`, product `model:case_fan:12-gt120-120mm-1-rgb-black`, field `title_raw`, verbatim `מאוורר למארז 12 ס&#39;&#39;מ Ivory Gaming GT120 ARGB`.
  - `data/site/qa.json` offer title: `קירור נוזלי למעבד CORSAIR NAUTILUS 240 RS – גודל 240 מ&#39;&#39;מ – צבע שחור`.
- Expected: decoded text. Source: `decisions.md` line 117 (2026-11-10 duplicate pass 2: "HTML entities decoded in model text (99 Ivory rows, 27 pid renames, aliased)"). The decode covers the `;`-terminated form only, and the 21 models keep the broken `&#39;&#39` form.
- Cause, suspected (unverified): the decode pattern requires the trailing `;`, so the `&#39;&#39` form (no final `;`) survives. Not traced in code.
- Flagged: no.
- Fix direction: decode `&#39` with and without the trailing semicolon in model and title text; then re-check the public site JSON.

### F5 (S3): U+200E in Yahav part numbers

- Count: 2 listings. Both carry U+200E in `vendor_sku` and `mpn` (`s05_out.json`, `invisible_mpn_offers` = 2; split from the bare part number = 0).
- Examples:
  - `yahav:7575`, product `model:case_fan:2-2x140mm-core-elite-icue-included-node-pack-rgb-series-sp140-triple-white-140mm-2-rgb-white`, field `vendor_sku`/`mpn`, value `'\u200eCO-9050139-WW'`.
  - `yahav:8419`, product `model:case_fan:52cfm-af120-air-led-series-triple-120mm-3-rgb-white`, field `vendor_sku`/`mpn`, value `'\u200eCO-9050082-WW'`.
- Expected: the bare part number. Source: raw `detail/yahav.jsonl` `real_sku` has the mark; the merge copies it (`normalize_and_match._merge_detail_specs`, real_sku path).
- Cause, traced: `real_sku` copied with the mark.
- Flagged: no. Matching still merges these with the Ivory twin (same product), so no split observed.
- Fix direction: strip U+200E/U+200F in `_merge_detail_specs` before the SKU and MPN are set.

### F6 (S3): NBSP and RLM marks in raw titles

- Count (raw newest snapshot, `s05_out.json`): TMS 2 NBSP and 3 RLM titles; 1PC 8 RLM and 1 LRM; Ivory 6 RLM titles and 19 RLM in `vendor_meta.description`.
- Examples:
  - `tms:CO-9050073-WW`, product `model:case_fan:9050073-co-ll140-ww-140mm-rgb-black`, field `title_raw`, RLM U+200F in `‏140mm`.
  - `tms:CP-9020336-EU`, product `model:psu:1-3-cybenetics-rm850e-850w-full`, field `title_raw`, RLM before `850W`.
  - `tms:CD8068904571901`, product `model:cpu:8360y-tray`, field `title_raw`, NBSP in `36-core (72-VC)`.
- Expected: text without invisible marks. Source: visible text is the same; this is hygiene.
- Cause: source-side (the vendor's page carries the marks).
- Flagged: no.
- Fix direction: strip NBSP and RLM in title normalization.

## Suspicions (not confirmed)

- **S-a, KSP cooler tag order (latent, scan 8, `s08_out.json`).** Tags 182 (air) and 1329 (liquid) never disagree (0 rows). Tag 186 (case-fan leaf) returns `case_fans` before the liquid check, so 116 cooler rows would change if 186 claimed the uin first. Tags 187/188 force `accessories`: 209 rows would change if 187 or 188 claimed first. Examples:
  - line 638, `Liquid Freezer III Pro 360 A-RGB`, raw `cpu_cooler_aio`. Under 186 it becomes `case_fans`.
  - line 639, `Arctic Freezer 36`, raw `cpu_cooler_air`. Under 186 it becomes `case_fans`.
  - line 830, `משחה תרמית 4 גרם Arctic MX-7 …`, raw `accessories`. Under 182 it becomes `cpu_cooler_air` (no accessory title rule matches paste).
  - line 908, `מאוורר NF-A14x25r G2 PWM מבית Noctua`, raw `case_fans`. Under 182 it becomes `cpu_cooler_air`.
  - Expected: the category the row's own title and type tag give. Membership of each uin in each tag is not recorded in raw, so this is unverified.
  - Fix direction: make the 186/187/188 branches read title and type tag like the other branches, so claim order cannot matter.
- **S-b, TMS keys present in only one crawl.** 4 keys only in crawl A (`tms:CMH16GX5M1D6000Z38`, `tms:CP-9020271-EU`, `tms:NH-U9SCH-BK`, `tms:T120`) and 8 only in crawl B (`tms:BK036`, `tms:BW015`, `tms:CL-B50-ARGB`, `tms:CO-9050184-WW`, `tms:CP-9020329-EU`, `tms:GSK850V2`, `tms:TS4-360-WH`, `tms:0-761345-40031-2`). Not known whether real delist or crawl noise. Part of F1.
- **S-c, detail specs that disagree between duplicate rows.** TMS: 136 SKUs have differing duplicate detail rows, but in each case the other rows have empty `specs` (only 6 SKUs have no non-empty spec, and no SKU has two different non-empty spec sets, `s06b_out.json`). Ivory: 2 SKUs have two different non-empty spec sets (4 listings). 1PC: `vendor_sku` 163190 (2 listings). The last line wins in each case; which row is right is unverified.

## False positives rejected

- "Mojibake" in 22 1PC titles and 21 product models: these are `×` (U+00D7) in `2×8GB`, not mojibake. Checked with `s05_out.json` examples.
- KSP snapshot 2026-11-07 (stale): accepted in the lane brief; not counted.
- 1PC `vendor_sku` changed on 2023 listings and Yahav on 1036: the detail `real_sku` replaces the numeric listing id by design (`normalize_and_match._merge_detail_specs`, lines 396–422).
- `image_url` changed on 2200 TMS, 1704 1PC, 624 Ivory listings: image competition by design (`_merge_detail_specs`, image index).
- Yahav builder rows with price 0: dropped by `_drop_included_builder_options` by design. None present in the newest raw file.
- TMS `scraped_at` differs from crawl B on 2130 listings: explained by F1, not a separate finding.
- Missing `promo` fields after dedupe: `promo_lost_on_kept_row` = 0 (`s02_out.json`).

## Out-of-lane sightings

- Image pick: 17 TMS detail rows whose only image candidate is the TMS logo (`logo-tms-256-soc.png`). The catalog keeps the listing thumbnail, so the logo does not reach the catalog. Image scoring is another lane's.
- Image pick: 142 1PC listings where the detail image differs from the catalog image. Same competition rule; not checked against the scorer.
- `decisions.md` line 7 (TMS 1 run/day) is broken by F1. Owner decision on the schedule.

## Not checked / questions

- Frontend rendering of the entities in F4 (did not check `site/` source or the rendered page).
- KSP rows dropped by scope or uin dedupe are not in the raw file, so their drops cannot be counted. `scripts/audit_ksp_tags.py` was not run.
- `data/review_queue.json` was checked only for product id text matches, not for its fuzzy-merge logic.
- The image pipeline was not checked beyond the sightings above.
- Owner question: should the TMS second crawl of 2026-11-09 be kept, dropped, or treated as the day's real crawl? The catalog currently uses both.
- `decisions.md` was not updated: this lane may write only to the two report files. The owner may want an entry for F1 and the schedule fix.
