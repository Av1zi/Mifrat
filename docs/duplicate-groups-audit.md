# Duplicate groups remaining in the identity categories

**Status:** completed and closed (historical). Outcomes, 2026-11-07..08: R1, R3, R4 and R6 were
implemented; R5 and R7 now emit `variant_conflict` QA cases instead of merging; R2 was measured
and rejected (2 merges for 322 renamed product ids). Counts below are from the 2026-11-07 catalog
and are not kept current.

Originally a read-only audit: no file under `scraper/`, `scripts/` or `data/` was modified, and no
catalog was regenerated. Everything below is derived from the catalog on disk at the time.

**Date:** 2026-11-07

---

## 1. Scope and method

In-scope categories are the ten in `scraper/identity.py::AXES`:
`cpu, memory, gpu, motherboard, storage, case, psu, case_fan, aio, cooler_air`.
(`AGENTS.md`/the brief mention "11 categories"; `AXES` has 10. `accessories` and `other` are
deliberately out of scope, per D2.)

Three independent scans were run against `data/catalog.json`:

1. **Exact-identifier scan** — group products that share an EAN/barcode, an exact manufacturer
   MPN, or a verified manufacturer model code.
2. **Identity-bucket scan** — group products that sit in the same `(category, model_code,
   variant-axes)` bucket, i.e. the model code says "same thing" but they were not merged.
3. **Token-set scan** — for every same-category/same-brand pair, drop brand words, generic body
   words and axis values (colour, lighting, quantity) from the offers' titles and model rows; if
   two products still produce an identical token set containing a digit, they are a candidate
   duplicate. Connected components of those pairs are the 62 groups below.

**This is a floor, not a ceiling.** The token scan needs an identical residual token set, so it
misses duplicates whose extra word is *not* in its noise list. Absence of a group is not proof
that no duplicate exists.

**What the scans found at the identifier level:**

| Check | Result |
| --- | --- |
| Shared EAN/barcode across two products | **0 groups** |
| Shared exact manufacturer MPN across two products | **0 groups** |
| Shared verified maker model code, still split | **5 code keys / 10 products** (all Gigabyte motherboards) |
| Same identity bucket, still split | **12 groups / 24 products** (case 1, memory 2, motherboard 5, storage 4) |
| Token-set candidates | **62 groups / 130 products** |

So the hard-identifier tiers (EAN 5b, MPN 3/4a, identity 2) are doing their job. What remains is
either (a) soft evidence that never reaches a tier, or (b) a variant suffix that the tiers read as
a different part.

---

## 2. Measured state

```
catalog products        4459
listings                7104
products in AXES cats   4362
identity_cases          1363
  identity_merge        1266
  packaging_conflict      50
  split_candidate          7
  variant_conflict        40
```

The 62 candidate groups cover **130 products**; merging every group would remove **68 product
rows** (1.5% of the catalog).

Of those 62 groups:

| Dimension | Split |
| --- | --- |
| Already carrying a QA flag (`identity_merge`/`variant_conflict`) | 20 groups (16 + 4) |
| **Silent — no QA flag at all** | **42 groups** |
| Same-vendor duplicate listings (one shop, two catalogue rows) | 25 groups / 50 products |
| Cross-vendor duplicates (affects price comparison) | 37 groups / 80 products |
| MPN on one side only | 44 groups |
| Both sides carry conflicting MPNs | 18 groups |
| Both sides carry the same MPN | 0 groups |

Risk split used below (colour / lighting / quantity conflict between the two sides):
**35 safe-ish (70 products)**, of which 14 have strong bridge evidence and 21 are weak-evidence
only; **27 ambiguous (60 products)** that must not be merged automatically.

---

## 3. Candidate groups by category

| Category | Catalog products | Groups | Products | Rows removed if merged |
| --- | ---: | ---: | ---: | ---: |
| case | 713 | 19 | 39 | 20 |
| case_fan | 537 | 12 | 24 | 12 |
| cooler_air | 245 | 9 | 18 | 9 |
| gpu | 353 | 8 | 17 | 9 |
| motherboard | 749 | 7 | 16 | 9 |
| aio | 271 | 3 | 6 | 3 |
| memory | 534 | 3 | 8 | 5 |
| psu | 349 | 1 | 2 | 1 |
| cpu | 214 | 0 | — | — |
| storage | 397 | 0 (see §7) | — | — |
| **total** | **4362** | **62** | **130** | **68** |

### Category × root cause

| Category | R1 no code | R1b neither coded | R2 code divergence |
| --- | ---: | ---: | ---: |
| aio | 1 | 1 | 1 |
| case | 4 | 2 | 13 |
| case_fan | — | — | 12 |
| cooler_air | 2 | 2 | 5 |
| gpu | 2 | 4 | 2 |
| memory | — | — | 3 |
| motherboard | — | 5 | 2 |
| psu | — | 1 | — |
| **total** | **9** | **15** | **38** |

Plus R4 (5 code keys), R5 (8 true-variant groups), R6 (14 listings, 11 of them already counted in
R1b/R2) and R7 (the 27 ambiguous groups), described below. R3 and R6 are *mechanisms* that cut
across the buckets, so their counts overlap the table.

---

## 4. Root causes, fixes and blast radius

### R1 — no-code fall-through: the listing never gets a model code
**9 groups / 19 products.** 4 safe, 5 QA.

`identity.model_code()` falls back to `title_raw` **only for CPU** (line 385–395). Every other
category reads `attributes.model` / `attributes.product_name` and gives up. KSP and Yahav often
publish neither, so the listing gets `None` and can never enter the identity tier — it lands in
`singleton` or on the MPN tier.

Two sub-cases make it worse:
* `generic_model_code()` returns `None` when the compact code is shorter than 4 characters
  (line 360). Real model codes like `A3W`, `C8`, `B4X` are dropped.
* A title-only listing that *does* have a model word still never gets a code because there is no
  fallback outside CPU.

**Fix:** use `title_raw` as the last-resort source in `generic_model_code()` (same pattern the CPU
branch already uses), and lower the minimum length to 3 when the brand is known. Titles need the
same `_MODEL_NOISE`/brand/axis stripping the model row gets.

**Blast radius:** every non-CPU listing without a model row gains a code. Potential pid churn and
new `identity_merge` QA cases. Needs the `identity_merge` fixture count (I2) checked and the
pid-alias path (`_pid_aliases`) exercised, because pids will move.

### R1b — neither side coded, but they are the same product
**15 groups / 30 products.** 11 safe, 4 QA.

The pure form of R1: no code on either side, no shared MPN, so no tier can see the pair. Almost
all of these are one vendor listing the same part twice (KSP `277276`/`311451`, both
"ASUS Proart B760-Creator WiFi") or a reviewer-visible truncation (`GV-N507TAORUS` vs
`N507TAORUSIF16GD`).

**Fix:** none of its own — R1 + R3 recover most of it. The same-vendor subset should additionally
be caught by a "same vendor, same title fingerprint, same spec tags" check, which is what the
existing `packaging_conflict` machinery already does for CPU (matching.py §6) but only for CPU.

**Blast radius:** if the vendor-twins check is generalised beyond CPU, keep the existing
corroboration rule (identical price **and** identical tag fingerprint minus packaging) so genuine
Box/Tray twins stay apart (D1).

### R2 — model-code string divergence
**38 groups / 81 products.** 20 safe, 18 QA.

Both sides get a code, but the codes differ by a word that does not change the part:
`hydro-x-**series**-...`, `c8-**constellation-series**-...`, `...-**case**-black`,
`...-**tower**-black`, `...-**fan**-...`, `neo-prizm-t3-120` vs `neo-prizm-t3-120-**fan**`.
`_MODEL_NOISE` is only `{the, and, with, for, of, edition, version, new, gen}`.

**Fix:** extend the noise set with body/series words (`series`, `case`, `tower`, `chassis`,
`fan`, `cooler`, `aio`, `liquid`, `kit`, `pack`, `retail`, `cpu`, `mid`, `full`, `micro`, `atx`,
`matx`, `itx`) and, more importantly, **drop every token that is the value of a variant axis**
(colour, lighting, quantity, size) from the code. That is safe by construction: `variant_subgroups`
already re-splits the group on those axes and `identity_pid_suffix` puts the value back into the
pid, so black and white still end up as two products — but they now share a code and are compared
at all.

**Blast radius:** the biggest of the fixes. Every non-CPU code changes shape, so pids and site
URLs move. Gate on `scripts/check_identity_merge.py` (I1/I2/I3 fixtures) plus a per-category delta
run; expect `identity_merge` cases to rise.

### R3 — the vendor SKU is never used as a part-number bridge
**11 of the 62 groups** have a SKU on one side that *is* the other side's MPN or SKU
(`tms:A3W` / MPN `A3W`, `tms:0-761345-77772-8` / EAN `0-761345-77772-8`,
`model:b4-mesh-case-black` sku `B4X` / MPN `B4X`).

`part_number_key`/`mpn_part_key` are shared by the MPN tiers, but the identity tier only looks at
`mpn`; a `vendor_sku` that is literally a maker code is ignored.

**Fix:** when a SKU is *manufacturer-shaped* (letters + digits, length ≥ 4, not a bare number, not
`C####`/`ULTRA…`), feed it into the same `mpn_part_key` bucket as a real MPN. Never for numeric
retailer ids.

**Blast radius:** 11 groups move immediately, mostly high-confidence. Risk is a vendor that uses
short alphanumeric SKUs that collide across brands — restrict the bridge to same category + same
brand, which the identity bucket already guarantees.

### R4 — verified maker code present, merge still blocked
**5 code keys / 10 products, all Gigabyte motherboards.** Separate from the 62.

Example: `x870maoruselitewifi7` and `x870maoruselitewifi7ice` both point at the same 1pc/tms
product, while Yahav's plain `X870M-AORUS-ELITE-WIFI7` is its own product. Tier 5c refuses
because the surviving pid carries **two** verified codes (base + ICE), and its guard is
`if len(_codes) > 1: continue`.

Two independent defects produce this:
1. **`_MFR_PREFIXES` is missing Gigabyte board prefixes.** `part_number_class()` treats a maker PN
   as `vendor` when it equals the vendor SKU and does not start with a known prefix. `GX…`/`GZ…`
   are not in the tuple (`GV`, `GP`, `GA` are), so `GX870MAORUSELITEWIFI7` **and**
   `GX870MAORUSELITEWIFI7I` both classify as `vendor`. `part_number_subgroups()` then sees no
   manufacturer clusters and never splits base from ICE — the over-merge happens first, and 5c is
   right to refuse afterwards.
2. **`mpn_affix_related()` treats any suffix as truncation.** `…WIFI7` vs `…WIFI7I` (ICE),
   `…WIFI7` vs `…WIFI7P` (Plus) and `…WIFI7` vs `…WIFI7PC` (bundle) all count as "same code at a
   different truncation level". Two of those three are wrong.

**Fix:** add `GX`, `GZ`, `GB` (and the other board prefixes in use) to `_MFR_PREFIXES`; then make
the affix rule asymmetric — a *shorter* code that is a prefix of a longer one is truncation, but a
one-character tail (`I`, `W`, `P`, `L`) on an otherwise complete code is a variant suffix and must
split. `-PC` is handled by R6 instead.

**Blast radius:** this one **splits existing products**, so it is the opposite direction from the
other fixes. The X870M/ICE split changes pids for 6 listings and needs a redirect/alias story. Do
it behind QA, after R6, and re-run 5c afterwards to pick up the Yahav rows.

### R5 — two different manufacturer PNs = a genuine variant
**8 groups in the candidate set, plus 12 `variant_conflict` groups elsewhere. No merge.**

Examples that must stay apart: `ROGRYUOIV360ARGB` vs `ROGRYUOIV360ARGBWHITEEDITION`,
`F400ARGB` vs `F400ARGBW`, `TRPA120SEARGB` vs `TRPA120SEARGBWHITE`,
`GAOG432GB3200C16BDC` vs `GAOSG432GB3200C16BDC` (GeIL non-RGB vs RGB),
`90YV0MP3-M0NA00` vs `90YV0MP2-M0NA00` (two ASUS Dual 5060 Ti SKUs).
These are the matcher's own rule (two maker PNs ⇒ two variants) working correctly.

**Fix:** none. Optionally surface them on the QA page so a human can confirm the variant axis
(several are colour/lighting variants of an axis the category *does* model, but one side's axis
value is unknown, so no `variant_conflict` case is emitted).

**Blast radius:** zero if left alone; merging any of them would be a regression.

### R6 — `-PC` is a bundle marker, not a manufacturer PN
**14 listings, all Yahav, all with `מבצע ברכישת מחשב שלם בלבד` in the title; 11 of them currently
split a product in two.**

`ACFRE00188A-PC`, `100-000001973-PC`, `TUF-RTX5060-O8G-GAMING-PC`, `KF556C36BBEAK2-128-PC`,
`CT2000T710SSD8-PC`, `BK043-PC`, `TL-C12CG-S-PC`, `GeForce-…-PC`, `ROG-ASTRAL-…-PC`,
`VCG5060T8DFXPB1-O-PC`, `VCG5070T16TFXXPB1-O-PC`, `B850M-MAX-GAMING-WIFI-PC`,
`TUF-GAMING-B650E-E-GAMING-WIFI-PC`, `49369-PC`.

`bundle_only`/`new_pc_deal` are only ever set from a **TMS** `category_guess` suffix
(`matching.py:949–974`). Yahav prints the deal in the Hebrew title instead, so the flag is
`False`/`None` on all 14 offers and the `-PC` suffix survives into the MPN.

**Fix:** strip a trailing `-PC` from the MPN before `mpn_part_key`, and set `bundle_only`/
`new_pc_deal` from the title phrase (`מבצע` + `מחשב שלם`) for any vendor. Keep the flag on the
offer so the UI can still mark it a bundle deal.

**Blast radius:** 11 products collapse into 11 existing ones; 14 listings gain the flag. Very low
risk, entirely mechanical. One caution: `model:cpu:9850x3d-tray` holds `100-000001973-PC`, so
stripping the suffix would join a bundle listing to whatever carries `100-000001973` — verify that
pair is not a Box/Tray conflict before shipping (D1).

### R7 — variant words the axes do not model
**27 groups / 60 products. QA only.**

Three recurring shapes:
* **Quantity** (12 case_fan groups): single fan vs 3-pack. `model:case_fan:proart-pf120-pwm-120mm-black`
  (`471091`) vs `...-3-120mm-3-black` (`471121`); `ZMIF120` vs `ZMIF120A3` is a real MPN
  difference and must not merge.
* **Lighting** (A70 ARGB vs A70: EANs `…22293` vs `…22279`; Antec `C8` vs `C8ARGBBLACK`).
* **Colour/edition as a letter suffix** the axes do not read (`…WIFI7` vs `…WIFI7 W`,
  `X870M … WIFI7` vs `… WIFI7 ICE`).

**Fix:** none inside this scope — adding axes (`edition`, `pack_count` outside case_fan, `ice`) or
colour-word extraction from titles is a widening of the identity model and needs its own decision.
Everything here should be **`variant_conflict` QA cases, not merges**.

---

## 5. Worked examples

All listing keys and pids are verbatim from the current catalog.

### E1 — R1: Corsair Titan 360 RX LCD White (AIO)
```
aio:ksp:ksp-360189                       singleton  ksp:360189            749
model:aio:icue-link-titan-360-rx-lcd-360mm-white
                                         identity   1pc:175128    CW-9061026-WW  1370
                                                    ivory:150454  CW-9061026-WW   749
                                                    tms:CW-9061026-WW            983
                                                    yahav:10342                  950
```
KSP has no model row and no MPN; its title says the same product. Price spread 749–1370 today.
**Fix:** R1 title fallback. Safe (all four other shops agree on one MPN).

### E2 — R2: Corsair Hydro X XH505i RX 360 Black (AIO)
```
model:aio:hydro-x-icue-link-xh505i-rx-360-360mm-black
     identity  1pc:218200  CX-9070018-WW  2531
model:aio:hydro-x-series-icue-link-xh505i-rx-360-360mm-black
     identity  ksp:430613  (no MPN)       2099
```
The only difference is the word `series` in Corsair's own name. **Fix:** R2 noise list. Safe.

### E3 — R1 + R3: Lian Li A3 White (case)
```
case:tms:tms-a3w          singleton  tms:A3W    (no MPN)  300
model:case:a3-case-white  identity   1pc:180225  MPN A3W  381
                                     yahav:10415 MPN A3W  345
```
The TMS SKU *is* the manufacturer PN (`A3W`), but the code is 3 chars so `generic_model_code`
returns `None`, and the identity/MPN tiers never look at SKUs. Same shape for A3 Black
(`tms:A3X` vs `model:case:a3-case-black`). **Fix:** R1 + R3. High confidence.

### E4 — R2: Antec C8 White (case)
```
model:case:c8-case-c8w-white            identity  1pc:157902  C8W  494
                                                  yahav:9181   C8W  480
model:case:c8-constellation-series-white identity 1pc:167528  —    583
```
Same case, one missing MPN, one extra series word. **Fix:** R2. Note the third product in the same
connected component, `model:case:c8-argb-black` (`C8ARGBBLACK`), is a *genuine* variant — the fix
must not chain through it.

### E5 — R2: Antec NEO Prizm T3 120 ARGB (case fan)
```
model:case_fan:neo-prizm-t3-120-120mm-rgb-black
     identity  1pc:171571  MPN 0-761345-77772-8  69
model:case_fan:neo-prizm-t3-120-fan-120mm-rgb-black
     identity  tms:0-761345-77772-8  MPN None    53
```
Different code slugs (`…-120` vs `…-120-fan`); TMS carries the EAN as its SKU, not as MPN.
**Fix:** R2 (+ R3 would catch it on its own). High confidence.

### E6 — R2: ARCTIC Freezer 36-S A-RGB Black (cooler)
```
model:cooler_air:freezer-36-s-a-black                        identity  ksp:491586     120
model:cooler_air:freezer-36-s-a-rgb-black-156mm-120mm-black  identity  ivory:167728  ACFRE00198A  120
```
Same price, same product; the code differs by `a-rgb` vs `a-` plus the dimension words.
**Fix:** R2. Safe.

### E7 — R6: Kingston Fury Beast 128GB kit (memory)
```
model:memory:fury-beast-…-rgb     identity  yahav:11125  KF556C36BBEAK2-128     9200
model:memory:fury-beast-…-rgb-2   identity  yahav:11552  KF556C36BBEAK2-128-PC  9100
```
Both Yahav, both a full-PC deal, 100 NIS apart. Currently flagged `variant_conflict` because the
two MPNs differ. **Fix:** R6 — same part, one is the bundle listing. Safe, but keep the flag.

### E8 — R6 + R1b: be quiet! Pure Rock 3 PRO LX (cooler)
```
model:cooler_air:pure-rock-pro-3-lx-155mm-120mm-black
     identity  1pc:207595 BK043 245 | ivory:143819 BK043 385 | tms:BK043 229 | yahav:10760 BK043 320
mpn:cooler_air:bk043pc
     mpn       yahav:11438 BK043-PC 300   (title: "מבצע ברכישת מחשב שלם בלבד")
```
A four-shop product plus a fifth Yahav row that is the same cooler sold as a build bundle.
**Fix:** R6. Safe after the flag lands.

### E9 — R4: Gigabyte X870M Aorus Elite WIFI7 (motherboard)
```
mpn:motherboard:x870maoruselitewifi7        mpn       yahav:11756  X870M-AORUS-ELITE-WIFI7  1260
model:motherboard:x870m-aorus-elite-wifi7-microatx
     identity  1pc:206281 GX870MAORUSELITEWIFI7   1296
               1pc:216437 GX870MAORUSELITEWIFI7I  1296   (ICE, white)
               tms:GX870MAORUSELITEWIFI7         1257
               tms:GX870MAORUSELITEWIFI7I        1257   (ICE, white)
```
This is **two** real products (black and ICE) plus a Yahav row for the black one. The 1pc/tms
product over-merged black with ICE because `GX…` is not a known maker prefix, which in turn
blocked tier 5c from pulling Yahav in. **Fix:** R4. QA only, and it splits a product — the only
fix here that needs an alias/redirect.

### E10 — R1b + R3: Gigabyte RTX 5070 Ti INFINITY (GPU)
```
mpn:gpu:n507taorus        mpn  1pc:221453  GV-N507TAORUS  6856
                              (title: "Gigabyte RTX 5070 Ti INFINITY GV-N507TAORUS IF-16GD")
mpn:gpu:n507taorusif16gd  mpn  tms:N507TAORUSIF16GD  6716
```
1pc truncated the MPN; its own title still prints `IF-16GD`. Same for
`R9070XTGAMINGOC16` vs `R9070XTGAMINGOC16GD`, where the longer product already lists the shorter
code as a second SKU. **Fix:** R3 (SKU/affix bridge), with the R4 affix-asymmetry rule so the
`-GD` tail (a real packaging/region suffix) still merges. Medium confidence → QA-flag it.

---

## 6. QA-only cases (do not auto-merge)

| Case | Why |
| --- | --- |
| 12 case-fan quantity groups (single vs 3-pack, `471091`/`471121`, `419669`/`419677`, `468533`/`468693`) | `quantity` is an axis, but the axis value is missing on one side and the code differs; a wrong merge destroys the pack size. |
| `ZMIF120` vs `ZMIF120A3`, `F400ARGB`/`F400ARGBW`, `TRPA120SEARGB`/`…WHITE`, `ROGRYUOIV360ARGB`/`…WHITEEDITION`, GeIL `GAOG…`/`GAOSG…` | Two manufacturer PNs = two variants. Keep apart. |
| Antec `C8` vs `C8ARGBBLACK`, Thermalright `A70` vs `A70 ARGB` (EAN `…22279`/`…22293`) | Lighting variants with different barcodes. |
| KSP B760-F `241505`/`458339`, B760-G `277270`/`506598`, ProArt `277276`/`311451` | Same shop, same title, different SKU and price — could be a re-list or a silent revision. Human call. |
| ASUS `TUF Gaming B850M-Plus WIFI7` (`435410`) vs `…Plus W WIFI7` (`435425`) | One letter; possible white edition or a typo re-list. |
| Gigabyte `Z890 Aorus Elite WIFI7` vs `… Plus` (`GZ890AORUSELITEWIFI7` + `…P` in one product) | Currently over-merged by the affix rule. Confirm whether "Plus" is a separate SKU before splitting. |
| All 12 identity-bucket `variant_conflict` pairs (memory 2, motherboard 5, storage 4, case 1) | Already public QA; MPNs differ, so the conservative outcome (two products) is correct until someone confirms. |
| `model:cpu:9850x3d-tray` holding a `-PC` MPN | D1 packaging rule + bundle flag interaction; check before R6 touches CPU. |

---

## 7. Suggested order (after sign-off)

1. **R6 bundle `-PC`** — 14 listings, 11 merges, mechanical, no code-shape change.
2. **R1 title fallback + length-3 codes** — recovers the KSP/Yahav no-code rows; pids move.
3. **R2 noise/axis-token stripping** — largest win (38 groups) but largest pid churn; gate on the
   three identity fixtures and a per-category delta.
4. **R3 manufacturer-shaped SKU bridge** — 11 groups, all in-bucket.
5. **R4 `_MFR_PREFIXES` + affix asymmetry** — splits base/ICE/Plus, then re-run 5c. QA + redirects.
6. **R7 axes** — out of scope; keep everything as `variant_conflict` QA cases.

Expected result if 1–4 land and the 27 ambiguous groups stay QA-only:
roughly **55 of the 68 removable rows** disappear, `identity_merge` cases rise (they are meant
to — D3), and the remaining ~13 sit on the QA page with a human decision.

### Verification for whatever gets implemented

* `python scripts/check_identity_merge.py` — I1 1834 / I2 3699 / I3 10 / CPU 215.
* `python scripts/report_identity_delta.py` — per-category product/listing/QA deltas.
* Re-run the three scans in this document; the 10 examples above must collapse (or split, for E9).
* `npm --prefix site run build`.

---

## 8. Caveats

* The 62 groups are what a token-equality heuristic can see. Duplicates that add an unknown word
  (a revision code, a local SKU, a Hebrew-only phrase) are invisible to it.
* Connected components chain: one genuine variant can pull a duplicate group into a larger
  component (E4/C8, the A70 pair). Every proposed merge must be checked pair-wise, not
  component-wise.
* `R1b` "no code either side" often means *no model row and no MPN* — those listings are also the
  ones most likely to be mis-categorised, so their absence from another category's duplicates is
  not evidence.
* No decision was taken on `docs/merge-identity-plan.md` D1–D3; this report only quantifies what
  is left, and flags the two places (R5, R7) where merging would be a regression.
