# Audit lane 03: misfiled products

- Date: 2026-11-10
- Snapshot: git HEAD `1e353d17` (re-pinned; see Method). `data/catalog.json` `generated_at` = `2026-11-09T22:13:04.288166+00:00`
- Products: 4383. Listings: 7095.
- Machine-readable instances: `docs/audits/2026-11-10/03-misfiled.jsonl` (31 rows, one per product, keyed by finding id)

## Summary

| ID | Sev | Where it sits | Should be | Products | Silent or flagged | Confidence | Cause |
|---|---|---|---|---|---|---|---|
| F1 | S1 | `other` | `aio` | 5 | silent | high | Classifier misses "קירור מים" (water cooling) |
| F2 | S1 | `cooler_air` | `aio` | 4 | silent (site shows "Air") | high | Generic "קירור למעבד" title, no AIO word; same MPN is an AIO at another vendor |
| F3 | S1 | `accessories` | `case_fan` | 4 | silent | high | Frame rule meant for Phanteks Halo frames catches Corsair RX360 II kits |
| F4 | S2 | `case` | `accessories` | 6 | 2 flagged (duplicate_vendor / identity_merge, both in review queue), 4 silent | high | Spare glass panel title; no panel rule for case |
| F5 | S2 | `case` | `other` | 2 | silent | high | Supermicro complete server; no barebone/server rule |
| F12 | S2 | `cpu` (spec, not category) | `includes_cooler=False` | 1 | silent | medium | `derived:cpu.lineup_box_cooler` overrides vendor title |
| F6 | S3 | `case` | `accessories` | 3 | silent | high | O11D EVO "Kit" titles (GPU upright / front mesh) |
| F8 | S3 | `aio` | `accessories` | 2 | silent | high | Corsair NAUTILUS RS "מודול מסך LCD" (LCD screen module) |
| F9 | S3 | `case_fan` | `accessories` | 1 | silent | high | Noctua LGA1700 "תושבת מתאם" (mounting bracket) |
| F10 | S3 | `case_fan` | `accessories` | 1 | silent | high | Corsair Lighting Node PRO controller, sold alone |
| F11 | S3 | `storage` | `accessories` | 1 | silent | high | SilverStone FS204-US "כלוב כוננים" (drive cage) |
| F13 | S3 | `aio` | `accessories` | 2 | silent | high | ASUS ROG Ryujin III "בלוק מעבד ... Custom Loop" (CPU water block) |

Totals: 3 S1 findings (13 products), 2 S2 category findings (8 products: F4, F5) plus F12 (1 spec-level product, S2), 6 S3 findings (10 products: F6, F8–F11, F13).

Existing gate: `scripts/check_categories.py` passes 43/43 and covers none of F1–F12.

## Method

Every count comes from a saved script in `tmp/data-audit/03-misfiled/`. Read-only against `data/`, `scraper/`, `scripts/`. Python run as `python -X utf8 -P`.

- `s1_other_acc.py`: dump every product in `other` (24) and `accessories` (73) with listing titles.
- `s0_shape.py`, `s0b_site_shape.py`: spec keys, `cooler_type` values, site file shapes.
- `s2_titles.py`, `s2b_review.py`: title keyword scan across all categories. Too noisy on its own (compatibility mentions dominate), used only to find candidates.
- `s3_strong.py`, `s3b_show.py`: narrow "is-a" phrase rules (non-part, enclosure, SO-DIMM, panel, PSU cable, GPU holder, barebone, AIO/air liquid words, cpu-with-cooler).
- `s4_specs_offers.py`, `s4b_show.py`: spec contradictions (AIO without radiator, cooler_air with radiator, case_fan with radiator), offer `category_normalized` vs product category, same-MPN-across-category, site `cooler_type` vs category.
- `s5_mpn_detail.py`: vendor titles for the shared MPNs, Nautilus rows, Ryzen 7900.
- `s6_probe.py`: calls the real classifier (`canonical_category`, `title_category`, `_hebrew_category_hint`) on the exact titles. Used to confirm the cause of each misfile.
- `s7_own_noun.py`: per product, does any listing title name its own category? Products with none are candidates.
- `s8_counts.py`, `s8b_show.py`: per-finding groups and counts. `s9_jsonl.py`: writes the JSONL and `s9_summary.json`.
- `check_categories_out.txt`: `[categories] pass - 43 titles`.

Causes were traced in code: `scraper/matching.py` (`_HEBREW_LIQUID_RE`, `_FRAME_ACCESSORY_RE` and the frame rule near line 728, `canonical_category`, `_cooling_fallback`), `scraper/specs/derive.py` (`_box_cooler`, `cpu.lineup_box_cooler`), `scraper/spiders/ksp.py` (`_refine_guess`).

**Snapshot change:** I pinned HEAD at `1534928e`. The re-check found `1e353d17` (six commits: CI split, Worker hardening, image-fetch limits). I checked the change set with `git diff --stat`: none of the classifier or derive files changed (`matching.py`, `derive.py`, `ksp.py`, `check_categories.py`), and `generated_at` is unchanged. The findings below therefore hold on `1e353d17`. Re-pinned on that basis.

## Findings

Each finding has a one-line fix direction. Examples are the first rows of the JSONL for that id; all rows are in the JSONL.

### S1

**F1. TMS water-cooling AIOs filed as `other` (5 products, silent)**
- Expected: `aio`. Source: the same MPNs are AIO products elsewhere (1PC and Yahav list them as AIOs; see `s4_out.json` `same_mpn_multi_category`).
- Field: `category`. Observed: `other`.
- Examples:
  - `other:tms:tms-mlx-d36m-a18p2-r1`, listing `tms:MLX-D36M-A18P2-R1`, vendor tms: "קירור מים למעבד CoolerMaster ML360 Illusion"
  - `other:tms:tms-mly-d24m-a20pa-r1`, listing `tms:MLY-D24M-A20PA-R1`, vendor tms: "קירור מים למעבד CoolerMaster ML240P Mirage"
  - `other:tms:tms-mly-d24m-a23pz-r1`, listing `tms:MLY-D24M-A23PZ-R1`, vendor tms: "קירור מים למעבד CoolerMaster PL240 Flux"
- Cause (traced, probe confirmed): `_HEBREW_LIQUID_RE` has no "קירור מים"; `ML360`, `PL240`, `ML240P` fail the `\b360\b` boundary check. Title category returns None, so the TMS guess `other` stands.
- Fix direction: add "קירור מים" to the Hebrew liquid hint and let the `ML/PL` + size model families match the AIO path.

**F2. 1PC Cooler Master 360mm AIO MPNs filed as `cooler_air` (4 products, silent; site shows "Air")**
- Expected: `aio`. Source: Yahav lists MLW-D36M-A18PA-R1, MLW-D36M-A18PA-RW, MLX-D36M-A18PA-RD as "קירור נוזלי" AIOs (`s5_mpn_detail.py`). For ELW-D36M-A21DA-R1, the local plonter raw snapshots (`data/raw/*/plonter.jsonl`, 2026-08-22 onward, no network) title it "360mm ARGB Liquid Cooler - Elite Liquid 360" with category_guess "Liquid Cooling".
- Field: `category` and site `cooler_type`. Observed: `cooler_air`, site `cooler_type` = `Air`.
- Examples:
  - `model:cooler_air:a18pa-d36m-mlw-r1`, listing `1pc:222812`, vendor 1pc: "קירור למעבד COOLER MASTER MLW-D36M-A18PA-R1"
  - `model:cooler_air:a18pa-d36m-mlw-rw`, listing `1pc:222815`, vendor 1pc: "קירור למעבד COOLER MASTER MLW-D36M-A18PA-RW"
  - `model:cooler_air:a18pa-d36m-mlx-rd`, listing `1pc:222813`, vendor 1pc: "קירור למעבד COOLER MASTER MLX-D36M-A18PA-RD"
- Cause (probe confirmed): the 1PC title says only "קירור למעבד" (generic CPU cooler); no AIO word, so `cooler_air` wins.
- Example (4th product): `model:cooler_air:a21da-d36m-elw-r1`, listing `1pc:222811`, vendor 1pc: "קירור למעבד COOLER MASTER ELW-D36M-A21DA-R1".
- Fix direction: when an MPN is already an AIO elsewhere, do not let a generic title vote `cooler_air`. Cross-vendor MPN evidence should decide the category.

**F3. Corsair RX360 II Unified Frame fan kits filed as `accessories` (4 products, silent)**
- Expected: `case_fan` (these are fan kits with RX360 radiator frames, not accessories).
- Field: `category`. Observed: `accessories`.
- Examples:
  - `mpn:accessories:co9051059ww`, listing `1pc:221519`: "ערכת מאווררים Corsair iCUE LINK RX360 II Unified Frame RGB PWM CO-9051059-WW"
  - `mpn:accessories:co9051060ww`, listing `1pc:221520`: "ערכת מאווררים Corsair iCUE LINK RX360 II Unified Frame RGB PWM White CO-9051060-WW"
  - `mpn:accessories:co9051061ww`, listing `1pc:221521`: "יחידת מאווררים Corsair iCUE LINK RX360 II Unified Frame RGB PWM Expansion Black CO-9051061"
- Cause (traced): `matching.py` ~730–736: `_FRAME_ACCESSORY_RE` ("frame") + `_FAN_LED_RE` ("RGB") returns `cooler_accessory`. The rule was written for Phanteks Halo fan frames.
- Fix direction: exempt titles with fan-size words and "fan"/"מאוורר"/"ערכת מאווררים" from the frame rule, or require the frame word to be a fan-frame phrase.

### S2

**F4. Spare glass panels filed as `case` (6 products; 2 flagged, 4 silent)**
- Expected: `accessories`. Field: `category`. Observed: `case`.
- Examples:
  - `model:case:680x-crystal-black`, listing `yahav:9360`: "זכוכית למארז חברת Corsair דגם Crystal 680X Tempered Glass Only צבע שחור - פאנל זכוכית בלבד"
  - `model:case:ax61-black`, listing `yahav:9347`: "זכוכית למארז חברת Antec מותאמת לדגם Antec AX61 Tempered Glass Only צבע שחור - פאנל זכוכית בלבד"
  - `model:case:1-ft-performance-black-midtower`, listing `yahav:9358` (flagged `qa:duplicate_vendor`, in review queue): "פאנל זכוכית צד שמאל למארז חברת Antec מותאמת לדגם Performance 1 FT צבע שחור - פאנל בלבד"
- Cause (probe confirmed): "Tempered Glass Only" / "פאנל בלבד" gets `case_fan` from the title, and case-peel only applies to accessory categories, so the case vendor guess stays.
- Fix direction: add a glass-panel-only rule (title says "Only" / "בלבד" with panel/glass words) that maps to `accessories`. Do not catch "ללא ספק" (without PSU) rows, which are real cases.

**F5. Supermicro complete servers filed as `case` (2 products, silent)**
- Expected: `other`. Field: `category`. Observed: `case`.
- Examples:
  - `model:case:420gp-barebone-gpu-sys-tnr`, listing `tms:SYS-420GP-TNR`: "Supermicro SYS-420GP-TNR GPU Barebone"
  - `model:case:740gp-superserver-sys-tnrt`, listing `tms:SYS-740GP-TNRT`: "SuperMicro SuperServer SYS-740GP-TNRT"
- Cause (probe confirmed): no barebone or server rule; vendor guess `case` stands. Rackmount chassis (SilverStone RM44/RM45/RM51/RM52, Chenbro SR115) are `case` by design (schema has `rackmount`) and are NOT in this finding.
- Fix direction: add a barebone/SuperServer/"SYS-" rule that maps complete servers to `other`.

**F12. Ryzen 9 7900 Box: `includes_cooler=True` against vendor title (1 product, medium confidence)**
- Expected: `includes_cooler=False`. Source: KSP title "מעבד AMD Ryzen 9 7900 3.7GHz AM5 - Box - ללא קירור באריזה" ("no cooler in the box"). The vendor says the box has no cooler, so the spec should say no. Field: `specs.includes_cooler`. Observed: `True`, source `derived:cpu.lineup_box_cooler`.
- Example: `model:cpu:7900`, listing `ksp:472524`, vendor ksp.
- Cause (traced): `derive.py` `_box_cooler` (~283) and `cpu.lineup_box_cooler` (~452) apply a lineup default and ignore the vendor's explicit negation.
- Medium confidence: I did not check the manufacturer spec offline (no network). The vendor title is explicit; the derived value is a default.
- Fix direction: when a vendor title says "ללא קירור" (no cooler) or "without cooler", the explicit title wins over the lineup default.

### S3

**F6. Lian Li O11D EVO kits filed as `case` (3 products, silent)**
- Expected: `accessories`. Field: `category`. Observed: `case`.
- Examples:
  - `model:case:011de-2x-evo-gpu-o11d-upright-black`, listing `1pc:125064`: "LIAN-LI O11D EVO Upright GPU Black Kit 011DE-2X"
  - `model:case:011de-4x-evo-front-mesh-o11d-black`, listing `1pc:125062`: "LIAN-LI O11D EVO Front Mesh Black Kit 011DE-4X"
  - `model:case:011de-evo-front-mesh-o11d-white`, listing `1pc:125061`: "LIAN-LI O11D EVO Front Mesh White Kit 011DE-4W"
- Fix direction: a "Kit" with a case model name and no "case" word belongs in `accessories`.

**F13. ASUS ROG Ryujin III Custom Loop water blocks filed as `aio` (2 products, silent)**
- Expected: `accessories`. Field: `category`. Observed: `aio`. Source: owner confirmed these are standalone CPU water blocks for custom loops, not radiator AIOs.
- Examples:
  - `model:aio:custom-iii-loop-rog-ryujin-black`, listing `ksp:327344`: "בלוק מעבד למערכת קירור לולאה מותאמת אישית (Custom Loop) Asus ROG RYUJIN III - צבע שחור"
  - `model:aio:custom-iii-loop-rog-ryujin-white`, listing `ksp:327401`: "בלוק מעבד למערכת קירור לולאה מותאמת אישית (Custom Loop) Asus ROG RYUJIN III - צבע לבן"
- Cause: the AIO regex matches "Ryujin" (a model family name in `AIO_TITLE_RE`), and the title's "Custom Loop" and "בלוק מעבד" words are not checked against it.
- Fix direction: "בלוק מעבד" / "water block" / "custom loop" with no radiator size should map to `accessories`, and "ryujin" should not on its own make an AIO.

**F8. Corsair NAUTILUS RS LCD module filed as `aio` (2 products, silent)**
- Expected: `accessories`. Field: `category`. Observed: `aio`.
- Examples:
  - `model:aio:lcd-nautilus-rs-black`, listing `1pc:218323`: "מודול מסך LCD Corsair NAUTILUS RS בצבע שחור"
  - `model:aio:lcd-nautilus-rs-white`, listing `1pc:218322`: "מודול מסך LCD Corsair NAUTILUS RS בצבע לבן"
- Fix direction: add "מודול מסך"/"LCD module" to the accessory words; the vendor guess `aio` is wrong for a screen.

**F9. Noctua LGA1700 mounting bracket filed as `case_fan` (1 product, silent)**
- Expected: `accessories`. Field: `category`. Observed: `case_fan`.
- Example: `model:case_fan:1700-chromax-lga-black`, listing `yahav:6517`: "תושבת מתאם חברת Noctua לקירורים Noctua ... לתושבת LGA 1700 גרסא Chromax Black שחורה"
- Fix direction: "תושבת" (bracket) and "מתאם" (adapter) with an LGA socket word should map to `accessories`.

**F10. Corsair Lighting Node PRO controller filed as `case_fan` (1 product, silent)**
- Expected: `accessories`. Field: `category`. Observed: `case_fan`.
- Example: `model:case_fan:9011109-cl-ww`, listing `1pc:62184`: "קורסייר לייטינג נוד פרו CL-9011109-WW צבע לבן"
- Note: the 6 Corsair fan kits that include a Lighting Node are correctly `case_fan`. Only the standalone controller is wrong.
- Fix direction: "לייטינג נוד"/"Lighting Node" with no fan words and no kit words should map to `accessories`.

**F11. SilverStone U.2 drive cage filed as `storage` (1 product, silent)**
- Expected: `accessories`. Field: `category`. Observed: `storage`.
- Example: `model:storage:2-4-fs204-u-us-slimsas4isff8654-25`, listing `1pc:212156`: "כלוב כוננים SilverStone FS204-US ל-4 כונני U.2 בגודל 2.5 אינץ'"
- Fix direction: "כלוב כוננים"/"cage" should map to `accessories`, not `storage`.

## Suspicions (not counted as findings)

- **S-3: Zalman Alpha 24 / 36 AIOs with null radiator** (9 AIOs have no `radiator_size_mm` at all). This is a spec gap, not a misfile: the category is right and the radiator field is empty.

## Rejected false positives

- Portable SSDs in `storage` (Samsung T5/T7/T9, Verbatim). Accepted decision; `check_categories.py` covers them.
- Rackmount chassis in `case` (SilverStone RM series, Chenbro SR115, FSP U660). By design: schema has `rackmount`, and these are cases.
- ASUS cases with "לגיימרים" (for gamers) or "ללא ספק" (without PSU). "לגיימרים" is not a laptop signal; "ללא ספק" is not a PSU signal.
- Sunn PSU "כולל כבלים" (includes cables). The PSU is not a cable product.
- Minisforum BD790i / BD895i SE in `motherboard`. Real Mini-ITX boards, not mini PCs.
- Laptop SO-DIMM memory in `memory` (31 products, formerly F7). Owner decision: it is a PC part, so it stays in `memory`. The KSP drop is a scope inconsistency to fix in the scraper, not a misfile.
- Laptops, mini PCs and NAS units in `other` (19 products). Owner decision: `other` is temporary and holds everything that fits no category. Not a misfile.
- Corsair fan kits with a Lighting Node in `case_fan` (6 products). Correct; only the standalone controller (F10) is wrong.
- Site `cooler_type`. AIO = `Water` (270), cooler_air = `Air` (242). Consistent. The 270 flags from `s4_specs_offers.py` were my expected-value bug, not data.
- `category_normalized` vs product category: 0 mismatches across all offers.
- Noctua NA-SFMA1 mounting adapters in `accessories` (KSP). Correct accessory.

## Out-of-lane sightings

- KSP and 1PC disagree on laptop SO-DIMM scope (see rejected). Fix in the scraper, not the category.
- Ryzen box default (F12) is a derive-rule issue, not a category issue.
- `check_categories.py` tests the Hebrew cooling tree but has no cases for F1–F12. Gap list for the gate:
  - "קירור מים" (water cooling) → aio
  - Corsair RX360 II Unified Frame kit → case_fan
  - glass panel "Tempered Glass Only" / "פאנל בלבד" → accessories
  - SYS-420GP / SYS-740GP / SuperServer → other
  - O11D EVO "Kit" → accessories
  - SO-DIMM / למחשב נייד memory → other (or out of scope)
  - "מודול מסך LCD" → accessories
  - "תושבת מתאם" → accessories
  - "לייטינג נוד פרו" standalone → accessories
  - "כלוב כוננים" → accessories
  - "ללא קירור באריזה" → includes_cooler=False

## Not checked / questions

Not checked:
- No network: vendor pages and manufacturer specs were not fetched. F12 needs that for the manufacturer spec.
- `scraper/audit_titles.py` was not run (optional in the plan).
- Scans rely on regexes; they are candidate generators, and each finding was confirmed by reading titles and, for causes, by the classifier probe. A title that uses none of my words could still be a misfile (s7 found only the ones it could name).
- Review queue overlap was checked by listing key, not by reading each queue entry.
- No live site check; site values come from `data/site/cpu_cooler.json`.

Owner answers (recorded):
- Q1. `other` is temporary and holds everything that fits no category. Laptops, mini PCs and NAS units stay there for now. Not findings.
- Q2. Laptop SO-DIMM memory is a PC part and stays in `memory`. Not a finding. KSP's drop is a scraper scope issue to revisit.
- Q3. Owner had no preference. Proposed: when a vendor's generic title conflicts with an MPN that another vendor lists as a specific category, the MPN evidence decides. This is the fix direction for F2. Not implemented; audit only.
- Q4. Asked what "override" meant. Answer: F12 is the case where the vendor title says "ללא קירור באריזה" (no cooler in the box), but the spec says `includes_cooler=True` from a lineup default. The explicit vendor negation should win over the default.
- Q5. ROG Ryujin III Custom Loop is a CPU water block, not a radiator AIO. Now F13 (`accessories`). Source: owner's product description. The owner pointed out I could have checked this myself. I did not, because the audit lane is no-network. I should have said so instead of leaving it as an open question.

- S-1 (ELW-D36M-A21DA-R1): you pointed out the AIO. Local plonter raw data confirms it (see F2). I should have checked the local raw data before calling it open. Now a fourth F2 product.

Out-of-lane sighting: plonter raw snapshots exist under `data/raw/` (37 raw files, dated from 2026-08-22) but plonter is not in `scraper/config` and no plonter listing reaches `data/catalog.json`. Owner to confirm whether plonter is retired or should be wired back in.
