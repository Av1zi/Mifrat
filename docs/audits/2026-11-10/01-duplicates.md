# Lane 01-duplicates: one part split across products, or listed twice by one vendor

- **Lane:** 01-duplicates
- **HEAD:** pinned at `1534928e`; re-checked before writing and found `1e353d17` (five later commits, `b6f4c157` to `1e353d17`). `git diff --stat 1534928e HEAD -- data scraper/identity.py scraper/matching.py` is empty, so the findings apply to both. The working tree has uncommitted edits from other work; not used here.
- **generated_at (`data/catalog.json`):** `2026-11-09T22:13:04.288166+00:00` (7095 listings, 4383 products)
- **Machine output:** `docs/audits/2026-11-10/01-duplicates.jsonl` (231 rows, one per instance)
- **Scripts (scratch):** `tmp/data-audit/01-duplicates/` — `scan1_identifiers.py`, `scan2_multi_pn.py`, `scan4_same_vendor.py`, `scan356.py` (scans 3, 5, 6), `scan3b.py`, `ean_source.py`, `dump_products.py`, `titles_for_distinct.py`, `finalize.py` (verdicts, counts, JSONL), shared loader `base.py`

## Summary

The main problem is **distinct parts merged into one product**, not one part split across products. The identity tier's part-number split is switched off for most vendors (Yahav, 1PC, TMS, Ivory print the maker part number as their own SKU), so colour and lighting variants of one model sit under one page.

| ID | Sev | Finding | Instances | Silent / flagged | Confidence |
|----|-----|---------|-----------|------------------|------------|
| S1-1 | S1 | True variants merged: colour, lighting, side panel, fan blade direction, or model (LBC vs HBC) | 22 products | 1 / 21 | high |
| S1-2 | S1 | Tray and Box merged into one product | 2 products | flagged | high |
| S1-3 | S1 | Two different barcodes inside one product | 4 products (3 also in S1-1) | flagged | high (observed), cause unverified |
| S1-4 | S1 | Accessory merged into a product (glass side panel; side-panel-only product) | 2 products | flagged | high |
| S2-4 | S2 | Same vendor, same SKU or MPN under two listing keys | 18 pairs | 1 silent / 17 flagged | high |
| S2-5 | S2 | Same vendor, two maker part numbers (35), one axis conflict (1), barcode plus two MPNs (1) | 37 pairs | flagged | high |
| S3-6 | S3 | Same vendor pair with no shared identifier: 6 safe merge, 28 true variant, 29 ambiguous | 63 pairs | flagged | medium |
| S3-7 | S3 | Distinct-unsplit product that titles do not settle | 6 products | 1 / 5 | medium |

Correctly merged (rejected): 58 distinct-unsplit products whose titles agree on one part. Alias twins (R-2) and scan 3 candidates (R-3) are rejected as false positives.

Leads: 112 products have one vendor twice in their offers (confirmed). `data/site/qa.json` has 115 `duplicate_vendor` cases over 111 unique products; one of the 112 is not flagged.

## Method

1. **Scan 1 (identifiers).** Used `identity.part_number_class`, `identity.shared_part_numbers`, and the strict EAN rule from `scraper/matching.py::_ean_shape` (digits only; no letter, dash or underscore; 8 or 12–14 digits).
   - Manufacturer PN on more than one product in one category: **0**.
   - Barcode on more than one product in one category: **0**. A lenient first pass gave 39; it was wrong, because letters and dashes were stripped (`5600J3636C16GX2-RS5K` became a fake barcode).
   - Product holding two different barcodes: **4**.
   - Product holding two or more printed PNs: **147**; 141 are unsplit by `identity.part_number_subgroups`.
2. **Scan 2 (multi-PN).** Each of the 147 classed `same_part` (spelling of one part: `-PC` tail, `GB`/`B` prefix, `TRAY`/`BOX`) or `distinct`. Result: **54 same_part, 93 distinct**. Of the 93 distinct, **90 are unsplit** by the splitter; 21 of those 90 are silent.
3. **Scan 4 (same vendor twice).** Every same-vendor pair classed by shared URL (`rekey`), shared SKU/MPN/barcode (`same_part`), axis conflict or two MPNs (`conflict`), or none (`unknown`). Result: **112 products, 118 pairs**: conflict 37, same_part 18, unknown 63. No `rekey` pairs. 117 of 118 flagged; 1 silent.
4. **Trace.** `identity._part_number_shape_class` returns `vendor` when the mpn equals the vendor's own SKU, which disables the split for most listings. Also, all-digit AMD OPNs (e.g. `100000000593`) hit the `isdigit()` vendor check before the `_MFR_PREFIXES` check.
5. **Title review (hand verdicts).** Every title of the 90 distinct-unsplit products and of the 63 unknown pairs was read from `titles_for_distinct.py` and `scan4_pairs.jsonl`. Verdicts are recorded in `finalize.py` and are hand readings, not a rule.
6. **Scan 3 (token-set).** Brand, generic and axis words dropped; products in one category with identical leftover tokens. Result: 583 buckets, 1899 products; narrowed to 3052 pairs with different model codes and no known axis conflict. A random sample of 12 was all different parts, so the token rule is too loose to find duplicates. Rejected as a detector (R-3).
7. **Scan 5 (cross-category).** One manufacturer PN or one model-code slug in two categories: **0 and 0**.
8. **Scan 6 (alias twins).** `pid_aliases` has 7085 entries, none dangling. 18 alias pairs have a live same-code twin; all 18 differ only in the Tray flag (packaging), so they are true variants (R-2).

## Findings

### S1-1: true variants merged into one product (22 products)

- **Expected:** each colour, lighting, side, blade direction or model is its own part. Source: the maker part numbers (each product page prints its own).
- **Examples** (product_id | listing_key | vendor | field | observed | verbatim title):
  1. `model:aio:17-2dba-85-85cfm-le520-240mm-white` | `yahav:9343` | yahav | mpn | `R-LE520-BKAMMN-G-1` | "קירור נוזלי למעבד חברת DeepCool דגם LE520 240MM"; `yahav:9466` mpn `R-LE520-WHAMMN-G-1` | "…LE520 White 240MM… צבע לבן". QA: `duplicate_vendor`, `spec_conflict`.
  2. `model:aio:1cfm-63-aio-h150i-icue-lcd-link-360mm-white` | `yahav:9877` | yahav | mpn | `CW-9061010-WW` | "Corsair iCUE Link LCD White RGB AIO H150i 360mm"; `yahav:9499` mpn `CW-9061008-WW` | "…iCUE Link LCD RGB AIO H150i 360mm".
  3. `model:aio:240-omni-240mm-white` | `tms:OMNI240ARGB` | tms | mpn | `OMNI240ARGB` | "קירור נוזלי Antec Omni 240 ARGB"; `tms:OMNI240ARGB-W` | "…Omni 240 ARGB לבן".
  4. `model:aio:360mm-io-lcd-light-loop-360mm-white` | `1pc:218659` | 1pc | mpn | `BW032` | "be quiet! LIGHT LOOP IO LCD 360mm"; `1pc:218657` mpn `BW033`.
  5. `model:case:c5-curve-white` | `1pc:207639` | 1pc | mpn | `0-761345-10225-4` | "מארז מחשב Antec C5 CURVE ARGB בצבע שחור"; `1pc:207641` | "…ARGB לבן" (white).
- **Others in this set:** DeepCool LS520 SE black/white; Thermalright/Antec ULTRA360 ARGB/ARGB-W; Antec C120 reverse 3PK black/white; Lian Li UNI SL reverse vs standard blade; Noctua NH-D15 G2 HBC vs LBC (`cooler_air`); Antec P20C vs P20C ARGB; G.Skill Trident Z5 Neo vs Neo RGB memory; Seasonic Vertex GX-1200 black/white and Antec GSK 850 V2 black/white PSUs; Asus ROG STRIX LC III 360 ARGB vs White Edition; Antec Performance 1 M Black vs Aventurine.
- **Suspected cause:** `identity._part_number_shape_class` returns `vendor` for an mpn equal to the vendor SKU, so `part_number_subgroups` never splits. **Traced** (133 of 141 unsplit multi-PN products are own-SKU, 8 digits-only).
- **Severity:** S1. **Confidence:** high. **Silent / flagged:** 1 silent / 21 flagged.
- **Fix direction:** let `part_number_class` treat a vendor-printed code as a manufacturer PN when another vendor prints the same code, or when the code matches the maker's shape; re-run the splitter.

### S1-2: Tray and Box merged (2 products)

- `model:cpu:14600k` — `1pc:152181` title "Intel Core i5 14600K / 1700 **Tray**", axis `packaging: box`; the other listings are Box (`ksp:280943`, `yahav:8754` BX8071514600K). QA flags `variant_conflict`, yet the merge stands.
- `model:cpu:245kf-tray` — `ksp:340400` title "Intel Core Ultra 5 245KF 24MB Cache LGA1851 - **Box**" inside a Tray product (other listings are Tray).
- **Suspected cause:** `packaging` axis derivation. **Unverified** (axis set, derivation not traced).
- **Fix direction:** trace `variant_values` for `packaging` on those listings; a title "Tray" or "Box" should win over the default.

### S1-3: two different barcodes inside one product (4 products)

- `model:aio:360-a13-coreliquid-mag-360mm-white` — `1pc:192580` `4711377273770` ("…ARGB") vs `1pc:192581` `4711377276689` ("…בצבע לבן").
- `model:aio:coreliquid-e360-mag-360mm-white` — `1pc:151938` `4711377115735` vs `1pc:163231` / `yahav:9643` `4711377124157` ("…White").
- `model:case:100r-mag-pano-pz-white` — `1pc:179941` `4711377231565` vs `1pc:179942` `4711377231572` ("…WHITE").
- `model:psu:a750bn-mag-pcie5-750w` — `1pc:214404` `4711377364317` ("…בצבע שחור") vs `1pc:161258` `4711377126595` ("750W 80+ Bronze"); ambiguous.
- **Suspected cause:** the EAN tier does not split on a barcode conflict. **Unverified.**
- **Fix direction:** two distinct strict-EAN values on the same product count as a split condition, as the PN tier already does.

### S1-4: accessory merged into a product (2 products)

- `model:case:1-ft-performance-black-midtower` — the product holds only the left and right glass side panels (`yahav:9358`, `yahav:9361`, "פאנל זכוכית צד … פאנל בלבד"), which are accessories, not cases.
- `model:case:nx410-black` — `yahav:7999` is "זכוכית למארז … Tempered Glass Only", a glass panel, merged with the NX410 case.
- **Fix direction:** accessories with "panel only" or "tempered glass only" in the title should not join a case product.

### S2-4: same vendor, same SKU or MPN under two listing keys (18 pairs)

- `aio model:aio:360-a-freezer-iii-liquid-pro-rgb-360mm-white` — `yahav:11462` SKU `ACFRE00188A-PC` vs `yahav:11461` SKU `ACFRE00188A` (same MPN; prices 590 / 620).
- `cooler_air …pure-rock-3-pro-black-lx…` — `yahav:11438` `BK043-PC` vs `yahav:10760` `BK043`.
- `cpu model:cpu:9850x3d-tray` — `yahav:11464` `100-000001973-PC` vs `yahav:11292` `100-000001973`.
- `memory KF560C30BBEA-32X2` — `yahav:10617` vs `yahav:11789`, same SKU and EAN. **Silent** (no QA flag): the only silent S2-4 pair.
- **Bundle status:** `bundle_only` is true on 13 of the 36 listings in these pairs; the `-PC` copies are not all bundles.
- **Suspected cause:** Yahav lists the same MPN under a `-PC` SKU and a plain SKU. **Traced** (same MPN on both).
- **Fix direction:** dedupe same-vendor offers on the normalised SKU (strip `-PC`); keep the lower price; log the other.

### S2-5: same vendor, two maker part numbers or one axis conflict (37 pairs)

- Reasons: `two_mpns` 35, `axis_conflict` 1, `same_ean`+`two_mpns` 1.
- Each pair's titles were read by hand (`s25_titles.txt`, verdicts in `finalize.py`):
  - **23 true variants** (colour, lighting, model): DeepCool LE520 and LS520 SE, Corsair H150i LCD, Antec Omni 240 / Ultra 360 / C5 Curve / P20C / C120 reverse / F600 / F620, MSI A13 and E360 and PANO 100R, be quiet! LIGHT LOOP, Asus ROG STRIX LC III, Thermalright, Lian Li UNI SL reverse, G.Skill Trident Z5 Neo vs Neo RGB, Seasonic Vertex GX-1200 and Antec GSK 850 V2 white, Antec Performance 1 M black vs aventurine, iStarUSA D-200L vs P-200L (titles identical; SKUs differ in model letter).
  - **1 separate accessories** (VX): `case:1-ft-performance-black-midtower`, left and right glass side panels, one product.
  - **1 Tray vs Box** (VP): `cpu:245kf-tray`, `ksp:340400` is Box.
  - **8 same part** (S, merge correct): Intel OPN vs retailer code for one CPU (245K, 245KF, 265K, 265KF, 285K) and Corsair RM1000x / RM850x SHIFT / RM1000e, where one listing is the EAN and the other the CP-code.
  - **4 ambiguous** (A): Thermalright TL-M10 VISION FAN4-C vs FAN4-M, XPG Gammix D35 SBKD35P vs SBKD35 (titles truncated or no colour in them), MSI A750BN (also S1-3).
- Script count: 23 VC, 1 VX, 1 VP, 4 A, 8 S. 22 of the 23 VC pairs are the vendor side of S1-1 products; the 23rd (D-200L vs P-200L) is in an S1-1-free product.
- **Fix direction:** the S1-1 fix covers the colour and lighting pairs; the Tray vs Box pair is S1-2. The 8 same-part pairs are a spelling problem: a retailer code (`C245KT`, `CP-9020300-EU`) and a maker OPN or EAN for one part. Cause unverified.

### S3-6: same-vendor pairs with no shared identifier (63 pairs)

| Verdict | Count | Meaning |
|---------|-------|---------|
| M safe merge | 6 | same vendor, same part (e.g. Corsair RM750e and RMe spelling) |
| V true variant | 28 | RGB vs non-RGB memory; ARGB vs non-ARGB fan/case; heatsink vs no heatsink storage; single vs pair fan |
| A ambiguous | 29 | clearance ("מציאון ועודפים") listings of the same title, or a colour not stated on one side |

- **Examples** (product_id | listing_key | vendor | field | observed | verbatim title):
  - M safe merge: `model:aio:240-nautilus-rs-240mm-black-rgb` | `1pc:206391` (SKU `CW-9060092-WW`) and `1pc:221790` (SKU `221790`) | 1pc | sku | same Nautilus 240 RS ARGB black | "קירור נוזלי למעבד Corsair NAUTILUS 240 RS ARGB בצבע שחור" / "קירור נוזלי למעבד NAUTILUS 240 RS ARGB – שחור". Flagged `duplicate_vendor`.
  - M safe merge: `model:aio:360-nautilus-rs-360mm-black-rgb` | `1pc:206392` / `1pc:222392` | 1pc | sku | same black ARGB 360 | "…NAUTILUS 360 RS ARGB בצבע שחור" / "…NAUTILUS 360 RS ARGB שחור".
  - A ambiguous: `model:aio:240-rog-ryuo-240mm-white` | `ksp:475172` / `ksp:260027` | ksp | sku | one listing is clearance | "מציאון ועודפים - קירור נוזלי למעבד ASUS ROG Ryuo III 240 ARGB - מהדורה לבנה" / "קירור נוזלי למעבד ASUS ROG Ryuo III 240 ARGB - מהדורה לבנה". Same title after the prefix; not settled.
  - A ambiguous: `model:aio:360-nautilus-rs-360mm-black` | `1pc:179082` / `1pc:222391` | 1pc | sku | one title has no colour | "קירור נוזלי למעבד Corsair NAUTILUS 360 RS 360mm" / "…NAUTILUS 360 RS שחור".
  - V true variant: `model:case:1-ft-performance-black` | `tms:PERFORMANCE1FTARGB` / `tms:0-761345-10088-5` | tms | sku | ARGB vs non-ARGB | "מארז מחשב Antec Performance 1 FT ARGB" / "מארז מחשב Antec Performance 1 FT".
  - V true variant: `model:case:1-m-performance-black` | `tms:0-761345-10168-4` / `tms:0-761345-10169-1` | tms | sku | Black vs Aventurine | "מארז מחשב Antec Performance 1 M Black" / "…Performance 1 M Aventurine".
- **Fix direction:** for the 28 V, check whether lighting (memory, fans) and heatsink (storage) are in `identity.AXES`; for the 29 A, strip the clearance prefix before comparison and read the colour from the detail table. Not verified against `AXES` yet.

### S3-7: distinct-unsplit products titles do not settle (6 products)

- `model:case:2u-case-performance-rackmount` (D-200L vs P-200L), `model:case:flow-h5-white` (CC-H51FW-01 vs CC-H52FW-01), `model:case:m10-tl-vision-black` and `…-white` (FAN4-C vs FAN4-M suffix), `model:memory:…3200mt-amd-…-gammix…` (AX4U320032G16A-SBKD35P vs -SBKD35), `model:psu:a750bn-mag-pcie5-750w` (S1-3 also).
- **Confidence:** medium. **Fix direction:** read the maker's own page or the detail table.

## Rejected false positives (R-1, R-2, R-3)

- **R-1, correctly merged (58 products).** Titles agree on one part: e.g. CPU tray OPN across vendors (`AT8076806414`, `C245KFT`), ICE and non-ICE boards correctly split by name, `GB`/`GX` prefix spellings, `-W` suffix spellings of the same part, Gigabyte `GV-` prefix (`gpu` 9070 XT). Retailer codes (TMS `C…`, Ivory `I3-…`, KSP numeric `uin`, 1PC numeric ids) are not part numbers and are correctly excluded.
- **R-2, alias twins (18).** Each retired pid points at a product that differs from a live twin only in Tray vs no-Tray (e.g. `model:cpu:12400-tray` → `corei512400-tray` with live `model:cpu:12400`). True packaging variants; no action beyond the S1-2 fix.
- **R-3, scan 3 token-set (3052 candidate pairs).** Sample of 12 random pairs were all different parts (different brands or models). The token rule matches by shared generic tokens; not a detector.
- **Strict EAN.** A lenient first pass produced 39 shared barcodes, all false. Not counted.

## Out-of-lane sightings

- **Lane 02 (identity):** all-digit AMD OPN (`100000000593`) hits the `isdigit()` vendor check before `_MFR_PREFIXES`, so a valid OPN is read as a vendor code.
- **Lane 02 (identity):** `ean_of` reads only attrs and MPN/SKU; detail-table barcodes (`ברקוד`) are not read by the EAN tier. Count not taken.
- **Lane 02 (identity):** `packaging` axis derivation on `1pc:152181` and `ksp:340400` (S1-2).
- **Working tree:** many uncommitted edits from other work; not touched.

## Not checked

- Scan 3 as a detector: rejected; no token-based duplicates found.
- Silent-or-flagged for the 58 correct merges: reported by the script, not reviewed further.
- `bundle_only` was checked only for the 36 listings in the 18 same_part pairs.
- The 6 ambiguous products, 4 ambiguous S2-5 pairs and 29 ambiguous S3-6 pairs need a human look.
- No `rekey` pairs were found; the re-keyed listing class was not searched beyond the URL test.

## Silent-or-flagged split

- Distinct-unsplit products: 90, of which 21 silent (S1-1 1, S3-7 1, R-1 19).
- Same-vendor pairs: 118 scan-4 pairs, 1 silent (S2-4 `KF560C30BBEA-32X2`); 63 unknown pairs all flagged.
- Alias twins and scan 3: not QA-based.
