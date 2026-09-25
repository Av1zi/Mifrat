# Spec System Overhaul — Detailed Plan

> Goal: replace the current additive, regex-soup attribute pipeline with a
> **fixed, typed, per-category spec schema** (PCPartPicker-style, per the
> attached `pc_component_specifications.md`), filled from a **tiered,
> accuracy-first source hierarchy**, with `null` for anything unknown.
> Spec correctness is a core product feature — the system must be
> deterministic, validated, and auditable.

---

## 1. Why the current system must go (diagnosis)

| Problem | Evidence |
| :--- | :--- |
| No schema | `extractors.py` (3,701 lines) produces ~800 distinct ad-hoc keys; `display_specs.py` exists *only* to clean up the mess after the fact |
| Additive-only merge | every source does `attrs.setdefault(k, v)` — first-writer-wins by accident of call order, not by reliability |
| Stringly-typed values | `"65W"` vs `65` vs `"65 W"`; booleans as `True`/`"yes"`/`"1"` needing `YES_NO_KEYS` canonicalization hacks |
| Vendor quirks baked into core logic | Ivory cut-label decoding, Plonter German detail tables, 1PC JSON-bleed guards all live inside the shared extractor |
| Two parallel spec systems | `attributes` (raw blob) + `display_specs` (curated view) + `pcpartdb` (sidecar reference) — the same fact can exist 3 times with 3 values |
| Silent conflicts | when two listings of one product disagree, merge order decides; `attribute_conflicts` is diagnostic-only, never resolved |
| Frontend pays the price | `specs.ts` needs SPEC_PRIORITY + FILTER_ALLOWLIST + VARIANT_IDENTITY_KEYS to guess which of 800 keys matter |

**What we keep:** spiders, raw JSONL snapshots, `matching.py` product
identity/clustering (`listing_key`, manual merges, MPN/SKU matching),
price history, image pipeline, detail-enrichment spiders. This overhaul
replaces **attribute extraction + spec representation only** — not product
matching, not scraping.

---

## 2. Target architecture

```
raw listings (unchanged spiders)
        |
        v
matching.enrich_listing()          (unchanged: brand/model/mpn/match_text)
        |
        v
specs/resolvers/*                  NEW — per-source typed fact extraction
  +- reference.py      pcpartdb / curated DB lookup     (Tier 0)
  +- vendor_struct.py  Ivory cuts/detail, TMS fields    (Tier 1)
  +- title_parse.py    regex over title/SKU             (Tier 2)
  +- weak_vendor.py    1PC/Plonter fragments            (Tier 3, fill-only)
        |  each resolver emits {field: (typed_value, source, confidence)}
        v
specs/merge.py                     NEW — deterministic tiered merge
        |  higher tier wins; equal-tier conflict -> QA log, keep higher-
        |  confidence value; never silently merge contradicting facts
        v
specs/validate.py                  NEW — per-field validators + cross-field
        |  consistency (range, enum, unit, socket<->chipset, kit math...)
        v
product.specs = FULL SCHEMA with null for every unknown field
        |
        v
site_data.py -> data/site/*.json   (specs replace display_specs;
                                    attributes kept trimmed for filters
                                    during transition, then retired)
```
Key property: **one product = one fixed key set, always**. The frontend
never discovers keys; it renders the schema. Missing => `null`.


---

## 3. Canonical schema (single source of truth)

New file `scraper/specs/schema.py` defines, per category, an ordered list
of `(field, type, unit, enum?, range?)`. Types: `int`, `float`, `bool`,
`str`, `list[str]`, `enum`. Units are baked into names (`_ghz`, `_mb`,
`_mm`, `_w`, `_rpm`, `_db`, `_ns`, `_v`) — values are always bare numbers
in that unit, no unit parsing downstream, ever.

Mapped from the attached spec sheet (field names snake_cased, units
normalized):

### cpu
`manufacturer, part_numbers: list, series, microarchitecture,
core_family, socket, core_count: int, thread_count: int,
base_clock_ghz: float, boost_clock_ghz: float, l2_cache_mb: int,
l3_cache_mb: int, tdp_w: int, integrated_graphics: str|null,
max_memory_gb: int, ecc_support: bool, includes_cooler: bool,
packaging: enum(boxed|tray), lithography_nm: int, smt: bool`

### cpu_cooler (covers current `cooler_air` + `aio`)
`manufacturer, model, part_numbers: list, fan_rpm_min: int,
fan_rpm_max: int, noise_db: float, color, height_mm: int,
sockets: list[str], water_cooled: bool, fanless: bool,
radiator_size_mm: int|null (aio), fan_size_mm: int|null`

### motherboard
`manufacturer, part_numbers: list, socket, form_factor:
enum(ATX|EATX|mATX|Mini-ITX), chipset, memory_max_gb: int, memory_type:
enum(DDR4|DDR5), memory_slots: int, memory_speeds: list[int], color,
pcie_x16_slots: int, m2_slots: list[str], sata_ports: int,
ethernet: str, onboard_video: str, usb2_headers: int,
usb32_gen1_headers: int, usb32_gen2_headers: int, ecc_support: bool,
wireless: str|null, raid_support: bool, back_connect: bool`

### memory
`manufacturer, part_numbers: list, speed: str ("DDR5-6000"),
speed_mhz: int, form_factor: str, module_count: int, module_size_gb: int,
total_gb: int, color, first_word_latency_ns: float, cas_latency: int,
voltage_v: float, timing: str ("30-36-36-76"), ecc: bool,
registered: bool, heat_spreader: bool`

### storage
`manufacturer, part_numbers: list, capacity_gb: int, type:
enum(SSD|HDD|Hybrid), cache_mb: int, form_factor: str, interface: str
("M.2 PCIe 5.0 x4"), nvme: bool, pcie_gen: int|null, rpm: int|null`

### gpu
`manufacturer, part_numbers: list, chipset, memory_gb: int,
memory_type: str, core_clock_mhz: int, boost_clock_mhz: int,
interface: str, color, frame_sync: str|null, length_mm: int, tdp_w: int,
slot_width: int, cooling: str, external_power: list[str],
dp_outputs: dict, hdmi_outputs: dict`

### case_fan
`manufacturer, model, part_numbers: list, size_mm: int, color,
quantity: int, flow_direction: enum(standard|reverse), rpm_min: int,
rpm_max: int, airflow_cfm: float, pwm: bool, led: str|null,
connector: str, static_pressure_mmh2o: float|null`

### case
`manufacturer, part_numbers: list, type: str, color,
psu_included: str|null, side_panel: str, psu_shroud: bool,
front_usb: list[str], mb_form_factors: list[str],
max_gpu_length_mm: int, drive_bays_35: int, drive_bays_25: int,
expansion_slots: str, fan_support: dict, radiator_support: dict,
dimensions_mm: str ("HxWxD"), volume_l: float`

### psu
`manufacturer, part_numbers: list, type: enum(ATX|SFX|...),
efficiency: enum(80+ .. titanium), wattage_w: int, length_mm: int,
modular: enum(no|semi|full), color, fanless: bool,
atx4_connectors: int, eps8_connectors: int, pcie16_connectors: int,
pcie12_connectors: int, pcie8_connectors: int, pcie62_connectors: int,
pcie6_connectors: int, sata_connectors: int, molex4_connectors: int`

Categories without a meaningful spec sheet (`accessories`,
`cooling_other`, `other`) get a minimal schema
(`manufacturer, accessory_type, color`) — same fixed-key rule.

The schema module also emits, from the same definition:
- the TS `types.ts` interface (generated or hand-synced with a CI check),
- the i18n label key list (Hebrew + English) for `i18n.ts`,
- the filter allowlist and spec-display order for `specs.ts`
  (schema carries `filterable: true/false` and `display_group` per field),
- a JSON Schema for validation tests.

One definition -> four consumers. No more drift between extractor keys,
display order, filters, and translations.

---

## 4. Source reliability tiers (the accuracy model)

| Tier | Source | Role |
| :--- | :--- | :--- |
| **0 — Reference** | Expanded `pcpartdb` index (docyx/pc-part-dataset = PCPartPicker specs, same layout as the attached sheet) + committed manual overrides `data/specs/overrides.json` | Authoritative. Wins every conflict. |
| **1 — Trusted vendor structured** | Ivory builder `cuts`/`detail_specs`, TMS product fields | Fills fields Tier 0 lacks (packaging Tray/Box, Israel-specific SKUs). |
| **2 — Title/SKU parsing** | Slimmed-down regex resolvers over `match_text` | Fills nulls after 0+1. |
| **3 — Weak vendors** | 1PC prose, Plonter `tree`/fragments | Fill-only, **and** every value must pass validation; a Tier-3 value contradicting a filled Tier 0–2 field is discarded and logged, never merged. |

Rules:
1. **Never overwrite a filled field with a lower tier.**
2. **Equal-tier conflict** -> keep the higher-confidence resolver's value,
   record both in `data/site/qa.json` as a `spec_conflict` case (new QA
   kind alongside `duplicate_vendor`/`naming_conflict`).
3. **`null` is a first-class value** — if no tier supplies a field, it
   ships as `null` (rendered as "Unknown" in UI). Never guess.
4. **Manual overrides are king**: `data/specs/overrides.json` (committed,
   human-edited) keyed by `product_id` + field — the escape hatch when a
   wrong value is spotted in production.

### Why Tier 0 is viable
`pcpartdb.py` already downloads and indexes this dataset — but its
`SPEC_KEYS` whitelist keeps only ~6 specs per category and it is attached
as an unmerged sidecar (`product.pcpartdb`). The overhaul:
- expands `SPEC_KEYS` to the **full** PCPartPicker field set per category
  (the dataset already carries every field in the attached sheet),
- makes it the primary spec source instead of a decorative reference box,
- keeps the safety property: index missing -> pipeline degrades to tiers
  1–3 with a loud warning and a coverage report, never crashes.


---

## 5. Identity matching — how a product gets its Tier-0 specs

Specs are only as correct as the product->reference-row link. Hierarchy
(strictest first, stop at first hit):

1. **Exact MPN match** — dataset `part_numbers` vs our extracted MPN
   (`matching.py` already extracts MPNs; strengthen MPN capture so every
   category tries). Zero ambiguity.
2. **Exact normalized name match** — brand + model normalized
   (lowercase, punctuation-stripped, tokens sorted) equality.
3. **Fuzzy name match, verified** — rapidfuzz >= per-category threshold
   (~90, as today) **plus a hard anchor cross-check**: at least one
   structured field parsed from our own title must equal the candidate's
   (memory: `capacity_gb`+`speed_mhz`; motherboard: `chipset`; cpu:
   model number; gpu: `chipset`; psu: `wattage_w`). No anchor agreement
   -> no match. This is the key change vs today's score-only attach, and
   it is what makes reference data safe to treat as authoritative.
4. **No match** -> tiers 1–3 only; product logged in the new
   `spec_coverage` report as "unmatched" so overrides/matching improve
   over time.

Ambiguity rule: two tied reference rows -> prefer exact-name over fuzzy;
still tied -> no Tier-0 match. Wrong specs are worse than null specs.

---

## 6. Validation layer (`scraper/specs/validate.py`)

Every value from every tier passes validators before entering the merged
sheet. Failed value -> dropped + counted in the run report (never kept).

- **Range checks**: cpu `tdp_w` 3–300, `core_count` 1–128, clocks
  0.5–8 GHz; memory `speed_mhz` JEDEC/XMP whitelist + plausible range;
  psu `wattage_w` 200–3000; case `volume_l` 1–200; etc. Most of these
  heuristics already exist scattered in extractors.py — they move into
  one typed place.
- **Enum checks**: `packaging`, `form_factor`, `efficiency`,
  `memory_type`, `modular` reject out-of-enum values.
- **Cross-field consistency** (post-merge):
  - motherboard chipset <-> socket <-> memory_type via the existing
    `CHIPSET_INFO` map (moved into schema data); contradiction -> keep
    the higher-tier field, null the loser, QA-log.
  - memory `module_count x module_size_gb == total_gb`.
  - cpu `includes_cooler=false` required when `packaging=tray`.
  - gpu `external_power` expected when `tdp_w > 75` (warn-only).
- **Unit normalization at the boundary**: resolvers convert "155 mm",
  "25.6 dB", "1.4V" to typed numbers once; everything downstream is
  numeric.

---

## 7. Provenance & QA

- Each product carries `spec_sources: {field: tier}` in `catalog.json`
  (site JSON gets a summarized form only if size allows — decide from
  `check_site_size.py`).
- Normalize run prints a **coverage report**: per category x field,
  `% non-null`, `% tier-0`, conflicts, dropped-invalid counts. This is
  the accuracy dashboard; later a `--strict` mode can fail CI if core
  compat fields (socket, chipset, wattage...) regress >2%.
- `qa.json` gains `spec_conflict` cases; the public `#/qa` page renders
  them like the existing duplicate/naming cases.


---

## 8. Implementation phases (file-by-file)

### Phase 0 — Schema foundation (no behavior change)
- New package `scraper/specs/` with `schema.py` (full section-3
  definition), type helpers, and `scripts/check_spec_sync.py` that
  verifies `site/src/types.ts` + `specs.ts` + `i18n.ts` keys cover the
  schema (run in CI).
- `decisions.md` entry recording the tier model + null policy.

### Phase 1 — Reference data upgrade
- `scraper/pcpartdb.py`: expand `SPEC_KEYS` to the full per-category
  field list; capture `part_numbers` too; run
  `python -m scraper.pcpartdb refresh`; spot-check ~20 known products
  (9800X3D, B850-A, Peerless Assassin 120 SE...) against the attached
  sheet.
- New `data/specs/overrides.json` (empty scaffold) + loader.

### Phase 2 — Resolvers + merge engine
- `scraper/specs/resolvers/reference.py` — Tier-0 lookup using the
  section-5 hierarchy (replaces `enrich_products_with_pcpartdb`'s
  attach-only behavior).
- `scraper/specs/resolvers/vendor_struct.py` — Ivory cuts/detail_specs
  + TMS structured fields, moved from extractors.py
  (`_from_vendor_meta`, cut-label decoding, `_is_ivory_promo_label`),
  retargeted to schema fields.
- `scraper/specs/resolvers/title_parse.py` — the per-category regex
  parsers (`_parse_cpu`, `_parse_motherboard`, ...) mechanically ported
  to emit typed schema fields. This is a move-and-type refactor, not a
  rewrite: keeps the battle-tested regexes, drops the alias/post-process
  soup (the schema handles units and canonical forms).
- `scraper/specs/resolvers/weak_vendor.py` — 1PC/Plonter fragment +
  tree parsing, fill-only flag.
- `scraper/specs/merge.py` — tiered merge + conflict logging.
- `scraper/specs/validate.py` — section 6.

### Phase 3 — Pipeline integration
- `normalize_and_match.py`: after `match_listings`, call
  `specs.build_product_specs(products, listings)`; per-listing
  `extract_attributes` blobs stop being the source of truth.
- Products get `specs` (full schema, nulls included) + `spec_sources`.
- Legacy `attributes` derived *from* `specs` for one transition cycle
  (filter compatibility); `extractors.py` deleted at end of Phase 4.
- `site_data.py`: `_trim_product` whitelists `specs`; drop
  `display_specs` and **delete `display_specs.py`** (schema order
  replaces it). Verify `motherboard.json` stays under the size guard;
  nulls are 4 bytes each, but if size explodes, elide nulls in site JSON
  and re-expand in `api.ts` from a shipped field-list constant.

### Phase 4 — Frontend
- `types.ts`: `Product.specs` typed (generated per-category interfaces
  or `Record<string, string|number|boolean|string[]|null>`).
- Detail overlay (`views/product.ts`): render schema order directly;
  `null` -> muted "Unknown"/"לא ידוע". Remove the pcpartdb sidebox —
  reference data is now merged invisibly; optional "specs verified
  against reference database" badge when Tier-0 coverage is high.
- `specs.ts`: SPEC_PRIORITY / FILTER_ALLOWLIST regenerated from schema
  metadata (`filterable`, `display_group`); VARIANT_IDENTITY_KEYS
  re-keyed to schema names.
- `build.ts` (compat engine): re-key socket/ram/wattage reads to schema
  fields (mostly same names — units-in-names is what makes this easy).
- `i18n.ts`: one label entry per schema field, he+en.
- Legacy `#/build?` links and D1 short links: untouched (specs are not
  in the URL contract).

### Phase 5 — Cleanup + verification
- Delete `extractors.py`, `display_specs.py`, and the `pcpartdb`
  sidecar field on products.
- Golden-file checks: `scraper/specs/golden/` with ~30 hand-verified
  products (the 9 from the attached sheet as the first fixtures);
  `python -m scraper.specs.check_golden` asserts extracted specs equal
  the expected dicts (plain script, per repo no-test-framework hygiene).
- Full verification loop: single-spider test crawl ->
  `python -m scraper.normalize_and_match` -> coverage report ->
  `npm --prefix site run build` -> eyeball PDPs of the 9 fixtures.


---

## 9. Rollout & risk control

| Risk | Mitigation |
| :--- | :--- |
| Tier-0 mis-match poisons specs | section-5 anchor cross-check; ambiguity -> null; conflicts -> qa.json; overrides file hot-fixes without a code deploy |
| Coverage regression on niche / Israel-only SKUs absent from the reference dataset | tiers 1–3 still fill; coverage report tracks it; overrides file grows over time |
| Site JSON size growth from all-null fields | `check_site_size.py` gate; if exceeded, elide nulls in site JSON and re-expand in `api.ts` from a shipped schema field-list |
| Filter breakage during transition | legacy `attributes` derived from `specs` until the frontend fully migrates |
| pcpartdb index missing in CI | degrade to tiers 1–3 + loud warning; coverage report makes degradation visible instead of silent |
| Hebrew promo labels / vendor junk leaking in | promo-label guards move into `vendor_struct.py` unchanged; validators add a second net |

### Acceptance criteria
1. Every product in `data/site/<cat>.json` has the identical schema key
   set for its category; unknown = `null`.
2. The 9 attached-sheet products render every listed field correctly.
3. Coverage report: core compat fields (socket, chipset, memory_type,
   wattage_w, form_factor) >= today's coverage; zero conflicting values
   rendered anywhere.
4. `npm run build` green; `#/qa` shows spec conflicts; remote-image
   guard untripped; category file sizes within guard.
5. `extractors.py` + `display_specs.py` deleted; one schema module is
   the only place field names/units are defined.

### Out of scope (explicitly)
Spider changes, product matching/clustering changes, pricing, images,
price history, short links. TMS/Nano scraping rules are untouched — all
of this is post-scrape.

