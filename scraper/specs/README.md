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
| `golden/` | Hand-verified fixtures + `check_golden.py`. |

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
python scraper/check_site_size.py                 # payload guard
npm --prefix site run build                       # typecheck + bundle
```

The coverage report is printed by the normalize run and written to
`data/site/spec_report.json` (per category x field: `% filled`, `% tier-0`,
conflicts, dropped-invalid counts). Core compat fields (socket, chipset,
`memory_type`, `wattage_w`, `form_factor`) are the regression signal: they must
not lose coverage, and no conflicting value must be rendered anywhere.
