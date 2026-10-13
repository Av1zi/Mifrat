# Spec Coverage — Detailed Plan (Oct 2026)

> Goal: fill the missing spec data on product pages. The vendor facts are
> already on disk — they are dropped at label-map / value-parse time, not
> missing from the scrape. This round maps what vendors already publish into
> the **existing** schema: no new fields, no new scraping, no schema change,
> so the generated frontend module is untouched.
>
> Status: implemented 2026-10-03 (Phases 0–2, 4–5 done; Phase 3 measured
> and deliberately skipped — no remaining low field has title evidence).
> Measured on the same 2026-10-03 snapshots, pre/post rebuild.

---

## 1. Baseline (measured, catalog of 2026-10-02)

| Metric | Value |
| :--- | :--- |
| Products / listings | 3,120 / 4,910 |
| Null schema fields | **35,239** (~11 per product) |
| `spec_report.json` label-gap rows | **13,062** across 280 labels (report caps at 300) |
| Tier-0 reference matches | 898 / 3,120 products (29%) |
| Detail capture (tms / ivory / 1pc) | 2,251 specs / 2,244 listings · 813 / 678 · 2,113 / 1,988 |

Per-category fill: cpu 72%, memory 62%, case_fan 59%, storage 58%,
motherboard 50%, gpu 50%, aio 38%, case 37%, **psu 31%**, cooler_air 26%,
cooling_other 20%.

Fields at 0% category-wide (all with matching vendor rows on disk):
PSU connectors/length, case fan mounts/expansion slots/weight, GPU
`slot_width`/`external_power`/`cooling`, cooler `sockets`/fan counts.

### Proven cause

`labels.py` lookup is exact-match, so a whole family of real vendor labels
misses the existing keys:

| Vendor label | Existing key it should hit | Rows |
| :--- | :--- | ---: |
| `EPS 12V 8 pin` | `eps12v` | 187 |
| `PCI-E Connectors 8 pin` | `8-pin pcie` | 184 |
| `Molex 4 pin` | `molex` | 183 |
| `חיבורי SATA` | `חיבורי sata3` | 188 |
| `חיבורי 12VHPWR` | `12vhpwr` | 129 |
| `תושבת מעבד` (aio/cooler tables) | `socket` (cpu table only) | 238 |
| `סוג תאורה` | `תאורה` | 426 |
| `גודל לוח` (Ivory) | `תצורת לוח` | 155 |

Ivory's board vocabulary (`תמיכה בזכרון`, `תמיכה באחסון`, `חיבורי USB`,
`כרטיס רשת קווי`, …) and 1PC's grouped labels (`hardware / Socket`,
`RAM / RAM type`, `Spec / Interface Connectivity`) are absent or unparsed
entirely; rich Ivory cells pack 3–5 facts each and are currently dropped
whole. A real TMS PSU page carries `חיבורי SATA: 5`, `Molex 4 pin: 3`,
`PCI-E Connectors 8 pin: 2`, `EPS 12V 8 pin: 2` — all four fields ship 0%.

### Non-causes (do not fix what is not broken)

- Detail capture is essentially complete; no re-scrape is needed.
- Missing offers/vendors (Plonter dropped, 47% single-offer) and the 83%
  empty descriptions are separate tracks — out of scope here.

---

## 2. Decisions locked

1. **Map existing schema fields only.** Fields that need a schema decision are
   recorded as a tracked candidate list with evidence (see §6).
2. No scraping, spider, or vendor changes; no schema change, so no frontend
   regeneration (`specSchema.generated.ts` stays as is).
3. Precision rules unchanged: never guess, `null` stays first-class,
   dropped-invalid values stay visible in the report.

---

## 3. Phases

### Phase 0 — Measurement harness

- `scripts/diagnose_spec_coverage.py`: offline, no network. Replays
  `data/raw/detail/*.jsonl` through `translate_vendor_label` /
  `parse_detail_specs`, prints label-gap rows per vendor/category, a dry-run
  mapping for each gap label, and projected per-field fill. Seconds per
  iteration instead of minutes for a full normalize.
- Snapshot the current `spec_report.json` as the delta baseline.

### Phase 1 — Label vocabulary and normalization (`scraper/specs/labels.py`)

Priority by row count:

1. **PSU connectors** (~880 rows): `PCI-E Connectors 8 pin`, `EPS 12V 8 pin`,
   `Molex 4 pin`, `חיבורי SATA`, `חיבורי 12VHPWR`, plus 6 / 6+2 / 16-pin and
   20/24-pin spellings.
2. **Coolers / AIO** (~1,100 rows): `תושבת מעבד` for aio + cooler tables,
   `רדיאטורים`, `מאוורר מובנה (ממ)`, `סוג תאורה`, `גובה (ממ)`; Ivory
   `תאימות תושבת Intel/AMD`, `גודל רדיאטור`, `מספר מאווררים`, `מהירות מאוורר`.
3. **Case** (~900 rows): `סוג תאורה`, `מידות כ-`, `תאימות לוח`,
   `PCI-E x16 (x4) Slot`, `PCI-E x1 Slot`.
4. **Ivory motherboard block** (~1,100 rows): `גודל לוח`, `תמיכה בזכרון (RAM)`,
   `תמיכה באחסון`, `חיבורי USB`, `כרטיס רשת קווי (LAN)`, `כרטיס קול`,
   `קישוריות Wi-Fi`, `חיבורים פנימיים בלוח האם`, `חיבורים בלוח האם (בגב המחשב)`.
5. **1PC labels** (~500 rows): `hardware / Mother Board Form factor`,
   `RAM / RAM Size`, `RAM / RAM Capacity`, `Storage / Storage Type`,
   `Storage / Storage capacity`, `Spec / Network Card`,
   `Spec / Interface Connectivity`.
6. **Bookkeeping ignores** in `_IGNORED_LABELS` so real evidence stops
   drowning: `שונות`, `הערות`, `Screen/*`, `Spec / Operating System`,
   `Spec / Built-in speakers`, `Spec / Designed for gaming`,
   `חיבור סיריאלי COM`, `PFC`, `מסב מאוורר`, `פרופיל זיכרון`.
7. **Normalization hardening** in `translate_vendor_label`: token-aware
   fallback (filler words connectors/connector/pin/גודל/חיבורי,
   `pci-e`/`pci express` → `pcie`, punctuation-free keys) so future vendor
   spellings match without a new table row. Exact-match precedence stays;
   Hebrew labels are still never guessed.

### Phase 2 — Multi-fact value parsing

New action tokens following the existing `__memory_kit__` / `__usb_count__` /
`__raid__` pattern (`vendor_struct.py`, `values.py`, `validate.py`):

| Token | Cell example | Fields |
| :--- | :--- | :--- |
| `__memory_support__` | `4 סלוטים DDR5 … עד 256GB … 9200MT/s` | `memory_slots`, `memory_type`, `memory_max_gb`, `memory_speeds` |
| `__storage_support__` | `4x M.2 … 4x SATA 6Gb/s … RAID 0/1` | `m2_slots`, `sata_ports`, `raid_support` |
| `__expansion_slots__` | `3x PCI-E x16 … 1x PCI-E x1` | `pcie_x16_slots`, `pcie_x1_slots`, `expansion_slots` |
| `__rear_ports__` / `__internal_headers__` | USB standards, DP/HDMI, fan headers | `usb_ports`, `onboard_video`, `fan_headers`, `usb*_headers` |
| `__interface_connectivity__` | 1PC junk-drawer cell | same fields, per token |

Every value goes through `values.coerce` + validators; unparseable cells are
dropped and counted, never guessed.

### Phase 3 — Title/SKU fill for facts pages do not carry

Only after a Phase 1–2 rerun, targeting fields still <30% with title evidence:
GPU `memory_type`, GPU `external_power`, PSU `length_mm`, case
`max_gpu_length_mm`, case_fan `static_pressure_mmh2o`, storage
`pcie_gen`/`nand`, memory `timing`/`voltage_v`. Each addition gated on ≥20
products' evidence, added to `text.py` + the category `parse_*`.

**Verdict 2026-10-03: no-op.** Title evidence measured over all listings:
memory full-timing strings 0, PSU `160mm` 1, GPU power-connector mentions 0,
case clearance 0, fan pressure 0, cooler fan-count words 1, AIO radiator
sizes 27 (aio `radiator_size_mm` already 96% via detail). The detail pass
harvested everything titles could give; the remaining low fields
(side-fan mounts, expansion slots, `static_pressure`, `timing`) have no
title evidence by construction. No `text.py` changes made.

### Phase 4 — Rebuild, verify, quantify

- `python -m scraper.normalize_and_match`; diff `spec_report.json` against the
  baseline (fill, label gaps, conflicts, invalid, core-field coverage).
- Spot-check 10 real products (PSU / AIO / case / motherboard / GPU).
- Run all gates: `scripts/check_spec_sync.py`,
  `scraper.specs.golden.check_golden`, `scripts/check_tms_detail.py`,
  `scripts/check_spec_merge.py`, `scraper/check_site_size.py`,
  `npm --prefix site run build`.
- Add golden fixtures pinning each new token against real vendor rows,
  including negatives (promo copy and Hebrew prose must still be dropped).

**Done 2026-10-03.** All gates pass (golden 81 assertions/10 products,
tms-detail 486/32 pair cases, spec-merge 33, size-guard +2.3% bytes at
+0.0% products, site build). Spot-checks caught two real issues, both
fixed: duplicate dict keys that silenced the case fan-mount and cooler
socket-union mappings, and 1PC `Spec / Network Card` shipping `Wi-Fi 6`
as `ethernet` (new `__network_card__` router). One stale fixture updated:
`sku:cooler_air:814256022132` height 170 → 164 (Ivory prints 164
consistently since Sep; no surviving source ever said 170). Pair cases
pin every new token plus negatives (bus-width ≠ VRAM, RPM tolerance
stripped, negated Hebrew still dropped).

**Hardening round, same day.** Adversarial re-audit found and fixed:
connector counts read pin-type digits as counts (`4+4-pin` → 4, `12VHPWR`
→ 12 — now leading-count-only with a singular-`חיבור` → 1 fallback);
slot counts read lane widths (`x8` → 8 — now `Nx`-sum with lane skip);
`canon_socket` passed junk through (`\ 1954` displayed as a socket) and
forked 115X three ways (now rejects unknowns, converges `LGA115X`;
invalid 255 → 84). Relaxed lookup audited over all 450 English labels:
curated the two legit hits (`Memory Type`, `Modular`), colon-guarded the
rest (1PC `Spec / Specifications` flattened pairs with empty values were
silently swallowed — back to gap evidence). Case `Spec / Interface
Connectivity` (101× `USB 3.2, USB-C`) routes to `front_usb`. Follow-ups
for another day, all with evidence: split unpaired `Label: value`
flattening upstream; `TR5`/`TRX4` vendor truncations; product-level
subset-vs-union socket ties (merge rules untouched by design).

### Phase 5 — Guardrails and documentation

- `scripts/check_spec_coverage.py`, wired into `normalize-and-deploy.yml`
  after normalize: fail when label-gap rows exceed the budget, a category's
  fill drops below its floor, or a core field regresses. Floors come from the
  post-fix baseline.
- Update `scraper/specs/README.md` and `PROJECT_OVERVIEW.md` §6.5.
- Record deferred schema candidates with row counts (see §6).

**Done 2026-10-03.** `check_spec_coverage.py` (stdlib-only, CI-wired after
the spec-merge gate): budget 4,500 gap rows (post-pass: 3,475), 12 category
floors + 5 core floors at baseline-minus-2pp. README documents the new
token family, `_is_token()` contract, relaxed lookup guards and the
ignore/deferred split; overview §6.5 summarizes results.

**Review pass, 2026-10-13 (101 new upstream commits, 1PC cloud-suspended).**
Re-verifying the pass end to end on the current snapshots found two real
defects; both are fixed here.

- `קבוצת הספק` (the PSU *series* range, `650W - 1100W`) was mapped to
  `wattage_w`. It prints first in the vendor table, so its low bound won the
  merge ahead of the unit's own `הספק` row: 143 PSUs shipped the family
  minimum (a 750W Antec displayed 650W, a 2800W Seasonic 1200W), and the
  polluted value also drove the tier-0 identity slice, which then matched a
  650W reference variant and "confirmed" the wrong number. The label is now
  unmapped gap evidence for a future `series_wattage_range` field; 192 PSUs
  store the vendor's rating and none store the family minimum.
- Ivory prints SATA ports as `N חיבורי SATA` (116 rows); only the English
  `4x SATA 6Gb/s` shape was parsed, so those boards shipped `sata_ports`
  null even when `m2_slots` filled from the very same cell. Both spellings
  now parse, including when a board lists its ports in the internal-header
  cell (106/107 Ivory boards have `sata_ports`). A port count still never
  comes from `SATA 6Gb/s` or `PCIe 4.0 x4 / SATA mode`.
- Re-measured on the 2026-10-13 snapshots: label-gap rows 3,428 (budget
  4,500), invalid 84, conflicts 9,666, core chipset 96% / memory_type 97% /
  socket 99% / wattage_w 96% / form_factor 73%. All gates pass: spec-sync,
  golden 81, spec-merge 33, tms-detail 492 (36 pair cases), coverage floors,
  size guard (+2.2% bytes, +0.0% products), site build.

---

## 4. Targets (measured 2026-10-03, same snapshots pre/post)

| Metric | Before | After | Target | Met |
| :--- | ---: | ---: | :--- | :---: |
| label-gap rows (diagnose) | 5,632* | **4,636** | <5k | ✓ |
| label-gap labels (report) | 280 | **102** | — | ✓ |
| overall null fields | 35,195 | **31,133** | ≤26k | ✗ (aspirational) |
| psu fill | 31.2% | **48.3%** | ≥45% | ✓ |
| cooler_air fill | 26.1% | **43.8%** | ≥40% | ✓ |
| aio fill | 38.5% | **53.0%** | ≥50% | ✓ |
| case fill | 37.3% | **45.0%** | ≥48% | ✗ (−3pp) |
| motherboard fill | 50.1% | **53.5%** | ≥60% | ✗ |
| conflicts | 7,334 | 10,643 | no blow-up | ⚠ see note |
| invalid | 255 | **84** | no blow-up | ✓ |
| core (socket/chipset/mem/watt/form) | 99/96/97/96/74 | same | no regression | ✓ |

\* The 13,062 figure in §1 was the Oct-02 catalog; by implementation time
(partial Phase-1 work already in the tree) the same-counter baseline was
5,632. Report-counter gap rows went 280 labels → 102 (3,475 rows).

Conflicts note: +45% is more facts meeting more facts (PSU connector
counts, socket unions, USB summaries from two vendors now overlap where
before one side was dropped). Spot-checks show truthful values on both
sides (e.g. vendors genuinely disagree 12GB vs 16GB on one 9070 XT;
Seasonic's own 18 SATA is printed as 18). Invalid went DOWN (255 → 84)
because the new parsers emit typed values, the network-card router stopped
shipping `Wi-Fi 6` as ethernet, and `canon_socket` stopped passing junk.

## 5. Risks

- Long prose values misparsed → token-level parsing, validators, drop-invalid
  visibility, one golden fixture per new token.
- Tier order and precision rules untouched; conflicts are logged, never
  silently resolved.
- The rebuild rewrites tracked artifacts (`data/catalog.json`,
  `data/site/*.json`) — expected output change; commit them with the change
  or let CI regenerate.

## 6. Deferred (needs a schema decision, evidence recorded 2026-10-03)

Report-counter rows in the post-pass `spec_report.json` (top unmapped):

| Label | Category | Rows | Note |
| :--- | :--- | ---: | :--- |
| `ממשק אחסון` | motherboard | 432 | storage-capability list, no field |
| `מהירות זכרון` | gpu | 216 | memory clock, no field |
| `גרסת DirectX` / `גרסת OpenGL` | gpu | 155/155 | no field |
| `רוחב פס זכרון` | gpu | 154 | bus width, no field |
| `כמות מסכים מקסימלית` | gpu | 153 | max displays, no field |
| `Recommended PSU` | gpu | 152 | no field |
| `תמיכה במעבדים (CPU)` | motherboard | 121 | CPU support list, no field |
| `קישוריות Bluetooth` | motherboard | 110 | BT version, not a compat fact |
| `Storage / Storage Type` | motherboard | 76 | 1PC junk-drawer on boards |
| `Thunderbolt` | motherboard | 76 | header count, no field |
| `PCI-E x4` | motherboard | 57 | no x4-slot field |
| `Bays 5.25` | case | 49 | no field |
| `Rackmount` | case | 32 | no field |
| `מידות משאבה` / `מידות רדיאטור` | aio | 82/90 | pump dims / radiator dims, no field |
| `חיבורים` | aio/cooler | 95/38 | connector lists, no connector field on coolers |
| `מהירות קריאה/כתיבה` | storage | ~250 | sequential speeds, no field |
| `תאימות ערכת שבבים` | cpu | 111 | chipset-compat, no cpu field |
| `דור המעבד` | cpu | 65 | generation, no field |
| `פרופיל קירור` | cooler | 14 | Low Profile, no field |
| `מאוורר צד` | case | 96 | side mounts, no `fan_side` field |
| `קבוצת הספק` | psu | 194 | series wattage range (`650W - 1100W`), not the unit rating — see the 2026-10-13 review above |
| `Storage / Storage capacity` | motherboard/gpu | 10/4 | 1PC cell: `4 slots` / `3x M.2, 6x SATA III` on boards, `16GB` on GPUs — mixed semantics per category, needs a decision |

Deliberately ignored (bookkeeping, not facts): `PFC` (187), case-fan
bearing `מסב מאוורר` (249), memory profile `פרופיל זיכרון` (170),
`באריזה`/`אריזת` box contents. Row counts from the pre-pass diagnose;
they no longer appear in the report by design.

## 7. Out of scope

- New schema fields (deferred list above).
- Vendor/offer coverage (Plonter replacement, 1PC's listing dip).
- The 83% empty product descriptions.
- Any new scraping or detail re-fetch.
