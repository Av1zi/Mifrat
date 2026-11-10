# Lane 06: offers, prices, stock, freshness, links

**Git HEAD:** `1e353d17` (re-pinned from `1534928e` during the audit, see Method)
**Catalog `generated_at`:** `2026-11-09T22:13:04.288166+00:00`
**Scope:** 7095 listings, 4383 products, `skipped_vendors` empty.

Read-only audit. No file under `scraper/`, `nano/`, `site/` or `data/` was changed. Output is this report and its JSONL.

## 1. Summary

| id | finding | severity | count | silent / flagged | confidence |
|---|---|---|---|---|---|
| 06-F1 | Best offer is a `bundle_only` or `new_pc_deal` TMS/Yahav offer, shown on the site as a plain offer | S1 | 206 products (149 bundle_only, 57 new_pc_deal) | silent | medium |
| 06-F2 | TMS has two same-day crawls in one raw file; the catalog keeps the lowest price across both | S2 | 67 listings (25 show the superseded older price) | silent | high |
| 06-F3 | TMS history chart's last point disagrees with the offer price | S3 | 42 series | silent | high |
| 06-F4 | 1PC memory `1pc:206013` jumps 1151 → 5756 in one day | S3 | 1 | silent | low |
| 06-F5 | TMS listing URLs use `category?product_id=N` instead of a product page path | S3 | 40 listings | silent | low |

Clean checks (no finding): null prices reach no best offer or site min price; best_offer and site min_price/in_stock match the recomputed rules for all products; freshness flags are consistent; zero and tiny prices absent; rounding matches `normalize_price`; no history series for unknown products; no plonter or skipped-vendor offers; no URL on the wrong domain; no URL shared between products.

## 2. Method

- **Pin.** HEAD and `generated_at` were read at start (`1534928e`, `2026-11-09T22:13:04.288166+00:00`). A second agent then committed 51 files (`1e353d17`). Five of them are pipeline files (`nano/run_tms.sh`, `nano/run_ksp.sh`, `scraper/download_images.py`, `scraper/pcpartdb.py`, `scraper/qa_tool.py`). On your instruction I re-pinned to `1e353d17`. `generated_at` did not change, so the catalog and raw files scanned are the same. The one `run_tms.sh` change in the range edits only a warning message; the crawl and FEEDS line (`nano/run_tms.sh` L43) are unchanged.
- **Snapshot read.** `common.py` mirrors `normalize_and_match.find_latest_snapshot` (14-day stale-forward). Snapshots read: tms 2026-11-09, onepc 2026-11-09, ksp 2026-11-07, ivory 2026-11-09, yahav 2026-11-09.
- **Scans** (all in `tmp/data-audit/06-offers-prices/`, run as `python -X utf8 -P`):
  - `s01_null_prices.py`: null prices by vendor, and whether they reach best_offer or site min_price.
  - `s02_raw_dupes.py`, `s02b_tms_dupe_detail.py`, `s02c_tms_two_passes.py`: duplicate raw rows per listing_key, which row the catalog kept.
  - `s03_price_sanity.py`: zero/tiny prices, outliers, rounding vs `normalize_price`, shared-price groups.
  - `s04_history.py`: history series vs catalog and site files.
  - `s05_best_min_fresh.py`: recomputed best_offer (`choose_best_offer` rule), site min_price and in_stock (`_trim_offer` rule), freshness.
  - `s06_stock_bundle_urls.py`: no-priced products, stock by vendor, bundle flags, URL checks.
  - `s07_checks.py`, `s08_bundle_jump.py`, `s09_examples.py`: bundle semantics, non-product URLs, the 1PC jump, examples.
  - `build_jsonl.py`: writes the JSONL from the scan outputs.
- **Flags checked.** `data/site/qa.json` (kinds: variant_conflict, spec_conflict, identity_merge, duplicate_vendor, packaging_conflict, core_gap, split_candidate; none about price, stock, bundle, URL or history) and `data/review_queue.json` (no bundle or price entries). All findings below are silent.
- **Code read.** `scraper/matching.py` (`listing_key` ~L1256, `dedupe_enriched_listings` ~L1898, `offer_from_listing` ~L2236, `choose_best_offer` ~L4718, `normalize_price` ~L369), `scraper/site_data.py` (`_trim_offer`, `_trim_product`), `scraper/build_price_history.py`, `scraper/spiders/tms.py` L255–347, `nano/run_tms.sh`, `scraper/run_spider.py`.

## 3. Findings

### 06-F1 (S1): bundle or new-PC offer is the best offer and is shown as a plain price

- **Count:** 206 products. 149 have a `bundle_only` best offer, 57 a `new_pc_deal` one. 196 are TMS, 10 are Yahav.
- **Field:** `best_offer`, and the site's `min_price` and offer list.
- **Observed examples:**

| product_id | listing_key | vendor | price | flag | verbatim title_raw |
|---|---|---|---|---|---|
| `model:aio:545lc-cooling-cpu-water` | `tms:1009115` | tms | 70 | bundle_only (raw category `cpu cooler:bundle-only`) | Asetek Water Cooling CPU 545LC |
| `model:aio:3-loop-silent-360mm-black` | `tms:BW025` | tms | 661 | bundle_only | be quiet! Silent Loop 3 360mm |
| `model:aio:360-aio-icue-link-rx-titan-360mm-black` | `tms:CW-9061018-WW` | tms | 745 | bundle_only | Corsair iCUE LINK TITAN 360 RX RGB AIO Liquid CPU Cooler |
| `model:case:1-ft-performance-black` | `tms:PERFORMANCE1FTARGB` | tms | 550 | bundle_only | מארז מחשב Antec Performance 1 FT ARGB |
| `model:aio:k240-240mm` | `tms:K240RGB` | tms | 318 | new_pc_deal (`promo_text_raw` "הנחת New PC", `price_promo_ils` 142 in raw, not kept) | Antec K240 RGB קירור נוזלי למעבד |

- **Expected:** a price that depends on buying a whole PC should not win "best price" as a plain offer. Whether the TMS 545LC/BW025 numbers are conditional is **unverified** (offline, cannot open the tile). The code marks the tile, but the flag is dropped on the way to the site.
- **Cause (traced, one part unverified):** `scraper/spiders/tms.py` L300–321 sets `bundle_only` from the tile text and appends `:bundle-only` to `category_guess`. `choose_best_offer` (`matching.py` ~L4718) ignores the flag. `site_data._trim_offer` drops `bundle_only` and `new_pc_deal`, so the site shows a plain offer. `site/src/i18n.ts` L98 has a "Bundle only" label, but a grep finds no code that renders it. The conditional-price question is unverified.
- **Severity:** S1. The site's headline "lowest price" can be a price the user can only get as part of a PC.
- **Confidence:** medium (the mechanism is traced; whether the price is conditional is not).
- **Silent.** No QA case or review item.
- **Fix direction:** exclude bundle/new-PC offers from best_offer and min_price, or show them with their label on the site.
- Full list: `06-offers-prices.jsonl`, finding `06-F1`.

### 06-F2 (S2): TMS keeps two same-day crawls in one file, and the catalog takes the lower price across both

- **Count:** 2204 listing keys appear twice in `data/raw/2026-11-09/tms.jsonl` (4430 rows for 2216 keys). 67 pairs disagree on price, 5 on in_stock. In the 67 pairs the older pass is 03:33 UTC and the newer is 21:25 UTC. In 25 pairs the catalog shows the **older, cheaper** price, which is superseded. In 42 pairs the newer price is cheaper and the catalog shows it.
- **Field:** `price_ils` (and `in_stock`) on the TMS listing; that price feeds `best_offer` and `min_price`.
- **Observed examples:**

| product_id | listing_key | vendor | older pass (03:33) | newer pass (21:25) | catalog | verbatim title_raw |
|---|---|---|---|---|---|---|
| `model:gpu:9070-amd-pulse-radeon-rx-xt-16gb` | `tms:11348-03-20G` | tms | 3750 | 4573 | 3750 (superseded) | Sapphire PULSE RX 9070 XT GAMING 16GB |
| `model:memory:6000-beast-cl36-fury-16gb-x1-6000mhz-cl36-white` | `tms:KF560C36BWE2-16` | tms | 1304 | 1367 | 1304 (superseded) | Kingston DDR5 16GB 6000 CL36 FURY Beast |
| `model:memory:0-3-6000-beast-cl30-expo-fury-xmp-16gb-x1-6000mhz-cl30-black` | `tms:KF560C30BBE-16` | tms | 1409 | 1447 | 1409 (superseded) | Kingston FURY Beast DDR5 16GB 6000 CL30 |
| `model:memory:2x16gb-5600-amd-cl38-gemini-32gb-x2-5600mhz-cl38-rgb-grey` | `tms:GAMSG532GB5600C38ADC` | tms | 1958 | 2017 | 1958 (superseded) | GeIL DDR5 32GB (2x16GB) 5600 CL38 |

- **Expected:** one price per listing per day, from the latest pass. Which pass is authoritative is **unverified**; the newest pass is the most recent observation.
- **Cause (traced):** `nano/run_tms.sh` L43 runs `scrapy crawl tms -s FEEDS={...}` with no overwrite setting, so a second run on the same UTC day appends to `tms.jsonl`. `git log -- data/raw/2026-11-09/tms.jsonl` shows `28cfe190` (05:38 +0200, "2213 items") and `4440d3f5` (23:31 +0200, "4430 items"). The trigger of the second run is **unverified**. `dedupe_enriched_listings` (`matching.py` ~L1898) then keeps the lowest price, so cross-pass prices are mixed. Note that `run_spider.py` writes its own output via `.part` and replaces the file, so the append happens in the Nano script, not in `run_spider.py`.
- **Best-offer impact (checked):** 11 of the 25 superseded prices are the product's current `best_offer`, so the headline price on those products is the superseded one.
- **Severity:** S2. Up to 25 offers show a superseded price; 11 of them are headline best offers.
- **Confidence:** high (count and examples are from data; the cause is from the script and git log).
- **Silent.**
- **Fix direction:** make the TMS run overwrite the day file (or dedupe by pass time) and dedupe by latest scraped_at, not lowest price.
- Full list: finding `06-F2` (67 rows; `superseded_by_catalog: true` on the 25).

### 06-F3 (S3): history chart's last point disagrees with the offer price for 42 TMS series

- **Count:** 42 series, all TMS. Example: `model:case:3500x-r-rs-black`, `tms:CC-9011322-WW`, offer 432 vs history 513 on 2026-11-09 (`data/site/history/case.json`). Others: `model:case:360-bf-flow-black`, `tms:PGW-CH-HVN-013`, offer 756 vs history 889. The same pattern holds for `model:case:3500x-r-rs-white` (`tms:CC-9011323-WW`, 432 vs 513).
- **Expected:** history last point equals the offer price shown on the page.
- **Cause (traced):** `scraper/build_price_history.py` `_load_snapshot_prices` takes the first row per SKU in the file, i.e. the 03:33 pass (F2). So the chart shows the older pass while the offer shows the lower current price. For these 42, the offer is the lower price in the 21:25 pass.
- **Severity:** S3 (chart and offer disagree; no price is invented).
- **Confidence:** high.
- **Silent.**
- **Fix direction:** fixing F2 fixes this; history should use the same pass as the offer.
- Full list: finding `06-F3`.

### 06-F4 (S3): one 1PC memory price jumps 5x in one day

- **Count:** 1 (the only memory row out of 248 that moved >3x or <1/3 between 2026-11-03 and 2026-11-04).
- **Product / listing:** `model:memory:32gb-4800mhz-4x77a77030-rdimm-thinksystem-truddr5-32gb-4800mhz-black-dimm`, `1pc:206013`, the only offer of the product.
- **Observed:** raw `onepc.jsonl` 2026-11-02 1143, 2026-11-03 1151, 2026-11-04 5756; catalog now 5822. Title: "זיכרון Lenovo ThinkSystem RDIMM 32GB TruDDR5 4800MHz 4X77A77030 בצבע שחור".
- **Expected:** unverified. Either a real vendor price change or a parse error. I cannot open the vendor page offline.
- **Cause:** unverified. The pipeline has no jump guard, so the value is passed through to the history and the offer.
- **Severity:** S3. **Confidence:** low.
- **Silent.**
- **Fix direction:** check the 1PC page for 206013 on the Nano; if it is a parse error, fix the 1PC parser.

### 06-F5 (S3): 40 TMS listing URLs point at a category path with `?product_id=`

- **Count:** 40 TMS listings in `data/catalog.json`. Examples:
  - `tms:12SLLCD1W3B`, `https://tms.co.il/case-fans?product_id=111401`, "Lian-Li UNI SL Wireless LCD 120mm Black 3xFans"
  - `tms:90MB14Z0-M0EAY0`, `https://tms.co.il/computer-hardware-components/motherboards?product_id=103905`, "Asus PRIME A520M-A"
  - `tms:90MB1500-M0EAY0`, `https://tms.co.il/computer-hardware-components/motherboards?product_id=103907`, "Asus PRIME A520M-K"
  - `tms:90MB1ER0-M1EAY0`, `https://tms.co.il/computer-hardware-components/motherboards?product_id=108849`, "Asus TUF GAMING B760-PLUS WIFI"
- **Expected:** a product page URL, `/<category>/<slug>`. Whether the `?product_id=` form resolves to the right product is **unverified** offline.
- **Cause:** unverified. The URL is taken from the tile link as-is (`tms.py` L255, L327).
- **Severity:** S3. **Confidence:** low. Note: an earlier regex gave 27; this count (40) includes every URL with a query string.
- **Silent.**
- **Fix direction:** on the Nano, open one of these URLs and confirm it resolves to the product; if not, use the product slug.

## 4. Suspicions (not confirmed)

- **Bundle prices and "conditional" semantics (F1).** `tms.py` L266–298 treats the second ₪ amount as a conditional deal price and keeps the first as the display price. For `bundle_only` tiles there is only one amount (raw: 300 bundle rows with a price, 142 with none). Whether the single amount is a whole-PC price is unverified.
- **The 21:25 TMS run trigger (F2).** Nothing in the repo shows what started the second same-day run. Could be a manual dispatch retry or a Nano catch-up. Not checked.
- **Passive SSD coolers and a bracket filed as `storage` (out of lane, see §7).** Not a price issue in itself, but their prices feed the storage outliers (9 found in `s03`).

## 5. False positives rejected

- **2255 `vendor_not_in_offers` in `s04`.** My script compared `1pc` with `onepc`. Fixed in the script; 0 real cases.
- **923 KSP URLs "not item".** My regex was `/shop/items/`. The real shape is `https://ksp.co.il/web/item/N`. 0 real cases.
- **878 null last history points for KSP.** KSP's newest snapshot is 2026-11-07, so 11-08 and 11-09 are correctly null. `stale` is true on all 923 KSP listings. Expected under the 14-day rule.
- **Outliers in cpu, gpu, memory, storage (`s03b`).** Checked: used Pentium/Celeron trays, Threadripper and Xeon workstation parts, workstation GPUs. Real prices.
- **Shared prices across products (`s03d`).** Coincidental (e.g. 150 NIS on 11 fans). Not placeholders.
- **Zero or tiny prices, and Yahav "included in" zero prices.** None present; the `_drop_included_builder_options` filter is working.
- **Rounding mismatch.** None: `price_ils` equals `normalize_price(price_ils_raw)` for every listing with a raw price.
- **New-PC deal promo (e.g. K240RGB 318 vs promo 142).** By design: `tms.py` keeps the regular tile price as the display price. The problem is F1, not this.
- **KSP and Yahav `in_stock` always True.** KSP 923/923 True; Yahav `yahav.py` ~L75 keeps True by design. Not a finding.

## 6. Known and accepted items (count unchanged, not reported)

- **TMS "price on request" (null price).** 82 listings across 81 products, with no priced offer (all TMS). Count matches the lead. Their detail rows (158 of 164 raw null rows) contain no price text. The 2 products with two null offers account for the 82 listings. Not a finding.
- **KSP stale within 14 days.** 923 listings, snapshot 2026-11-07. Not a finding.

## 7. Out-of-lane sightings

- **Misfiled as `storage` (likely accessories):** `1pc:171797`, `1pc:171798`, `1pc:139894`, `1pc:109256`. These are passive SSD coolers and a bracket. Owner: categorisation lane.
- **Possible misfile as `aio`:** `model:aio:545lc-cooling-cpu-water` (`tms:1009115`, 70 NIS, bundle_only). Its raw category is `cpu cooler:bundle-only`. The product is a CPU water cooler, so its "aio" category may be wrong too. Owner: categorisation lane, and F1.

## 8. Not checked / questions for the owner

1. **Re-pin.** The audit now runs against `1e353d17`. Do you want a fresh run once the other agent's work settles, or is this report enough?
2. **F1 conditional prices.** Can someone open one TMS bundle tile (e.g. `tms:1009115`) and say whether 70 NIS is the whole price or a whole-PC price? This decides whether F1 is S1 or S2.
3. **F2 trigger.** What started the 21:25 UTC TMS run on 2026-11-09?
4. **F4.** Is 1PC `206013` really 5756? Needs a live check on the Nano.
5. **F5.** Do the 40 `?product_id=` URLs resolve to the right products?
6. **Not checked:** whether `site/src` renders `bundle_only` anywhere beyond the i18n label (grep found none); the live vendor sites (offline audit).

## 9. Outputs

- `docs/audits/2026-11-10/06-offers-prices.md` (this file)
- `docs/audits/2026-11-10/06-offers-prices.jsonl` (356 instances: F1 206, F2 67, F3 42, F5 40, F4 1)
- Scratch and scans: `tmp/data-audit/06-offers-prices/`
