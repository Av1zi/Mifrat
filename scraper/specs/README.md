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
| 0.5 — Manufacturer | the brand's own product page, fetched by `scraper/mfr/` into `data/mfr/<brand>.json` (see `scraper/mfr/README.md`) | Primary-source facts; beats the retailer payload, loses to Tier 0 and overrides. Source label `manufacturer`. |
| 0.75 — Catalog | Open Icecat sheets fetched by `scraper/icecat/` into `data/icecat/<brand>.json` (see `scraper/icecat/README.md`) | The brand's sheet as syndicated; beats retailers, loses to the brand's own page. Per-field trust gate (`mapping.DISABLED`). Source label `catalog`. |
| 1 — Trusted vendor | Ivory `cuts`/`detail_specs`, TMS product fields, the `matching:computed` bridge, foreign retailers' tables from `scraper/xref/` (source `xref:<site>`) | Fills what Tier 0 lacks. |
| 1.5 — Extracted | Claude reading the product's own listing text (`scraper/extract/`, `data/extract/products.json`) | Only fields still empty; a value is kept only if its quote is verbatim in the text and re-parses to the value, and only for fields the audit measured at ≤3% disagreement. Source label `extracted`. |
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
   The name must also pass `reference.fuzzy_row_plausible`: same brand, every
   distinctive model token of ours in the row, every model number of the row
   in ours (token-subset scores of 100 otherwise linked "Antec CSK DC" to
   "Antec CSK"). Variant fields (colour, efficiency, modular, lighting) from a
   non-exact link rank below the title (`merge.TIER_REFERENCE_FUZZY`).
3. ambiguity/tie -> no Tier-0 match. Wrong specs are worse than null specs.

Audit the links after changing any of this:
`python scripts/audit_reference_matches.py` (runs the normalize in memory,
writes `tmp/reference_audit.json`).

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
  per element, splitting vendor groupings (`1150/1151/1155/1156/1200`). The
  Intel 115X family shorthand converges to one form (`115X`, `LGA 115X`,
  `LGA115X` -> `LGA115X`), and unrecognized tokens return empty instead of
  passing through — cut fragments (`\ 1954`) and typos used to ship as
  sockets on cooler pages until Oct 2026. A wrong socket is worse than none.
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
- **Never inferred by rule**: per-SKU facts. Exact clocks, fan counts, connector
  counts, board USB headers. Two fan-count rules are the exception, because the
  count is fixed by something the product states, not guessed: an AIO's
  radiator size over its fan size (360 = 3 x 120; 135/135 sourced counts agree)
  and a GPU board line that names it (`tables/gpu_board_lines.json`, 53/53).
  Every such rule must pass `scripts/backtest_rules.py` before it ships. A wrong number is worse than a missing one, so these stay
  `null` until a real source answers. (L3/L2 size and ECC are the exception: since Oct
  2026 they come from the curated per-model table described below, i.e. from a
  source, not from a rule.)

The order inside `build_product_specs` is part of the contract:
`merge -> fill_derived -> cross_check -> infer_specs`. `cross_check` runs first
because a consistency rule may *null* a contradictory value (a tray CPU that
claims a bundled cooler); inference then answers for the field the rule just
emptied, which it could not do while that wrong value was still present.

`cross_check` also emits **notes** that change no data, e.g. a
`microarchitecture` that contradicts its own model number (the reference
dataset lists Threadripper 7960X as Zen 2). They land in
`data/site/spec_report.json` under `issues` with `kind: spec_note`.

### Curated tables and explicit negatives (Oct 2026, Phase 1c)

`derive.infer_specs` reads two kinds of knowledge beyond the architecture rules
above. Both only fill nulls and tag `derived:<rule>`; `scripts/fill_report.py
--check-tables` compares every table row with the vendor-published values already in
the catalog, and `scripts/check_spec_merge.py` validates every table cell against the
schema.

- **Lookup tables** (`scraper/specs/tables/*.json`, data not logic): GPU facts that are
  invariant for a chipset name (memory type, bus width, DirectX/OpenGL, the chip
  designer's reference TDP and recommended PSU, interface) and per-CPU-model facts
  (L2/L3, iGPU, Threadripper memory ceiling). A row lists a field only when it holds for
  every SKU sharing the anchor: the RTX 3060 row has no bus width because 12GB/192-bit
  and 8GB/128-bit both exist, `Radeon RX 9070` carries `_requires: {memory_gb: [16]}`
  because the name also covers the 12GB GRE, and `max_displays` is absent everywhere
  because retailers print the card's output count, not the chip's ceiling.
- **Explicit negatives** (`context` argument, built in `build.py::_evidence_context`):
  where the whole evidence base proves absence. A board whose title and *every* detail
  row never mention Wi-Fi/Bluetooth/Thunderbolt, on a page with a full table (8+ rows),
  has none (every one of the 473 boards that have Wi-Fi mentions it, 74/74 for
  Thunderbolt); a memory kit with no laptop/server marker is desktop, unbuffered, non-ECC;
  a case title that never mentions a PSU is "Not included". Negatives are spelled "No",
  never "None" (`values.coerce` treats "none" as a placeholder and drops it).
- **Schema gates** (`FieldSpec.applies_to`, `schema.applies()`): a field that cannot exist
  for a product (an SSD's RPM, a fanless PSU's fan size, a SATA drive's PCIe generation) is
  *not applicable*, not a gap. `scripts/fill_report.py` uses the same gate.

## Identity-scoped reference join (`identity+anchor`)

Name similarity alone cannot match products whose index row is named by
the *board model* ("MSI VENTUS 3X OC") while our query names the *chip*
("GeForce RTX 5070 Ti"): the chip is only in the row's `specs.chipset`.
The identity-scoped join closes that gap without weakening the ambiguity
rules (plan §5):

1. slice the index pool by exact identity-field equality
   (`IDENTITY_FIELDS`: gpu chipset+VRAM, memory type/count/size, PSU
   wattage, storage capacity, motherboard/CPU socket);
2. strip identity/physical tokens from the query (chip words, VRAM,
   kit notation, CL, MHz, category keywords) leaving board-model words;
3. require at least one *distinctive* residual token (non-brand,
   non-`_GENERIC_TOKENS`) and require the winning row name to contain
   every one — 'Patriot VP4300 Lite' cannot fall onto 'Patriot P400 Lite';
4. brand gate: residual brand must not contradict the row's brand
   (`_brand_agrees`; an Antec G650 never joins a Rosewill G650);
5. anchor re-check + the same tie refusal as the fuzzy path (tied rows of
   different names are refused; same-name variants intersect).

Precision beats recall: the first prototype scored ~415 joins, the
shipped version 180-200 — the dropped ones were exactly the unverifiable
brand-only residuals. Method string `identity+anchor` flows into the
coverage report like the others.

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
  `specs` AND the label-gap report, where they drowned real evidence. The Oct
  2026 pass added the same treatment for PSU `PFC`, case-fan bearing
  (`מסב מאוורר`), memory XMP/EXPO profile (`פרופיל זיכרון`) and box-content
  rows (`באריזה`, `אריזת`) — shop facts with no schema field, recorded as
  deferred schema candidates instead of gap noise.
- Known unmapped labels left as evidence deliberately: motherboard
  ממשק אחסון (a storage-capability list with no schema field), GPU memory
  bus width / DirectX/OpenGL / max-displays / Recommended-PSU, Thunderbolt,
  case side-fan mounts and 5.25" bays, storage sequential speeds. 1PC's
  junk-drawer "Spec / Interface Connectivity" is routed per category
  (motherboard USBs, storage interface, GPU PCIe lane, case front-panel USB);
  categories the router does not cover (PSU, fans, memory, CPU) stay gaps on
  purpose. New fields require a schema decision first (see "Adding or
  changing a spec field").

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
  would ship as 3 MB), `450-500W` becomes the upper bound. The Oct 2026
  coverage pass added a second family for cells that carry an existing-schema
  fact in prose or a foreign unit (`__sockets_cell__` unions Ivory's split
  Intel/AMD socket rows, `__memory_support__`/`__storage_support__` expand
  Ivory support cells to four fields, `__connector_count__:*` reads PSU
  connector counts, `__slot_count__:*` sums TMS per-type slot rows,
  `__fan_mount_cell__:*` / `__length_mm__:*` / `__dims_cell__` normalize
  Hebrew cm/mm cells, plus `__gpu_vram__`, `__network_card__`,
  `__interface_connectivity__` routers for 1PC grouped cells). Parameterized
  tokens carry their target after a colon and are recognized by
  `labels._is_token()` — any gate that walks the vocabulary must use it,
  not a hardcoded prefix list.
- English labels get one relaxed lookup (`_relaxed_lookup`): filler words
  (`connectors/pin/count/...`) are stripped and `pci-e` folds to `pcie`, so
  `PCI-E Connectors 8 pin` matches the curated `8-pin pcie` key. Guards: the
  curated key must be fully contained with >= 2 tokens, ties are refused, and
  Hebrew labels are never relaxed — they must be curated explicitly.
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
   `golden/fixtures.json`'s `schema_version`. Add a step to
   `scripts/migrate_mfr_schema.py` and run it: `mfr/store.py` skips a
   `data/mfr/*.json` at another version, which silently drops every
   manufacturer fact.
3. Regenerate the frontend metadata: `python -m scraper.specs.export_site`.
4. Teach a resolver to emit it (vendor alias -> automatic; title -> add a
   `text.py` regex in the right `parse_*`).
5. `python scripts/check_spec_sync.py` must pass.

Nothing else needs editing: labels, filter allowlist, PDP order and the TS type
all come from the same definition.

## Verifying a change

```bash
python scripts/check_spec_sync.py                 # schema <-> frontend drift
python scripts/diagnose_spec_coverage.py          # offline gap/fill view (seconds, no normalize)
python -m scraper.normalize_and_match             # rebuild catalog + site data
python -m scraper.specs.golden.check_golden       # hand-verified fixtures
python scripts/check_tms_detail.py                # vendor page fixtures (offline)
python scripts/check_spec_merge.py                # merge-rule regressions
python scripts/check_spec_coverage.py             # fill floors + gap budget (CI gate)
python scraper/check_site_size.py                 # payload guard
npm --prefix site run build                       # typecheck + bundle
```

The coverage report is printed by the normalize run and written to
`data/site/spec_report.json` (per category x field: `% filled`, `% tier-0`,
conflicts, dropped-invalid counts). Core compat fields (socket, chipset,
`memory_type`, `wattage_w`, `form_factor`) are the regression signal: they must
not lose coverage, and no conflicting value must be rendered anywhere.
