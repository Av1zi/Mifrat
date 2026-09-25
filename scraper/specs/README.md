# `scraper/specs/` — the typed, tiered spec system

Replaces the old additive `extractors.py` regex soup + `display_specs.py`
cleanup layer (both deleted). One product now always carries one fixed key set
for its category, with `null` for anything unknown, filled from a strict
source-reliability hierarchy. Spec correctness is a product feature, so the
system is deterministic, validated and auditable.

## Why the old system had to go

- No schema: ~800 ad-hoc attribute keys; `display_specs.py` existed only to
  clean up the mess afterwards.
- Additive merge: first-writer-wins by accident of call order, not reliability.
- Stringly-typed values (`"65W"` / `65` / `"65 W"`), booleans needing hacks.
- The same fact could live in `attributes`, `display_specs` and a `pcpartdb`
  sidecar — three shapes, three possible values, silent conflicts.
- The frontend guessed which of 800 keys mattered.

## Layout

| File | Responsibility |
| :--- | :--- |
| `schema.py` | **Single source of truth.** Per category: ordered fields with type, unit, enum, range, `filterable`, display `group`, aliases, he/en label. Also owns the knowledge maps (`CHIPSET_INFO`, `SOCKET_MEMORY`). |
| `values.py` | Boundary coercion (`coerce`): vendor text -> typed value, in the field's unit. Rejects anything it cannot represent (never guesses zero). |
| `canon.py` | Canonical forms (`mATX` -> `Micro-ATX`, `gold` -> `80+ Gold`, `AMDB850` -> `B850`). |
| `labels.py` | Vendor label vocabulary: Hebrew/English detail label -> schema field (category-aware), plus Hebrew value cleaning. |
| `text.py` | The one place regexes live (titles, capacities, sockets, clock ranges). |
| `validate.py` | Per-value validators + post-merge cross-field consistency. |
| `merge.py` | Deterministic tiered merge; higher tier wins, equal-tier conflicts are logged. |
| `derive.py` | UI facets derived from typed specs (CPU tier/generation). |
| `legacy.py` | Transitional `attributes` view **derived from** `specs` (see below). |
| `build.py` | Orchestration: per-listing pass + per-product pass. |
| `report.py` | Coverage/conflict report for a run (`data/site/spec_report.json`). |
| `export_site.py` | Generates `site/src/specSchema.generated.ts` from the schema. |
| `api.py` | Public surface consumed by `matching.py` / `normalize_and_match.py`. |
| `resolvers/` | One module per source tier. |
| `golden/` | Hand-verified fixtures + `check_golden.py`, plus real vendor pages (`golden/tms_pages/`) for `scripts/check_tms_detail.py`. |

## The pipeline

```
raw listings (unchanged spiders)
      |
      v
matching.enrich_listing()            (unchanged: brand/model/mpn/match_text)
      |
      v
specs/resolvers/*                    per-source typed facts {field: [Fact]}
  reference.py    pcpartdb index + data/specs/overrides.json      (Tier 0)
  vendor_struct.py vendor payloads, detail tables, Ivory cuts     (Tier 1)
                   (labels.translate_vendor_label + clean_detail_value)
  title_parse.py   regex over title/SKU                           (Tier 2)
  weak_vendor.py   1PC/Plonter prose fragments, fill-only         (Tier 3)
      |
      v
specs/merge.py       higher tier wins; equal-tier conflict -> QA log
      |
      v
specs/validate.py    per-value validators + cross-field consistency
      |
      v
product["specs"]  = FULL schema, nulls included
product["spec_sources"] = {field: tier}
      |
      v
site_data.py -> data/site/*.json (nulls elided; re-expanded in site/src/api.ts)
```

Order inside the product pass is deliberate (`build.py::build_product_specs`):

1. collect per-offer facts (tiers 1-3) + the post-match bridge values;
2. provisional merge (no Tier 0) -> anchors + the legacy view;
3. reference matching **with those anchors** (`reference.py`), plus overrides;
4. final merge with all tiers -> the authoritative sheet;
5. fill derived fields, cross-field checks, projection to `attributes`.

## Source reliability tiers

| Tier | Source | Role |
| :--- | :--- | :--- |
| 0 — Reference | docyx/pc-part-dataset (PCPartPicker specs) indexed by `scraper/pcpartdb.py` + committed `data/specs/overrides.json` | Authoritative; wins every conflict. |
| 1 — Trusted vendor | Ivory `cuts`/`detail_specs`, TMS product fields, the `matching:computed` bridge | Fills what Tier 0 lacks. |
| 2 — Title/SKU | typed regex resolvers over `match_text` | Fills remaining nulls. |
| 3 — Weak vendors | 1PC prose, Plonter tree/dash dumps | Fill-only; a value contradicting a filled Tier 0-2 field is discarded and logged, never merged. |

Rules:

1. Never overwrite a filled field with a lower tier.
2. Equal-tier conflict -> keep the higher-confidence value, record both as a
   `spec_conflict` QA case (rendered on `#/qa`).
3. `null` is first-class: no source -> ships as null ("Unknown" in the UI).
   Never guess.
4. Manual overrides are king: `data/specs/overrides.json`, keyed by
   `product_id` + field, is the production escape hatch (no code deploy).

### Reference identity (why Tier 0 is safe)

Specs are only as good as the product -> reference-row link. Strictest first:

1. exact normalized-name equality;
2. fuzzy name match at a per-category threshold **plus a hard anchor check** —
   at least one structured field parsed from our own data must equal the
   candidate's, and the candidate must not contradict another anchored field.
3. ambiguity/tie -> no Tier-0 match. Wrong specs are worse than null specs.

Two same-name rows that differ in a field (colour/CAS twins) are intersected:
only the fields **every** row agrees on are used.

Degradation: a missing or stale index logs one warning and disables Tier 0; the
pipeline continues on tiers 1-3 and the coverage report makes it visible.

## The transitional `attributes` view

`legacy.to_attributes()` projects the merged `specs` into the flat blob the
frontend's **category filter rail**, table columns, variant pills and the build
compatibility engine still read this cycle. It emits each field name plus every
declared alias so existing consumers keep finding their keys, and it round-trips
(feeding it back through `vendor_struct` reproduces the same specs).

The **product page already renders `specs` directly** (schema order, typed
values, "Unknown" for null) and reference data is merged invisibly (no more
pcpartdb/pckombo sidebox). Retire `legacy.py` + the `attributes` field once the
category rail (and `build.ts`) finish migrating to `specs`.

## Canonical forms (one spelling per fact)

The filter rail can only be honest if `AM5`, `AMD AM5` and `AMD AM5 (LGA1718)`
are one value. `canon.py` owns that mapping and runs before type coercion:

- `canon_socket`: finds the socket token anywhere in the value, drops vendor
  noise and parentheticals, and expands bare Intel numbers (`1851` ->
  `LGA1851`). AMD prints its physical package in parentheses (`AMD SP5
  (LGA6096)`); reading that produced phantom sockets that ranked among the most
  common CPU sockets until Sep 2026. Cooler `sockets` lists are canonicalized
  per element, splitting vendor groupings (`1150/1151/1155/1156/1200`).
- `canon_gpu_chipset`: GPU chips are marketing names, canonicalized the way the
  reference data spells them (`GEFORCE RTX5070` -> `GeForce RTX 5070`,
  `RX9070XT` -> `Radeon RX 9070 XT`, `RTX A4000` stays prefixless). The board
  chipset rule (`^[A-Za-z]{1,4}\d{2,4}$`) must never be applied to GPUs: it
  silently rejected 87% of the GPU catalogue.
- Unit scaling lives in `values.coerce`: a `_gb` field holding `2TB` is 2000,
  not 2.
- `canon_color` translates Hebrew color words first (`שחור | כסוף` ->
  `Black / Silver`), so an Israeli vendor's two-tone case does not become a
  third filter option.
- `canon_series` strips the manufacturer a vendor glues onto a lineup name
  (`AMD EPYC` -> `EPYC`): the `series` facet is vendor-free, and a detail row
  must not fork it into two entries.
- Knowledge maps are data, not truth: `CHIPSET_INFO["WRX90"]` claimed the
  `sWRX8` socket until Sep 2026, so WRX90 boards inherited a wrong socket from
  the title parser while the vendor page printed `sTR5`. WRX90 is
  Threadripper PRO 7000 (sTR5); WRX80 is the sWRX8/DDR4 line.

## Derivation and inference (`derive.py`)

Two kinds of knowledge are separated on purpose:

- **Derived facets** (`cpu_tier`, `cpu_generation`) are pure functions of a
  model number, computed on demand for the legacy view.
- **Inferred specs** (`infer_specs`) only fill `null` fields, always set
  `sources[field] = "derived"`, and only encode facts that hold for a whole
  lineup or platform: Ryzen series -> microarchitecture/node/L2-per-core (with
  explicit APU exceptions: 2200G/2400G are Zen, 3200G/3400G are Zen+, and
  mobile parts are never inferred), Intel desktop generation -> codename/node,
  tray packaging -> no cooler, socket -> platform memory maximum, `thread_count` for
  SMT-uniform AMD lineups, and storage fields implied by the interface
  (`M.2 PCIe 4.0 x4` -> NVMe SSD on M.2 at gen 4).
- **Never inferred**: per-SKU facts. L3 size, exact clocks, ECC support, fan
  counts, connector counts, board USB headers. A wrong number is worse than a
  missing one, so these stay `null` until a real source answers.

The order inside `build_product_specs` is part of the contract:
`merge -> fill_derived -> cross_check -> infer_specs`. `cross_check` runs first
because a consistency rule may *null* a contradictory value (a tray CPU that
claims a bundled cooler); inference then answers for the field the rule just
emptied, which it could not do while that wrong value was still present.

`cross_check` also emits **notes** that change no data, e.g. a
`microarchitecture` that contradicts its own model number (the reference
dataset lists Threadripper 7960X as Zen 2). They land in
`data/site/spec_report.json` under `issues` with `kind: spec_note`.

## Spelling folds and shared Hebrew (Sep 2026 coverage pass)

- `normalize_label` folds זיכרון -> זכרון: vendors mix full and defective
  ktiv spellings for the same label (TMS prints גודל זיכרון, Ivory prints
  גודל זכרון); one canonical form prevents near-duplicate table rows that
  each map correctly but only for one vendor.
- TMS combined connectivity cells ("Bluetooth 5.4 | Wi-Fi 7 | LAN 5 Gb/s")
  are split per radio (`CONNECTIVITY_SPLIT` token); Bluetooth itself has no
  schema field by design — board BT version is not a compatibility fact.
- Plonter certificate rows (`certificates-according to manufacturer`) map to
  `efficiency`; canon_efficiency extracts the tier word from the
  parenthetical blob. The `manufacturer` alias no longer leaks via schema
  suffix matching because the label resolves before the alias lookup.
- Concatenated vendor chipset cells ("AMDB850AMDX670",
  "INTELH810INTELH610", "C612PCH") split on brand/suffix words; server
  chipsets C602/C612 joined CHIPSET_INFO (cross-check now knows their
  sockets).
- TMS case shorthand "2+2" drive bays sums to 4 (`canon_bay_count`); list
  coercion splits comma-glued elements so ["ATX, Micro ATX"] and
  ["ATX", "Micro ATX"] converge instead of conflicting.
- Warranty / importer rows are `is_ignored_label` bookkeeping: they leave
  `specs` AND the label-gap report, where they drowned real evidence.
- Known unmapped labels left as evidence deliberately: 1PC's junk-drawer
  "Spec / Interface Connectivity" (HDMI+USB+SATA in one cell), motherboard
  ממשק אחסון (a storage-capability list with no schema field), case
  עיצוב תרמי (vendor cooling gimmicks), PSU PFC. New fields require a
  schema decision first (see "Adding or changing a spec field").

## Vendor detail pages (`labels.py`) and the TMS selector bug

Most of a page's richest facts — L3 cache, exact clocks, board slots/headers/
RAID, drive RPM, rear USB counts — exist **only** on the vendor's product page.
`scraper/spiders/detail_pages.py` fetches those pages into
`data/raw/detail/<vendor>.jsonl`; `vendor_struct.parse_detail_specs()` turns the
rows into facts.

Two things were broken until Sep 2026, and both were invisible:

1. **The TMS selector matched nothing.** TMS renders its "מפרט" block as
   `<div class="product-attribute-item"><h3 class="specification-title">label</h3>
   <div class="specification-data">value</div></div>`. The spider only looked
   for `dl/dt/dd`, two-column tables, `[data-spec-name]` and JSON-LD
   `additionalProperty` — so all 1,051 TMS detail pages ever scraped produced
   `specs = {}`, the ledger correctly refused to mark them, and the pending
   queue never drained while the vendor page showed 14-21 rows. `_parse_specs()`
   now matches that markup (and its schema.org `itemprop`s), and reports
   `extra.spec_selector` / `extra.spec_rows` so "page had no rows" and "rows we
   could not map" are distinguishable in `mark` output.
2. **Hebrew labels and values were dropped.** The translator was Ivory-only and
   `is_junk_text()` rejected any value containing Hebrew letters, so
   `תושבת מעבד = sTR5` and `128 ליבות` could never reach the schema.

`labels.py` is the fix for (2) and the place vendor vocabulary now lives:

- `translate_vendor_label(label, category)` resolves a detail label through a
  curated category table, a common table, an English parenthetical hint and
  finally the schema's own `label_he`/`label_en`. **Category-aware by design**:
  `מעבד גרפי` is a CPU's integrated graphics but a GPU's chip name.
- One vendor row can expand into several fields through **action tokens**
  (`__clock_range__`, `__cache_tier__`, `__memory_kit__`, `__rpm_range__`,
  `__gpu_outputs__`, `__raid__`, `__usb_count__:*`): `Base 2.7GHz | Max. 4.1GHz`
  becomes base+boost, `2x16GB` becomes count/size/total, `L3 512MB` becomes
  `l3_cache_mb` (the tier token's own digit is stripped first, or every cache
  would ship as 3 MB), `450-500W` becomes the upper bound.
- `clean_detail_value(value)` removes Hebrew unit/noun words, translates Hebrew
  color/boolean words, and **drops the whole value** when Hebrew prose survives
  — `לא תואם AM5` would invert its meaning if the token were kept.
- Vendor SKU rows (`מק״ט`, `sku`, `mpn`) are ignored on purpose: that is the
  shop's catalogue number, not the manufacturer part number.

### Unmapped labels are evidence, not noise

Every detail label that maps to no schema field is counted into
`data/site/spec_report.json` under `label_gaps` (category, label, count, sample
product ids) and printed at the end of a normalize run. That list is the queue
for `labels.py`: it currently shows real schema gaps (`motherboard:Lighting`,
`Recommended PSU`, GPU memory bus width, DirectX/OpenGL versions) next to
ignorable bookkeeping (`Warranty / Importer`).

### The detail ledger means "specs on disk", not "scraped once"

`make_detail_pending make` now re-queues any ledger entry whose specs are no
longer present in the current detail file. Rebuilding or truncating a detail
file used to strand those SKUs forever (622 ivory entries pointed at rows that
no longer existed, with 134 rows on disk). TMS stays excluded from the cloud
workflow — it blocks datacenter IPs — so its backfill runs from the home IP in
~200-page chunks with `mark` after each chunk.

## Adding or changing a spec field

1. Edit `scraper/specs/schema.py` (name, type, unit, enum, range, aliases,
   `filterable`, `group`, he/en label).
2. Bump `SCHEMA_VERSION` for a breaking change and update
   `golden/fixtures.json`'s `schema_version`.
3. Regenerate the frontend metadata: `python -m scraper.specs.export_site`.
4. Teach a resolver to emit it (vendor alias -> automatic; title -> add a
   `text.py` regex in the right `parse_*`).
5. `python scripts/check_spec_sync.py` must pass.

Nothing else needs editing: labels, filter allowlist, PDP order and the TS type
all come from the same definition.

## Verifying a change

```bash
python scripts/check_spec_sync.py                 # schema <-> frontend drift
python -m scraper.normalize_and_match             # rebuild catalog + site data
python -m scraper.specs.golden.check_golden       # hand-verified fixtures
python scripts/check_tms_detail.py                # vendor page fixtures (offline)
python scraper/check_site_size.py                 # payload guard
npm --prefix site run build                       # typecheck + bundle
```

The coverage report is printed by the normalize run and written to
`data/site/spec_report.json` (per category x field: `% filled`, `% tier-0`,
conflicts, dropped-invalid counts). Core compat fields (socket, chipset,
`memory_type`, `wattage_w`, `form_factor`) are the regression signal: they must
not lose coverage, and no conflicting value must be rendered anywhere.
