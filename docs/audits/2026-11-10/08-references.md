# Lane 08: references (pointers, published files, ledgers, enrichment, images)

- Lane: 08-references
- HEAD: `1e353d17` (re-pinned from `1534928e`; `git diff --stat 1534928e 1e353d17 -- data` is empty, so the catalog and every data file are identical across the range. Changes are under `site/`, `scraper/download_images.py`, `scraper/qa_tool.py`, `scripts/` and CI.)
- catalog `generated_at`: `2026-11-09T22:13:04.288166+00:00` (unchanged)
- generated_at (this report): 2026-11-10

## Summary

No S1 confirmed. The published files, aliases, QA references, curated ledgers and cover images all agree with the catalog. The one real routing gap is in extract facts keyed to retired product ids (F1, F2).

| id | finding | severity | count | silent/flagged | confidence |
|----|---------|----------|-------|----------------|------------|
| F1 | Trusted extract facts keyed to retired pids never reach the product (alias not consulted by `_candidate_ids`) | S2 | 28 | silent | high (traced) |
| F2 | Trusted alias-keyed extract facts that the current code would apply, but the published product value is null | S2 | 21 | silent | low (unverified: likely stale build) |
| F3 | Extract facts whose quote fails the pipeline's own verbatim check (includes PSU colour Black vs White) | S2 | 16 | silent (not published) | high |
| F4 | Extract entries whose pid is gone with no alias | S2 | 277 entries | silent | high |
| F5 | Extract facts held but untrusted (trust allowlist has 54 intern-latest tuples) | S3 | 1,127 facts (1,122 alias-keyed + 5 live) | silent | high |
| F6 | Curated manual products whose pid is gone and whose listings were last seen Sep-Oct | S3 | 4 pids, 7 keys outside 14-day window | silent | high |
| F7 | Blocked pair with a listing key no longer in any snapshot | S3 | 1 | silent | high |
| F8 | `qa_dismissed` keys for cases that no longer exist | S3 | 2 | silent | high |
| F9 | Spec overrides keyed to aliased (retired) pids | S3 | 3 | silent | high (verified applied via mpn fallback) |
| F10 | Enrichment entries with no product using their part numbers | S3 | about 1,500 across mfr and icecat files (see body) | silent | medium |
| F11 | Images with no listing behind them; blocklist entry matching nothing | S3 | 565 files; 1 entry | silent | high |
| F12 | Detail ledgers out of step with raw detail | S3 | 159 / 51 / 8 / 1,232 | silent | high |

## Method

Scripts are in `tmp/data-audit/08-references/` (run as `python -X utf8 -P`); outputs are in `out/`. All checks are read-only; no normalize, spider, download, QA, promote or npm commands were run.

1. `scripts/check_publish_set.py`: pass, 4,383 products across catalog, 11 category files, index, meta and spec_report.
2. `scan_a.py`: site rows vs catalog (each product in one file; `cooler_air` and `aio` in `cpu_cooler`); index and meta recount; alias graph (loops, chains, dangling, live-name collisions, cross-category); `identity_cases` and `qa.json` pointers; `qa_dismissed`.
3. `scan_b.py` and `raw_keys.py` (uses the real `scraper.matching.listing_key`): manual products, blocked pairs, review decisions, overrides, listing-to-offer ownership.
4. `scan_hist.py`: price-history ids and HEAD~1/3/10 catalog products vs live ids and aliases.
5. `scan_c*.py`: enrichment (`data/mfr`, `icecat`, `xref`, `extract`); orphan counts; extract classification.
6. `runtime_findings.py`, `runtime_quote_check.py`, `runtime_gate_check*.py`, `runtime_alias_null.py`: re-run the extract quote check with the pipeline's own `scraper.extract.verify.normalize` and `product_text`, and trace `scraper.extract.store.facts_for` and `scraper.extract.runner.trusted_fields`. Outputs: `out/runtime_findings.json`.
7. `scan_d.py`, `cover_sheet.py`: image paths, covers vs offers, shared covers, blocklist, dark_ok, category covers, detail pending vs scraped, review queue pointers. A 40-cover contact sheet was checked by eye (`out/cover_sheet.png`).

Tracing: `scraper/specs/build.py` (line 244-248) calls `extract_store.facts_for(product_id, category, offers)`. `scraper/extract/store.py` `_candidate_ids` tries the exact product id, then `mpn:<cat>:<key>` and `sku:<cat>:<key>` from the product's own part numbers. The alias map is not consulted. `facts_for` also requires `(model, category, field)` to be in `trusted_fields()`, and the quote to be in `product_text(offers)`.

## Findings

### F1 (S2): trusted extract facts keyed to retired pids never reach the product

- Count: 28 (`out/runtime_findings.json`, `alias_null` `('alias','trusted','not_applied')`).
- Silent: the product field is null and nothing flags it.
- Examples:
  - product `model:case:cg-e3-talos`, extract key `case:1pc:1pc-222500`, field `drive_bays_35`, observed null, value 2, quote `"2.5/3.5": 2x2.5"/2x3.5"`
  - product `model:case:110r-mag-pano-pz-white`, extract key `case:1pc:1pc-222501`, field `drive_bays_35`, observed null, value 2, quote `2 x 3.5“`
  - product `model:case:aura-elite-gc9m`, extract key `case:1pc:1pc-222502`, field `drive_bays_35`, observed null, value 1, quote `1 * 3.5" or 1 * 2.5"(HDD Cage)`
- Expected: value 2 (or 1) on the product, source `extracted`, since the quote is verbatim in the product's own text and the trust tuple is listed.
- Source: `data/extract/products.json`, `data/extract/trust.json`, `data/catalog.json` `pid_aliases`.
- Cause: traced. `_candidate_ids` in `scraper/extract/store.py` does not resolve `pid_aliases`. The entry is keyed by the retired id, and the product's current id is not `mpn:`/`sku:`-keyed to that entry.
- Fix direction: resolve `pid_aliases` in `_candidate_ids` (or rekey the extract file to current ids), then rebuild.
- Confidence: high on the routing, since the code path is traced and the counts are reproduced.

### F2 (S2, unverified): trusted alias-keyed facts that current code would apply, but the published value is null

- Count: 21 (`alias_null` `('alias','trusted','applies_now')`).
- Silent.
- Examples:
  - product `model:cooler_air:22fp-blizzard-r1-rr-t2-t2-140mm-92mm`, extract key `mpn:cooler_air:rrt222fpr1`, field `color`, observed null, value `כסף`, quote `בצבע כסף`
  - product `model:gpu:3x-5060-8g-oc-rtx-ti-ventus-8gb`, extract key `mpn:gpu:4711377337649`, field `interface`, observed null, value `PCI Express® Gen 5 x16 (משתמש ב-x8)`, quote `ממשק: PCI Express® Gen 5 x16 (משתמש ב-x8)`
  - product `model:motherboard:b-b650m-pro-microatx`, extract key `mpn:motherboard:4711377144797`, field `usb_ports`, observed null, value `2×USB 2.0…`
- Expected: the value is applied, because `facts_for` on the current listings returns it.
- Source: `scraper/extract/store.py` `facts_for` run on current `catalog.json` offers.
- Cause: unverified. Most likely the published build predates the extract file or saw different offers. I did not rebuild (not allowed), so I cannot separate the two.
- Fix direction: re-run the build in the agreed path and confirm these 21 land; if they do, the cause is staleness, not code.
- Confidence: low until a build is compared.

### F3 (S2): extract facts that fail the pipeline's own quote check

- Count: 16 (`runtime_quote_fail`). Earlier scan figure of 230 was a corpus artifact; 214 of those pass the pipeline's normalizer.
- Silent: none of the 16 is applied to a published product value, except where a vendor value already agrees.
- Examples:
  - product `model:aio:6cfm-73-aura-gl360-v2-360mm-black`, extract key `mpn:aio:4712960139343`, field `radiator_length_mm`, observed null, value 360, quote `גודל רדיאטור: 360mm`
  - product `model:aio:360-lc-lcd-rog-strix-360mm-white`, extract key `mpn:aio:rogstrixlciii360argblcd`, field `fan_rpm_min`, observed null, value 2800, quote `2800RPM`
  - product `model:psu:750-csk-dc-750w-white`, extract key `mpn:psu:csk750dc`, field `color`, observed `White` (vendor), extract value `Black`, quote `בצבע שחור`. Both listings say `לבן` (white).
- Expected: quotes present verbatim, or the value removed from the extract file. The PSU colour is wrong in the extract file and is hidden only because the vendor tier wins.
- Source: `data/extract/products.json`; both listings in `data/catalog.json`.
- Cause: traced for the check (`scraper/extract/store.py` quote test); the extraction-side cause (value/quote mismatch) is unverified.
- Fix direction: drop or re-extract these 16 facts; the PSU entry needs a re-check of colour.
- Confidence: high on the 16; medium on the PSU cause.

### F4 (S2): extract entries whose pid is gone with no alias

- Count: 277 entries (`target_gone`).
- Silent. Examples: `case:tms:tms-a3w` (`max_gpu_length_mm`), `gpu:1pc:1pc-221469` (`boost_clock_mhz`), `motherboard:1pc:1pc-203138` (`memory_slots`, `pcie_x16_slots`, …).
- Expected: either an alias to the current product or removal.
- Source: `data/extract/products.json`, `data/catalog.json` `pid_aliases`.
- Cause: traced (no alias path). Fix direction: decide per entry whether it maps to a live product (human call; do not prune without approval).
- Confidence: high.

### F5 (S3): untrusted extract facts held in the file

- Count: 1,127 facts (1,122 alias-keyed, 5 live) with a verified quote but no trust tuple. `trusted_fields()` lists 54 `intern-latest` tuples.
- Silent. These are inert in the product but still ship in the extract file.
- Examples: `aio:1pc:1pc-222207` → `model:aio:ultra360-360mm-black`, `radiator_length_mm`, value 360, quote `גודל רדיאטור: 360 מ״מ`; `motherboard:asus:b860m-max-gaming-ax` (live), `storage_interface`.
- Fix direction: decide whether to extend the trust list or prune the file; not a bug on its own.
- Confidence: high.

### F6 (S3): curated ghost products

- Count: 4 pids missing from catalog and aliases; 7 listing keys outside the 14-day window.
- Silent. Examples: `case:antec:flux` (`1pc:171578`, last seen 2026-10-05), `cpu:amd:ryzen-9-9950x3d` (`ivory:128577`, last seen 2026-09-14), `model:cpu:ryzen57500x3d-tray`, `model:cpu:ryzen99900x3d`.
- Expected: curated entries either re-attached to live products or removed.
- Source: `data/matching/manual_products.json`; raw snapshots.
- Cause: traced (pids not in catalog, not aliased).
- Fix direction: human review of the curated list.
- Confidence: high.

### F7 (S3): blocked pair with a gone key

- Count: 1. `tms:SRP-CGX851-A5A32SFW` last in raw 2026-11-02; the other key `tms:SRP-CGX851-A5A32SF-W` is live.
- Silent. Fix direction: remove or update the blocked pair.
- Confidence: high.

### F8 (S3): stale `qa_dismissed` keys

- Count: 2. `spec_conflict|aio:tms:tms-1009115|model` (pid gone, no alias); `spec_conflict|aio:1pc:1pc-222392|model` (aliased to `model:aio:360-nautilus-rs-360mm-black-rgb`, which has no spec_conflict case).
- Silent. Fix direction: drop the two keys.
- Confidence: high.

### F9 (S3): overrides keyed to retired pids

- Count: 3 entries (`mpn`/`alias` ids). Field `socket` = LGA4710 on `model:cpu:674x` is applied via the mpn fallback, so no visible error.
- Silent. Fix direction: rekey to current ids.
- Confidence: high.

### F10 (S3): enrichment entries with no product

- Counts (orphan / entries): `mfr/silverstone` 993/1,050; `mfr/antec` 272/419; `mfr/bequiet` 68/151; `mfr/coolermaster` 63/91; `mfr/nzxt` 48/62; `mfr/lianli` 31/59; `mfr/corsair` 8/236; `mfr/asus` 2/87; `mfr/amd` 2/47; `mfr/fractal` 2/40; `mfr/thermalright` 1/11; icecat files 0-8 each; xref small.
- Silent. All files are schema_version 3.
- Example: `https://www.antec.com/product/case/df700-flux-white.php` (part `0761345800747`) has no listing from any vendor, so it is correctly an orphan.
- Cause: unverified in general (most look like manufacturer pages for products we never listed); the Antec and SilverStone model-token hits were checked and rejected.
- Fix direction: decide whether to prune; not a visible error.
- Confidence: medium.

### F11 (S3): images

- Count: 565 webp files with no catalog listing behind them; 2,282 webp not a current cover (1,595 onepc, 275 ivory, 185 yahav, 155 ksp, 72 tms); `image_blocklist` entry `onepc/0333830` matches no listing.
- Silent. No cover file is missing; no shared covers; all 35 `image_dark_ok` files exist.
- Fix direction: prune the orphan images and the dead blocklist entry.
- Confidence: high on counts; medium on "no listing" meaning unused.

### F12 (S3): detail ledgers out of step

- 1PC: 159 `detail_pending` SKUs are already in `detail_scraped` (19 are live listings).
- Ivory: 51 `detail_scraped` entries not in raw detail; 3 raw detail rows not in scraped ledger; 5 pending.
- TMS: 8 raw detail rows not in scraped ledger.
- Plonter: 1,232 raw detail rows not in scraped ledger; the catalog has 0 plonter listings and 0 offers, so this is inert.
- Yahav: detail is keyed by URL id; all 1,044 live listing keys are `yahav:<url id>` with detail rows (no loss).
- Silent. Fix direction: reconcile the ledgers.
- Confidence: high on counts.

## Suspicions

- F2 may be a stale build. Confirm by comparing the extract file's mtime with the catalog's `generated_at` and rebuilding in the normal path.
- Whether all `other` and `accessories` covers were reviewed: only the 40-cover sample was checked.

## Rejected false positives

- Image path "drift" 4,380: the catalog stores remote URLs and the site stores local paths. Not a mismatch.
- Cross-category aliases 2,723: parser bug in my first scan. Fixed; 0 real cross-category aliases.
- Thumbs "missing" 4,366: thumbs are derived and never committed.
- 17 covers "SKU not in offers": filenames replace spaces and `#` with `_`; the files exist.
- Extract quote misses 230: corpus artifact (my own normalizer). The pipeline check gives 16 (F3).
- 58 "live extracted facts with unverifiable quote" (earlier S1): these pass the pipeline check. Rejected.
- `review_queue.json` listing-key misses (1,314): the 657 QA-style rows have no `listing_a`/`listing_b`; all 529 pair rows resolve.
- Antec DF700 Flux White orphan: correctly orphaned (no listing).
- Yahav detail "gap": join error (URL id vs SKU).
- TMS `100-000001904` missing from catalog: appears in 11-07/11-08 raw but not the newest snapshot. Normal vendor churn; all newest-snapshot listings are in the catalog.

## Out-of-lane sightings

- `docs/audits/` was untracked while this lane ran (this lane's output); committed afterwards (2026-11-10).
- Commits `9801f010` through `1e353d17` change CI, worker and site code, including removal of root `wrangler.jsonc`. Not reviewed in this lane.

## Not checked / questions

- Re-running the full build to test F2 (not permitted in this lane).
- Whether the PSU colour contradiction (F3) should be re-extracted or removed: human decision.
- Whether `bk004` → `Shadow Rock 3 White` (part key `bk005` on the product) is the right link; it is an untrusted fact, so it has no visible effect.

## Closed in this pass

- The 888 mpn-keyed alias facts: 1,008 of the mpn-keyed null facts have their part number among the product's part numbers, so the fallback reaches them; they are null because the trust gate rejects them (F5). The other 14 differ only by a `-tray` suffix, except `bk004`/`bk005` above; all 14 are untrusted, so none is visible.
- `spec_report.json`: covered by the `check_publish_set.py` pass, which checks that it describes the same 4,383 products as the catalog.
