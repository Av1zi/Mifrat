# Audit 02: wrong merges (different parts inside one product)

- Git HEAD: `1e353d17` (rechecked before writing). Pinned at the start of the lane as `1534928e`; the HEAD moved during the audit. Commits in between touched CI, the worker, `scraper/qa_tool.py`, `scraper/download_images.py` and `scraper/pcpartdb.py`. `scraper/identity.py`, `scraper/matching.py` and `data/` are unchanged, so the evidence applies to both HEADs.
- `data/catalog.json` `generated_at`: `2026-11-09T22:13:04.288166+00:00` (7095 listings, 4383 products, 542 identity cases). Unchanged across both checks.
- Scope: read-only. Only this file, the JSONL and `tmp/data-audit/02-wrong-merges/` were written.

## Summary

| Finding | Severity | Confidence | Scope | What is wrong |
|---|---|---|---|---|
| F-01 | S1 | high | 1 product | Black SKU sits in the white Antec C5 Curve product, and it is the best offer (404) |
| F-02 | S1 | high | 1 product | Glass-panel-only offer (95) is the best offer for the whole NX410 case |
| F-03 | S1 | high | 1 product | Arctic F12 fan (KSP, stale, 24) is the best offer for an Antec F12 |
| F-04 | S1 | high | 1 product | Arctic P14 fan (KSP, stale, 32) is the best offer for an Antec P14 |
| F-05 | S1 | medium | 1 product | RX 9070 XT (4397) and RX 9070 (3979, 3190 stale) share one MPN |
| F-06 | S2 | high | 1 product | 1PC Box listing merged into a TMS Tray product (same MPN) |
| F-07 | S2 | high | 1 product | 1PC Tray listing (title and MPN say Tray) sits in the Box product, at the top price |
| F-08 | S2 | medium | 1 product | KSP Box listing moved into the Tray product by the packaging fix (trap case) |
| F-09 | S2 | high | 4 products | `-black` product ids hold white-only offers (1PC colour attribute) |
| F-10 | S2 | high | 1 product | Yahav black fan kit (160) and white fan kit (160) in one product |
| F-11 | S2 | medium | 1 product | Bare GX-1200 SKU (no colour) merged with its `-W` white SKU |
| F-12 | S2 | medium | 1 product | Bare GSK850 V2 SKU (no colour) merged with its `-W` white SKU |
| F-13 | S2 | high | 1 product | Black-walnut 4000D offer merged into the white/oak product (Hebrew `אגוז` dropped) |
| F-14 | S2 | medium | 1 product | Black and Aventurine Antec 1 M SKUs in one product |
| F-15 | S2 | medium | 1 product | 100R white offer and an offer with no colour on two EANs in one product |
| F-16 | S2 | medium | 1 product | A13 360 white offer and an uncoloured offer on two EANs |
| F-17 | S2 | medium | 1 product | E360 uncoloured offer (own EAN) in the white product |
| F-18 | S2 | medium | 1 product | A750BN PCIE5 III and A750BN Bronze on two EANs |
| F-19 | S2 | high | 2 products | Same MPN in a manual product and an identity product: blocked merge (14600K, 14900K) |
| F-20 | S3 | high | 1 product | Product id says 5600 MT/s; the part is 6000 (TMS speed attribute wrong) |
| F-21 | S3 | medium | 1 product | Motherboard offer has `memory_type` DDR4 while its title says DDR5; merge looks right |
| F-22 | S3 | high | systemic | 1PC colour attribute contradicts its own title on 22 of 862 comparable offers (other vendors 0 to 3) |
| F-23 | S3 | high | systemic | Junk model codes in identity products: 2712 (colour, light, size, Hebrew, or length) |

Counts: S1 5, S2 14, S3 4. Every wrong-merge finding has a silent or flagged status below. The scan floor is noted in Method.

## Method

Read-only analysis against `data/catalog.json` and `data/site/qa.json`, using the `scraper/identity.py` API. Scripts live in `tmp/data-audit/02-wrong-merges/`:

1. Axis conflicts inside a product: `scan.py` writes `scan_results.json`. 121 products carry an in-product axis conflict (`s1_axis_conflicts`).
2. Title check per conflict: `scan_s1_titles.py` writes `scan_s1_titles.json`. Title support mostly does not decide the axis (non-colour axes are reported as `non_colour_axis`).
3. Manufacturer PN check: `scan_s1_mpn.py` writes `scan_s1_mpn.json`. 88 of 121 have one identical manufacturer PN on every offer (attribute noise); 22 need a title judgement (`nompn_list.txt`, reviewed). 58 products have title-token Jaccard below 0.5.
4. Colour title vs attribute, comparable offers only: `scan_attr.py` (`scan_attr.json`) and `colour_by_vendor.txt`. The earlier raw count of 108 is inflated by regex noise: the PSU word "Gold" (80+ rating), fan "Red" and "Blue" (RGB effect words) and slash attributes such as "Black / White". The vendor-level count is 1PC 22/862, TMS 3/568, Ivory 1/312, KSP 2/306, Yahav 0/482.
5. Manufacturer PN across products: `scan_attr.py` (2b) and `check_pack_o11.py` (same MPN in two or more products).
6. Price spread: `scan.py` (`s3_spread_dist`): 1940 multi-offer products, p50 1.101, p90 1.456, p99 2.222, 104 at ratio of 1.6 or more, 32 at 2 or more. All 32 at 2 or more were listed and classified (see Findings and Suspicions). `bundle_only` is set on 0 of the 104; stale is set on 5 of the 104 (reported separately).
7. Self-contradiction (product id colour word vs product attribute, canonical name, offer titles): `scan_rest.py` writes `scan_rest.json` (`s4_pid_contradiction`). 95 hits, of which 48 are PSU "gold" hits (efficiency rating, not colour, false positive). 47 non-PSU hits: the findings below are the ones that were inspected; the rest were not reviewed.
8. Junk model codes: `scan_rest.py` (`s5_junk_pids_n` 2712 of 4232 identity products; 48 with conflicting offer colours). Blocked-merge effect measured by same MPN in two products (see F-19).
9. Manual products: `scan_rest.py` (`s6`): 50 manual products, 35 with two or more offers, 10 flagged (`manual_multi_mpn.txt` for the multi-MPN ones).
10. Seeded samples (`random.seed(20261110)`): `sample_identity.txt` (30 of 195 `identity_merge`), `sample_packaging.txt` (20 of 50 `packaging_conflict`). Both were judged by reading titles and raw rows.
11. Identity check: `scripts/check_identity_merge.py` exit 0; I1 1906 products, I2 4202 identities, I3 fixtures 10 and CPU products 216 checked; invariants hold.

Sample error rates:
- `identity_merge` (30 judged): 3 wrong (f12, p14, 7500). Error rate 10%. 1 unclear (3240-tray, 1PC title gives no packaging), counted as correct.
- `packaging_conflict` (20 judged): 1 wrong (14900K, F-07). Error rate 5%. The 245KF trap (F-08) is in the sample and counted separately as a corroboration question, so 2 of 20 (10%) if included.

Mechanisms traced in code (`scraper/identity.py`, `scraper/matching.py`):
- `part_number_class` returns "vendor" when a printed number equals the listing's own SKU, and when it is all digits (EAN-shaped). Such numbers never split in `part_number_subgroups` (called from `matching.py` ~5603). Traced; drives F-01, F-10, F-11, F-12, F-14 to F-18.
- `identity._compact` drops Hebrew, so `אגוז` (walnut) reads as unknown and rides along in the merge. Traced; drives F-13.
- The packaging fix (`matching.py` ~6200-6341) moves the copy chosen by sibling-offer count, not by label evidence; KSP has no MPN, so a KSP Box/Tray pair with equal price always passes corroboration. Traced; drives F-08.
- The 1PC colour attribute is wrong in ways the title is not. Traced by comparison (F-09, F-22); the identity code reads the attribute.

## Findings

Findings are ordered by severity. The fix direction is one line each. "Silent" means no `identity_merge`, `packaging_conflict` or other QA case exists in `data/site/qa.json` for the product; "flagged" lists the QA kinds.

### S1

**F-01 Antec C5 Curve (black SKU in the white product)**
- product: `model:case:c5-curve-white`; listings `1pc:207639`, `tms:0-761345-10225-4`, `1pc:207641`, `tms:0-761345-10226-1`
- observed: the product id and canonical name say White. The black SKU `0-761345-10225-4` is in it and holds the best offer (TMS 404). Offer attributes read `color: White` on every listing, but the titles say Black on the SKU `…10225-4` (`מארז מחשב Antec C5 CURVE ARGB בצבע שחור`, TMS `… ARGB Black`).
- expected: the black SKU is a separate product; the best offer for the white product is 413 (TMS `…10226-1`).
- expected source: the offer titles (scraper output `title_raw`).
- cause: traced. Both SKUs are EAN-shaped and equal the vendor SKU, so `part_number_class` returns "vendor" and the pair never splits.
- status: flagged (`identity_merge` ×1, `duplicate_vendor` ×2).
- fix direction: stop treating a printed number equal to the vendor's SKU or all-digit as a same-part bridge, and split when the offers' own titles name different colours.

**F-02 Antec NX410 (glass panel in the case product)**
- product: `model:case:nx410-black`; listings `1pc:132022`, `tms:0-761345-81041-8`, `yahav:7999`
- observed: `yahav:7999` (`זכוכית למארז חברת Antec מותאמת לדגם Antec NX410 RGB Tempered Glass Only צבע שחור - פאנל זכוכית בלבד`, 95 NIS) is the best offer of the case product. The panel is an accessory, not the case.
- expected: the panel is not a case offer; the best case offer is 242 (TMS).
- expected source: title says "פאנל זכוכית בלבד" (glass panel only).
- cause: traced. The panel's model text collapses to `nx410`; its MPN `NX410-TEMPERED-GLASS-ONLY` is manufacturer-shaped while the others are vendor-shaped, so no split.
- status: flagged (`identity_merge`).
- fix direction: exclude panel-only and accessory titles from the case identity (use the accessory type as an axis).

**F-03 Antec F12 fan (Arctic F12 from KSP)**
- product: `model:case_fan:f12-120mm-rgb-black`; listings `1pc:96015`, `tms:0-761345-75287-9`, `ksp:192969`
- observed: `ksp:192969` (`מאורר למארז Arctic F12 120mm - שחור`, 24 NIS, stale) is the best offer. Arctic is a different brand from Antec.
- expected: the Arctic F12 is a separate product; Antec F12 best offer is 39 (TMS).
- expected source: title brand `Arctic`; the other two offers say Antec.
- cause: traced. The KSP row has no MPN and no brand attribute, so the code `f12` alone joins it.
- status: flagged (`identity_merge`).
- fix direction: require brand agreement (vendor brand or title brand) before a code-only join.

**F-04 Antec P14 fan (Arctic P14 from KSP)**
- product: `model:case_fan:p14-140mm-rgb-black`; listings `1pc:172032`, `tms:0-761345-40038-1`, `ksp:235707`
- observed: `ksp:235707` (`מאוורר למארז Arctic P14 140mm - צבע שחור`, 32 NIS, stale) is the best offer. Same mechanism as F-03.
- expected: Antec P14 best offer is 40 (TMS).
- expected source: title brand `Arctic`.
- cause: traced (as F-03).
- status: flagged (`identity_merge`).
- fix direction: as F-03.

**F-05 Asus Prime RX 9070 / 9070 XT (one MPN, two cards)**
- product: `model:gpu:9070-gddr6-oc-prime-rx-xt-16gb`; listings `tms:90YV0L71-M0NA00` (`Asus Prime RX 9070 XT 16GB GDDR6 OC Edition`, 4397), `1pc:195916` (`ASUS Prime Radeon RX 9070 OC Edition 16GB GDDR6`, 3979), `ksp:371874` (`Asus Prime Radeon RX 9070 16GB GDDR6 OC Edition`, 3190, stale)
- observed: the chipset attribute differs (TMS `Radeon RX 9070 XT`, 1PC and KSP `Radeon RX 9070`). The cheapest offer (3190, stale) is the non-XT card.
- expected: two products (9070 and 9070 XT), unless the MPN is wrong on one vendor.
- expected source: titles and chipset attribute; the MPN is the only bridge.
- cause: unverified. One MPN is shared across the two model names, so either the TMS MPN is wrong or ASUS uses one number for both. The GPU axis set does not include the chipset model.
- status: silent (no QA case).
- fix direction: check the MPN against the manufacturer page; add the GPU model (chipset) to the GPU variant axes.

### S2

**F-06 Intel Core i5 7500 (Box and Tray in one product)**
- product: `model:cpu:7500`; listings `1pc:134718` (`מעבד Intel Core i5 7500 צבע קופסה`, 397, Box), `tms:C7500T-P` (`Intel Core i5 7500 / 1151 Tray Pull`, 378, best)
- observed: Box (1PC) and Tray (TMS) share MPN `C7500T-P`, and the product holds both. The alias `mpn:cpu:c7500tp` points to this product.
- expected: Box and Tray are two products (decisions.md: Box and Tray are two products unless the labels are wrong).
- expected source: `decisions.md` (Box vs Tray rule); titles.
- cause: unverified. The packaging axis should split on the title conflict, and it does not; the mechanism was not traced.
- status: flagged (`identity_merge` ×1, not resolved).
- fix direction: packaging must split when titles say Box vs Tray even when the MPN is shared.

**F-07 Intel Core i9 14900K (Tray listing in the Box product)**
- product: `model:cpu:14900k` (Box); listing `1pc:152189` (title `מעבד Intel Core i9 14900K / 1700 Tray`, MPN `C14900KT`, packaging attribute `Box`, price 2589, highest in product). Best offer is KSP `ksp:280959` (Box, 1899, stale).
- observed: the 1PC packaging attribute says Box, while the title and MPN say Tray. The same MPN `C14900KT` sits in the manual Tray product `model:cpu:corei914900k-tray` (F-19).
- expected: the 1PC listing is the Tray product, and the Box product's top offer is 1899 (KSP).
- expected source: title and MPN (MPN `C14900KT` is the Tray SKU at TMS).
- cause: traced. The attribute is the 1PC source; identity reads the attribute, so the attribute and the product agree and no conflict fires.
- status: flagged (`identity_merge`, `packaging_conflict` open).
- fix direction: when the title and the packaging attribute disagree, use the title and send the case to `packaging_conflict`.

**F-08 Intel Core Ultra 5 245KF Tray (KSP Box moved in by the packaging fix; trap case)**
- product: `model:cpu:245kf-tray`; listing `ksp:340400` (title `… 245KF 24MB Cache LGA1851 - Box`, 690, moved in by the packaging fix, `resolved: True`). The Tray copy `ksp:340404` (title `… - Tray`, 690) stays in place.
- observed: the raw KSP rows (`data/raw/2026-11-07/ksp.jsonl`) for 340400 and 340404 have identical tags except `תכונות` (Box vs Tray). Both are 690. KSP has no MPN.
- expected: the corroboration test (equal price and identical tags except packaging, or a shared maker part number) passes on its letter. The direction is the problem: nothing in the evidence says the Box copy is the wrong label; the code chose it by sibling-offer count.
- expected source: decisions.md (moving a listing on corroborated packaging evidence is by design); the raw rows.
- cause: traced (`matching.py` ~6200-6341).
- status: flagged (`packaging_conflict` resolved; `duplicate_vendor` ×2; `packaging_conflict` open ×1).
- fix direction: require a shared maker PN for a move, or move only when another vendor's label supports the other side.

**F-09 AIO colour suffix contradicts the offers (four products)**
- products and listings:
  - `model:aio:04cfm-…-mystic-white-240mm-black`: `1pc:169966` (title `… בצבע לבן`, attr Black); `yahav:10016` (White, 450, best)
  - `model:aio:9060072-cw-ww-240mm-black`: `1pc:141859` (title `מאוורר מים CORSAIR iCUE H100i ELITE CAPELLIX XT צבע לבן`, attr Black); Ivory and TMS White
  - `model:aio:cooler-tulong-w360-warrior-water-360mm-black-2`: `1pc:165187` (title `… W360 White Water Cooler`, attr Black); TMS White
  - `model:aio:coolermaster-flux-liquid-pl360-360mm-black-2`: `1pc:132844` (title `… PL360 Flux בצבע לבן`, attr Black)
- observed: every offer and the canonical name say White; the id says `-black` because the 1PC colour attribute says Black.
- expected: the merge is right (all titles white); the product id colour is wrong. This is not a wrong merge.
- expected source: titles and the other vendors' colour attribute.
- cause: traced in pattern (1PC colour attribute, F-22); the id suffix comes from the attribute.
- status: 04cfm flagged (`identity_merge`, `spec_conflict` ×3); the other three silent.
- fix direction: take the id colour from the agreed title colour, not from a single vendor attribute.

**F-10 Yahav case-fan kit (black and white in one product)**
- product: `model:case_fan:3-3x120mm-c120-connect-pwm-reverse-120mm-3-rgb-white`; listings `yahav:10321` (title `… בצבע שחור`, 160), `yahav:10783` (white, 160)
- observed: same price, both Yahav. MPNs `C120ARGB-REVERSE-3PK` and `C120ARGB-REVERSE-3PK-WHITE` differ only by the `-WHITE` suffix; the SKU-equal rule makes them "vendor" and no split.
- expected: two products, black and white.
- expected source: titles.
- cause: traced (vendor class).
- status: flagged (`duplicate_vendor` ×1).
- fix direction: as F-01.

**F-11 Seasonic GX-1200 (bare SKU merged into the white product)**
- product: `model:psu:1-1200-3-gx-vertex-1200w-white`; listings `tms:12122GXAFS` (bare, 1091, best, `bundle_only` true, no colour in title), `tms:12122GXAFS-W` (white, 1138, `bundle_only` true)
- observed: the best offer is the uncoloured SKU, in a white-named product.
- expected: the `-W` SKU is the white variant. The bare SKU's colour is not stated in the title, so its product is uncertain.
- expected source: SKU suffix and the white title on `-W`.
- cause: traced (SKU-equal rule, both vendor-shaped).
- status: flagged (`duplicate_vendor`).
- fix direction: as F-01 (split a `-W`/`-B` pair on suffix as a colour axis).

**F-12 Antec GSK850 V2 (bare SKU merged into the white product)**
- product: `model:psu:1-850-atx3-full-gsk-modular-v2-850w-full-white`; listings `tms:GSK850V2` (bare, 426, best, no colour), `tms:GSK850V2-W` (white, 444)
- observed: as F-11.
- expected: `-W` is the white variant.
- expected source: as F-11.
- cause: traced (SKU-equal rule).
- status: flagged (`duplicate_vendor`).
- fix direction: as F-11.

**F-13 Corsair 4000D Wood (black walnut merged into white/oak)**
- product: `model:case:4000d-rs-wood-white`; listings `ksp:492605` (white/oak, 519, stale), `ksp:492602` (attribute `color` is `אגוז`, 519, stale)
- observed: `ksp:492602` is black walnut (its colour attribute `אגוז` is "walnut"); the product is white.
- expected: two products (white/oak and black walnut).
- expected source: colour attribute `אגוז`; the product id.
- cause: traced. `identity._compact` drops Hebrew, so `אגוז` is unknown and rides along.
- status: flagged (`duplicate_vendor`).
- fix direction: map Hebrew colour words (אגוז, בז', חום) into the colour axis instead of dropping them.

**F-14 Antec Performance 1 M (Black and Aventurine in one product)**
- product: `model:case:1-m-performance-black`; listings `1pc:183243` (`… שחור`, 899), `1pc:183246` (`… אוונטורין`, 899), `tms:0-761345-10168-4` (Black, 879), `tms:0-761345-10169-1` (Aventurine, 879)
- observed: two SKUs with two EAN-shaped numbers, both attributes say Black. Titles name two finishes (Black and Aventurine).
- expected: two products, one per finish, if Aventurine is a separate finish. The vendor titles treat them as different.
- expected source: titles; the two SKUs.
- cause: traced (EAN-shaped rule). Whether Aventurine is a separate physical product is not verified from a manufacturer source.
- status: flagged (`duplicate_vendor` ×2, `identity_merge` ×1).
- fix direction: add the finish name as a colour-like axis.

**F-15 MSI MAG Pano 100R PZ (no-colour offer in the white product)**
- product: `model:case:100r-mag-pano-pz-white`; listings `1pc:179941` (`מארז מחשב MSI MAG PANO 100R PZ`, 545, best, no colour; EAN 4711377231565 that the canonical name calls Black), `1pc:179942` (`… PZ WHITE`, 604, EAN 4711377231572)
- observed: two EANs in one product. The best offer is the uncoloured one.
- expected: two products, or at least the best offer is the white one (604).
- expected source: EAN; canonical name; titles.
- cause: traced (EAN-shaped rule; the code comment says one barcode names one part, but two barcodes here name two parts).
- status: flagged (`duplicate_vendor`).
- fix direction: a second distinct EAN on the same vendor is a variant signal, not a bridge.

**F-16 MSI MAG Coreliquid A13 360 (white offer and uncoloured offer)**
- product: `model:aio:360-a13-coreliquid-mag-360mm-white`; listings `1pc:192580` (`קירור נוזלי MSI MAG CORELIQUID A13 360 ARGB`, 413, best, no colour, EAN 4711377273770), `1pc:192581` (`… בצבע לבן`, 530, EAN 4711377276689)
- observed: two EANs. Best offer is the uncoloured one, in a white-named product; canonical name says Black.
- expected: two products.
- expected source: EAN; titles.
- cause: traced (EAN-shaped rule).
- status: flagged (`duplicate_vendor`).
- fix direction: as F-15.

**F-17 MSI MAG Coreliquid E360 (uncoloured own-EAN offer in the white product)**
- product: `model:aio:coreliquid-e360-mag-360mm-white`; listings `1pc:151938` (`קירור נוזלי למעבד MSI MAG CORELIQUID E360`, 658, no colour, EAN 4711377115735), `1pc:163231` (`… WHITE`, 732, EAN 4711377124157), `yahav:9643` (White, 650, best, EAN 4711377124157)
- observed: the uncoloured offer has its own EAN; the white offers share one.
- expected: the uncoloured EAN is a different product (probably the black E360); best offer for the white product is yahav 650.
- expected source: EAN; canonical name (`… White Mystic … Black`).
- cause: traced (EAN-shaped rule).
- status: flagged (`duplicate_vendor`, `identity_merge`).
- fix direction: as F-15.

**F-18 MSI MAG A750BN PCIE5 750W (two EANs)**
- product: `model:psu:a750bn-mag-pcie5-750w`; listings `1pc:214404` (`ספק כוח MSI MAG A750BN PCIE5 III בצבע שחור`, 365, best, EAN 4711377364317), `1pc:161258` (`… 750W 80+ Bronze`, 472, EAN 4711377126595; attribute `80 PLUS Bronze`)
- observed: two EANs; the best offer has no efficiency rating; the other is Bronze.
- expected: possibly two products (PCIE5 III revision vs the original), not verified from a manufacturer source.
- expected source: EAN; titles.
- cause: traced (EAN-shaped rule).
- status: flagged (`duplicate_vendor`).
- fix direction: as F-15.

**F-19 Blocked merges: the same MPN in a manual product and an identity product (Intel 14600K, 14900K)**
- products: `model:cpu:corei514600k-tray` (manual) vs `model:cpu:14600k` (identity), both holding MPN `C14600KT`; `model:cpu:corei914900k-tray` (manual) vs `model:cpu:14900k`, both holding `C14900KT`
- observed: manual products are skipped by the I1/I2 checks, so the duplicate pair stays split. `check_pack_o11.py` finds these two MPN keys across products, and no other same-MPN pair exists in the catalog.
- expected: one product per part, with the Tray copy in the Tray product.
- expected source: the shared MPN.
- cause: traced (manual products are not re-checked; `scan_rest.py` s6 and `check_pack_o11.py`).
- status: flagged (`packaging_conflict`, open ×2 on `corei514600k-tray`; ×1 on `corei914900k-tray`; `variant_conflict` on `14600k`).
- fix direction: run I1/I2 on manual products too, and merge a manual product's listings into the identity product when the MPN matches.

### S3

**F-20 Kingston FURY Beast 2x16GB (product id speed wrong)**
- product: `model:memory:16gbx2-36-beast-cl-fury-32gb-x2-5600mhz-cl36-rgb-white`; listings `tms:KF560C36BWE2AK2-32` (title `… 6000 CL36 White`, attribute `speed_mhz` 5600, 2720), `yahav:10195` (`… 6000MHZ CL 36`, attribute 6000, 2320)
- observed: the TMS speed attribute (5600) contradicts its own title (6000). The product id `5600mhz` follows the attribute.
- expected: the product is a 6000 MT/s part (same MPN, both titles say 6000).
- expected source: titles.
- cause: traced (TMS speed attribute).
- status: silent.
- fix direction: read speed from the title when the attribute and title disagree; flag the conflict.

**F-21 MSI PRO H610M-E (DDR4 attribute on a DDR5 board)**
- product: `model:motherboard:e-h610m-pro-microatx`; listings `1pc:172045` (`MSI PRO H610M-E DDR5`, DDR5, 428), `ivory:176668` (`MSI PRO H610M-E DDR5 1700 mATX`, attribute `DDR4`, 365, best)
- observed: the Ivory memory-type attribute says DDR4 while its title says DDR5. The merge looks right (same title and chipset). It did not split on `memory_type` for an unexplained reason.
- expected: DDR5 board, one product.
- expected source: titles.
- cause: unverified. The attribute is wrong; the split did not fire; the bridge through EAN `4711377125147` was not traced.
- status: silent.
- fix direction: read memory type from the title when the attribute disagrees; trace the bridge.

**F-22 1PC colour attribute (systemic)**
- observed: 22 of 862 comparable 1PC offers have a colour attribute that contradicts their single-colour title (TMS 3/568, Ivory 1/312, KSP 2/306, Yahav 0/482). Source: `colour_by_vendor.txt`, `scan_attr.py`.
- expected: attribute matches title.
- cause: traced by comparison; the attribute source is not traced.
- status: mixed (F-09 and others).
- fix direction: stop trusting the 1PC colour attribute over the title; log the contradiction.

**F-23 Junk model codes (systemic)**
- observed: 2712 of 4232 identity products carry a junk word in their model code: colour 2062, light 820, size 1133, length over 40 characters 1392 (counts overlap). Among them 48 products have conflicting offer colours (wrong-merge effect, a floor). The blocked-merge effect could not be measured: same-MPN pairs across products are only the two in F-19.
- expected: codes name the part, not the colour or size.
- cause: traced (the code keeps the title words).
- status: systemic.
- fix direction: strip colour, light and size words from the code and keep them as axes.

## Suspicions

- 1PC fan prices run 2 to 6 times TMS on the same MPN (fans in 26 of the 32 spread products at 2 or more: `scan.py` `s3_spread_high`). Not a merge: it could be a pack, price error or missing quantity. Not verified.
- 1PC `model:case:br-ca-h510i-h510i-black`: 1028 vs TMS 493 on the same MPN `CA-H510I-BR`. Not verified.
- `model:motherboard:aorus-pro-x3d-x870e-atx`: chipset X870 (1PC) vs X870E (TMS, Yahav) under one MPN; QA `variant_conflict` exists. Titles not judged.
- `model:cpu:3240-tray`: the 1PC listing has no packaging label (its title says "צבע שחור"); counted as correct in the sample. Not verified.
- 47 non-PSU hits in `scan_rest.json` `s4_pid_contradiction` not reviewed beyond the findings above.

## False positives

- Scan 2 multi-spelling MPNs: `GX870EAORUSPROICE` vs `X870EAORUSPROICE` (one part, two spellings); `ryzen79800x3d-tray` spelling variant; `corei512400-tray` (I5-12400 OEM code and CM8071504650608 MM code are one Intel part).
- Scan 1 colour regex noise: PSU "Gold" (80+ rating); fan "Red" and "Blue" (RGB effect words); "Black / White" and "Black / Brown" attributes.
- Scan 4 PSU hits: 48 "gold" hits (efficiency rating, not colour).
- `model:cooler_air:nh-p1-160mm-black`: KSP passive NH-P1 (stale) is the same passive cooler; the colour attribute Black is consistent. Not a wrong merge.
- `case:lian-li:o11-dynamic-mini-v2-white` (lead): all four offers are Mini V2 White, MPN `O11DMIV2W`. No non-Mini "O11 Dynamic V2" listing exists in `data/catalog.json` (search over all listing titles). Clean.
- `model:case:flux-white-white`, `model:case:501-base-dx-pure-white`, `model:cooler_air:82cfm-d15-nh-170mm-140mm`: correct in the identity sample.
- KSP 340400 + 340404 packaging move: the move is by design per decisions.md; reported as F-08 only for the corroboration question.

## Out-of-lane sightings

- `model:memory:ddr5-pro-48gb-x1-5600mhz-cl46-black-dimm`: TMS 2523 vs 1PC 581 on the same MPN `CP48G56C46U5` (ratio 4.3). Merge looks right; the TMS price looks wrong. Price lane.
- Stale KSP rows at the top of spread lists (5 of 104 at 1.6 or more). Stale lane.
- `data/catalog.json` `identity_cases` count is 542; `qa.json` cases total 879 across kinds. Counts lane.

## Not checked

- Individual judgement of the 22 no-MPN products beyond those in the findings (`nompn_list.txt`).
- The 47 non-PSU scan 4 hits beyond the findings.
- Scan 3 spread beyond the 32 at 2 or more: classified by pattern only.
- 165 of 195 `identity_merge` cases and 30 of 50 `packaging_conflict` cases (outside the seeded samples).
- The 1PC colour pattern in categories other than identity categories.
- Product-level spec read-back for chipset, speed and colour (only the findings above).
- The 14 non-Hebrew titles.
- Why `variant_conflict` did not split the F-09 and F-21 pairs (trace not done).
