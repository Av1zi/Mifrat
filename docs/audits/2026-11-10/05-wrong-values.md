# Lane 05: wrong, mis-scaled, contradictory or misplaced values

- Lane: 05-wrong-values
- HEAD: `1e353d17` (re-pinned by owner instruction; the brief pinned `1534928e`. The catalog is identical: no file under `scraper/specs/` or `data/catalog.json` changed between the two commits.)
- generated_at: `2026-11-09T22:13:04.288166+00:00`
- Scratch: `tmp/data-audit/05-wrong-values/`

## Summary

| ID | Sev | Conf | Flagged in QA? | Count | What |
|---|---|---|---|---|---|
| F01 | S2 | high | silent | 8 products (lead case + 7), 12 stored listing values | Ivory drive-bay parser reads the `5` of `2.5"` as a bay count |
| F02 | S1 | high | silent | 10 CPUs | `thread_count` below `core_count` or simply wrong on Intel hybrid parts |
| F03 | S1 | high (4) / medium (1) | silent | 5 boards | `chipset` contradicts the title and the vendors |
| F04 | S1 | medium | silent | 1 board | AM5 socket on a B550 (AM4) board |
| F05 | S1 | high | silent | 3 GPUs | `memory_type` = GDDR4 / DDR6, impossible or contradicts title (one from an override) |
| F06 | S2 | high | silent | 2 drives | `capacity_gb` 8000 for 7.68 TB drives |
| F07 | S2 | high | silent | 1 drive | `cache_mb` 512 where title says 256MB |
| F08 | S2 | high | silent | 42 instances | HTML entities in `model` |
| F09 | S2 | medium | silent | 37 boards | E-suffix chipsets folded (B650E→B650, X870E→X870) |
| F10 | S3 | high | silent | 23 instances | Invisible bidi marks in identity and text fields |
| F11 | S3 | high | silent | 32 motherboards | Extra key `pcie_x4_slots` outside schema |
| F12 | S3 | high | n/a | 1 override | `mpn:gpu:100505849` matches no listing |

Silent = no `spec_conflict` case in `data/site/qa.json`.

## Method

1. **Schema pass** (`scan_schema.py`): every spec checked with `validate_fact`, enums, bool types, whitespace, HTML entities, bidi marks, key-set against `schema.field_names`. Output `scan_schema.json`, `numeric_extremes.json`. Result: 0 validation drops, 0 enum drift; the hits are F08, F10, F11.
2. **Top and bottom 1% per numeric field** (`numeric_extremes.json`), read against titles. Values checked against titles are in "Suspicions" when no source confirms them.
3. **Title vs spec** (`scan_title_vs_spec.py`, `title_vs_spec.json`): for 13 field parsers, a product is flagged only if none of its titles agree. Clean for radiator size, fan size, GPU memory, memory cas/speed/total/module, PSU wattage/efficiency, PCIe gen. Hits: storage capacity (3, F06), chipset (25, F03/F09 after fixing my regex).
4. **Drive-bay replay** (`scan_drive_bays.py`, `scan_drive_bays_fixed.py`, `drive_bays.json`, `drive_bays_fix_delta.json`): replay `_emit_drive_bays` on 1,337 detail cells; 117 have a decimal size. Lookbehind variant changes 43 cells and 12 stored Ivory `drive_bays_35` values.
5. **Cross-field contradictions** (`scan_contradictions.py`, `scan_contradictions.json`): C1 threads<cores (10), C7c socket/memory (96, of which 95 are LGA1700/DDR5 false positives), C9 case cooler height <60 (5, rejected).
6. **Attribute conflicts vs winning spec** (`scan_conflicts.py`, `view_conflicts.py`, `conflicts.json`, `conflicts_view.txt`): 355 rows across schema fields. Used to confirm which vendor is right in F02, F03, F06, F07.
7. **Reference-tier audit** (`scripts/audit_reference_matches.py` → `ref.json`): 39 reference rows flagged (fuzzy+anchor 17, exact-name 10, identity+anchor 12; by category aio 5, case_fan 12, cpu 4, motherboard 6, psu 11, storage 1). Only the cpu and motherboard rows were checked against titles; the rest are not drilled.
8. **Overrides** (`data/specs/overrides.json`): 3 `mpn:` keys, each checked against the product it resolves to (`verify_batch.py`).
9. **Title audit** (`scraper/audit_titles.py` → `audit_titles.txt`): 62 duplicate_name, 79 too_long, 6 too_short, 3 upper_ti, 1 series_word. Coarse; not drilled (see Not checked).

Cause tags: **traced** = followed the code or data path to the source; **unverified** = not confirmed.

## Findings

### F01 (S2, high): Ivory drive-bay parser reads "5" from `2.5"`
- Lead: `case:lian-li:o11-dynamic-mini-v2-white`, field `attribute_conflicts.drive_bays_35` = `[5, 2]`. Product spec is **2** (correct; 1pc and tms both say 2). The wrong value is the Ivory listing `ivory:147541` (`attributes.drive_bays_35` = 5).
- Evidence: Ivory row `מקום לכוננים` = `• 2 כונני SSD (2.5") או HDD (3.5") בכלוב הכוננים • 2 כונני SSD (2.5") מאחורי לוח האם`. Only two 3.5" bays exist. Replay gives 5 (`scan_drive_bays.py`).
- Stored Ivory values that the bug produced and the fix changes: `ivory:146303` 5→1, `ivory:147538` 5→1, `ivory:166168` 5→2, `ivory:167170` 5→1 (12 in all, `drive_bays_fix_delta.json`).
- Other products carrying the wrong 5 in conflicts: `model:case:dynamic-o11-v2-black`, `model:case:4500x-frame-rs-black`, `model:case:m-o11-vision-black` (16 conflict rows, 8 products).
- Expected: 2 for the lead (source: 1pc and tms detail rows, `attributes.drive_bays_35`).
- Cause: **traced**. `scraper/specs/resolvers/vendor_struct.py` `_emit_drive_bays` (line ~703–718): `(\d{1,2})` before `3\.5` takes the trailing `5` of `2.5`. Mapped via `DRIVE_BAYS` in `scraper/specs/labels.py` (line 71, 789).
- Fix direction: add a `(?<![\d.])` lookbehind before the count, then rerun the Ivory bay replay.
- Confidence high. Silent (not in QA).

### F02 (S1, high): thread_count wrong on Intel hybrid CPUs
- `model:cpu:14600k` thread_count 12 (source: reference). Cores 14. 1pc row `1pc:152181` says 20 threads.
- `model:cpu:14500` 12 (reference), `model:cpu:14600kf` 12 (reference), `model:cpu:245kf` 6 (reference), `model:cpu:265kf` 8 (reference).
- `model:cpu:225-tray` 6 (vendor; 1pc `1pc:189653` and tms `tms:C225T` both print 6), cores 10. `model:cpu:225f-tray` 6 (vendor), cores 10.
- `model:cpu:245-tray` 6 (vendor), cores 14. `model:cpu:265-tray` 8 (vendor), cores 20. `model:cpu:285-tray` 8 (tms `tms:C285T`), cores 24.
- Expected: threads ≥ cores. For 14600K, 20 is confirmed by the 1pc row. For the Ultra 5/7/9 parts the expected value (threads = cores, since these have no SMT) is from Intel's published spec and was **not** confirmed in this run.
- Cause: 14600K and the 245KF/265KF/14500/14600KF values come from the reference tier. The Ultra tray values come from vendor rows, so the vendors are the source of the error. Partly traced.
- Fix direction: check how the reference tier stores thread count for hybrid CPUs; reject thread_count<core_count in the merge.
- Confidence high. Silent.

### F03 (S1, high for 4 boards, medium for 1): chipset contradicts title and vendors
- `model:motherboard:aorus-master-x3d-x870e-atx` chipset X670, source vendor; title `Gigabyte X870E AORUS MASTER X3D`; tms `GX870EAORUSMASTERX3D` says X870E; 1pc `1pc:216436` says X670. Expected X870E (title plus tms).
- `model:motherboard:eagle-wifi7-x870e-atx` chipset X670, vendor; title `Gigabyte X870E Eagle WiFi7`. Expected X870E.
- `model:motherboard:ai-aorus-top-x3d-x870e-xtreme-atx` chipset X870 (vendor); title and tms say X870E. Expected X870E.
- `model:motherboard:aorus-pro-x3d-x870e-atx` chipset X870 (vendor); title, tms `tms:GX870EAORUSPROX3D` and yahav say X870E. Expected X870E.
- `model:motherboard:p-prime-wifi-x670-atx` chipset X670E, source **reference**; both vendors (`1pc:126955`, `tms:90MB1BV0-M0EAY0`) and the title say X670. Expected X670 (vendor agreement). This contradicts 2+ vendors at the top tier.
- `model:motherboard:b450m-gaming-wifi-microatx` chipset B550, vendor; tms `tms:MS-B450M-GAMING-WIFI` says B450, title says B450M. 1pc says B550. Expected B450. Listed in `attribute_conflicts`, not in QA.
- `model:motherboard:h410m-s2h-v3-microatx` chipset H510, source catalog; both vendors (`1pc:206132`, `tms:GH410MS2HV3`) say H410. Expected H410.
- `model:motherboard:gh410ms2hv2-h410m-s2h-v2-microatx` chipset H470, source catalog; title and both vendors say H410M. Expected H410 (vendor titles agree).
- Cause: vendor-provided chipset rows (B450, X870E) plus catalog/reference resolution for the H410 and P-Prime rows. Partly traced; the "X670 for X870E" rows come from the vendor row picked by the winner rule.
- Fix direction: when a title token and ≥2 vendors agree on a chipset, do not let a single vendor or the reference override it.
- Confidence high for the B450, H410 and P-Prime rows, medium for the X670/X870 rows. Silent.

### F04 (S1, medium): AM5 socket on a B550 (AM4) board
- `model:motherboard:b550m-k-wifi6e-microatx`: socket AM5, memory_type DDR4, chipset empty. Source for socket: vendor. Titles: `לוח אם Gigabyte B550M K WiFi6E` (×2).
- Expected AM4 (B550 is an AM4 chipset; source: schema `CHIPSET_INFO` `B550` = AM4 with DDR4). Verified against `scraper/specs/schema.py` CHIPSET_INFO; only the socket here is wrong.
- Cause: unverified. Vendor-sourced socket.
- The contradiction scan (C7c) finds this as its only real hit among 96.
- Confidence medium. Silent.

### F05 (S1, high): GPU memory_type impossible or wrong
- `model:gpu:1030-4gd4-geforce-gt-lp-oc-4gb`: memory_type **GDDR4**, source **override** `mpn:gpu:4711377107549` (`data/specs/overrides.json`). Title `כרטיס מסך MSI GeForce® GT 1030 4GD4 LP OC` (4GD4 = DDR4). The override tier beats every source, so the wrong value is locked in.
- `model:gpu:1030-2g-2gl-d4-gt-gv-low-n1030d4-profile-2gb`: memory_type GDDR4, source catalog. Titles `GT 1030 Low Profile D4 2G`, `GT 1030 2GB DDR4`. Expected DDR4.
- `model:gpu:1660ti-192bit-6g-gtx-6gb`: memory_type **DDR6** (does not exist), vendor 1pc. tms says GDDR6. Expected GDDR6.
- Cause: override for 4GD4 traced; catalog rows for the D4 card and the DDR6 value unverified (1pc vendor string).
- Fix direction: correct the override; add a rule rejecting DDR6/DDR7.
- Confidence high. Silent.

### F06 (S2, high): storage capacity 8000 GB for 7.68 TB drives
- `model:storage:d3-s4520-8000gb-sata-25` (Intel D3-S4520) and `model:storage:enterprise-pm893-sed-8000gb-sata-25` (Samsung PM893) both show `capacity_gb` 8000, source vendor (tms). Titles say 7.68TB. Expected 7680. Sibling products of the same drive class show 7680 (WD SN840 7.68TB, `model:storage:dc-enterprise-sn840-ultrastar-wd-7680gb-u2-25`).
- tms detail row `נפח דיסק: 8TB` on `tms:SSDSC2KB076TZ01` is the source of the rounding.
- Cause: traced to the tms detail row, which the merge picks over the title.
- Confidence high. Silent.

### F07 (S2, high): cache 512 MB where title says 256MB
- `model:storage:0gbps-6-barracuda-st20000dm001-20000gb-sata-35` cache_mb 512, source catalog. Title `Seagate ST20000DM001 Barracuda 7200RPM 256MB 20TB`; yahav `yahav:11087` says 256MB. Expected 256.
- Ivory `ivory:173329` says 512; the catalog picks it over yahav.
- Cause: catalog pick, traced via `spec_sources`.
- Confidence high. Silent.

### F08 (S2, high): HTML entities in `model`
- 42 instances in `model` (aio 6, case_fan 36). Examples:
  - `model:aio:240-a24-alpha2-se-240mm-black`: `ALPHA2 SE A24 240 &#39;&#39`
  - `model:aio:240-a24-alpha2-se-240mm-white`: `ALPHA2 SE A24 240 &#39;&#39`
  - `model:aio:360-a36-alpha2-se-360mm-white`: `ALPHA2 SE A36 360 &#39;&#39`
- Expected: `ALPHA2 SE A24 240 ''` decoded, i.e. the quote character (escaped text in the source).
- Cause: unverified. The entities are in the stored text; the source is unverified.
- Confidence high. Silent.

### F09 (S2, medium): E-suffix chipsets folded
- 37 boards (B650E 30, X870E 7) show the base chipset (B650, X870). Example: `model:motherboard:am5-atx-b650e-ddr5-displayport-e-gaming-gaming-hdmi-tuf-w` titles say B650E; spec B650.
- Expected: B650E / X870E kept, since the E variant is a different chipset (`scraper/specs/schema.py` lists B650E separately; `scraper/mfr/common.py` line 211 says they must not share a key).
- Cause: partly traced. `canon_chipset` (`scraper/specs/canon.py` line 449) keeps E when the vendor string has it; the folding comes from the vendor label. Whether any code strips the E was not confirmed.
- Confidence medium (could be an intended vendor label). Silent.

### F10 (S3, high): invisible bidi marks
- 23 instances across memory (10), psu (10), case (1), case_fan (1), storage (1). Examples:
  - `model:case:atlas-m3m-black`, `dimensions_mm` = `\u200e420 × 285 × 350`
  - `model:case_fan:52cfm-af120-air-led-series-triple-120mm-3-rgb-white`, `part_numbers` = `\u200eCO-9050082-WW`
  - `model:memory:b3200gsst-ld4as032g-32gb-3200mhz`, `model` = `\u200f LD4AS032G-B3200GSST`
- Expected: the same text without U+200E/U+200F.
- Cause: unverified (vendor text).
- Confidence high. Silent.

### F11 (S3, high): extra motherboard key
- `pcie_x4_slots` (value None) on 32 motherboards, outside the schema key set. Examples: `model:motherboard:12450h-aio-h45-sk-t2c-thin-miniitx`, `model:motherboard:1851-aorus-b860i-ice-lga-pro-miniitx`, `model:motherboard:2q-motherboard-rack-w880d4id-miniitx`.
- Expected: key removed, or added to schema if wanted.
- Cause: unverified.
- Confidence high. Silent.

### F12 (S3, high): dead override
- `mpn:gpu:100505849` (`{"memory_type": "GDDR3"}`) matches no listing (scan of `catalog.json` listing text). Two other overrides resolve to real products: `mpn:cpu:pk8072007045600` → `model:cpu:674x` (LGA4710, correct), `mpn:gpu:4711377107549` → F05.
- Expected: remove or fix the key.
- Confidence high. Not in QA (n/a).

## Suspicions (no sourced expected value)

- `aio.fan_rpm_min` = 10 on 13 vendor-sourced AIOs (e.g. `model:aio:240-a24-alpha2-se-240mm-black`, `model:aio:aio-cooler-cpu-h100i-icue-link-liquid-240mm-white`). A fan's min RPM of 10 is impossible; unit or parse error likely. Expected unknown.
- `aio.airflow_cfm` = 767.0 on `model:aio:3-loop-silent-360mm-black` (manufacturer source). Far above the other 94 AIOs (max otherwise 120). Expected unknown.
- `aio.fan_size_mm` = 60 on Zalman Alpha 24/36 AIOs (source: extracted). Expected probably 120; not confirmed.
- `cooler_air.height_mm` = 25 on `model:cooler_air:212-3cfm-57-hyper-120mm-black` (manufacturer). A 212 class tower is ~150–165 mm. Expected unknown offline.
- `case_fan.rpm_max` = 400 on GAMDIAS Notus 120mm (vendor).
- `psu.molex4_connectors` = 9 on SilverStone 2U units (manufacturer); `psu.sata_connectors` = 18 on Seasonic (vendor).
- `case.drive_bays_35` = 18 on `model:case:u660-black` whose title says "supports up to 21 drives" (vendor). Could be total not 3.5".
- `case.volume_l` = 1.3 on `model:case:011de-4x-evo-front-mesh-o11d-black` (an accessory kit filed as a case).
- `memory.first_word_latency_ns` = 7.9 on G.Skill 5066 CL20 is in fact correct (CL20 / 2533 MHz = 7.9 ns); see False positives.
- `storage.pcie_gen` 5 on `model:storage:990-evo-1000gb-pcie4-m22280` (1pc and tms say Gen 5; ivory says Gen 4; the product id says pcie4). Expected unknown offline.
- CPU base clock 3.3 (250K Plus) and 3.2 (270K Plus) from 1pc/tms vs ivory 4.2/3.7; expected unknown.
- Ivory `drive_bays_25` conflicts (e.g. `model:case:501-base-lx-pure-white`: ivory 9 vs vendors 5). Likely the same parser family as F01; not traced.
- `motherboard.memory_slots` = 1 on `model:motherboard:1xdp-1xhdmi-6e-am5-b850-pro-s-wifi-atx` (MSI PRO B850-S). Probably wrong; not confirmed.
- `motherboard.memory_speeds` on `model:motherboard:b550m-pro-vdh-microatx`: 1pc says up to 4266, ivory 4400.
- `memory.voltage_v` 1.4 vs 1.1 on Corsair 48GB DDR5 7000 (vendor disagreement).

## False positives

- Kingston KC3000 `2TB` with capacity 2048 (`model:storage:0-2048g-4-kc3000-skc3000d-2048gb-nvme-m22280`): title code `2048G`, correct.
- LGA1700 with DDR5 flagged by `SOCKET_MEMORY` (95 hits): LGA1700 supports DDR5 boards; the schema map is a hint only.
- `case.max_cooler_height_mm` 40–58 on small cases (5 hits, C9): plausible for SFF cases (e.g. `model:case:isk110-u3-vesa-black` 40, `model:case:raven-rvz02-black` 58).
- Chipset regex matches `B860M` for `B860` and `B650E` for `B650` in the first parser run: my regex bug, fixed in `scan_title_vs_spec.py`.
- MSI / Gigabyte alias false matches in title-vs-spec chipset: regex bug, fixed.
- `memory.first_word_latency_ns` 7.9: correct arithmetic for CL20 at 5066 MT/s.
- `gpu.memory_type` GDDR7 on RTX 5050 `model:gpu:2xdp-2xhdmi-5050-8gb-gaming-gddr7-geforce-oc-rtx-8gb` vs yahav: the spec GDDR6 is the right one (1pc agrees); yahav is wrong.
- 8400F thread_count 12 (spec) vs 16 (1pc, tms): spec is right (6 cores / 12 threads).
- Ryzen 7 8700F L3 16 MB (spec) vs ksp 24: spec right.
- 14700 cores 20 (spec) vs yahav 16: spec right.
- 12700 base 2.1 GHz (spec) vs 1pc 1.6: spec right.
- 285K base 3.7 / boost 5.7 (spec): right.
- Samsung/WD 7.68 TB rows with 7680 (`model:storage:dc-enterprise-sn840-ultrastar-wd-7680gb-u2-25`): spec right, tms 8000 wrong.
- Kingston NV3 500 GB (spec 500) vs yahav 480: spec right.

## Not checked

- Scan 7 (source-tier ranking via `spec_sources`): only the cases in F02, F03, F05 were traced. The rest of the tier ranking across all categories is not checked.
- Reference-tier audit rows beyond cpu and motherboard (aio 5, case_fan 12, psu 11, storage 1 in `ref.json`). Not drilled.
- PSU PCIe connector sums; memory timing outliers beyond the listed ones.
- Top/bottom 1% of every numeric field was read only for the listed fields.
- `scraper/audit_titles.py` results (62 duplicate_name, 79 too_long, 6 too_short, 3 upper_ti, 1 series_word): counted, not drilled. Mostly out of lane (titles).
- Ivory-only products: whether F01 changed any product whose only bay source is Ivory (not checked).
- `canon_chipset` E-suffix path: read, not run on the vendor strings.
- No live web checks (offline run). All "expected" values come from in-catalog sources or the title; Intel/AMD spec values are marked unverified.
