# Plan — one product per part (merge identity rework)

Status: **implemented**, shipped 2026-11-06 (products 4,687 -> 4,474, listings
unchanged). Written 2026-11-04 as a proposal; the body below is the design as
approved. Deviations from §2.3/§3.6: `color` became a gpu axis, and the pid
alias map lives in `data/site/meta.json` (`pid_aliases`), not `index.json`.
Later refinements (R1-R7 duplicate fixes) are summarized in
`docs/duplicate-groups-audit.md`.
Author context: the "245" search on the site showed 10 rows for 3 chips; the
catalogue holds 7,091 listings in 4,672 products, and **706 groups of
listings that describe the same part are spread over more than one product
(909 redundant products)** across 11 categories.

---

## 0. Decisions taken (from the owner, 2026-11-04)

| # | Decision | Answer |
|---|---|---|
| D1 | Box vs Tray of one chip | **Two separate products.** The split stays; only the orphans it creates get fixed. |
| D2 | Scope of the first pass | **All categories in one pass.** |
| D3 | Ambiguous identity evidence | **Merge and flag in the QA page.** Nothing is held back to a manual queue. |

D1 means the "245" search goes from 10 rows to **5**, not 3:
`245 Tray` / `245K Box` / `245K Tray` / `245KF Box` / `245KF Tray`.

---

## 1. What is actually broken

### 1.1 The screenshot, decoded

`data/site/cpu.json` today contains **10** products whose name contains "245",
for exactly three chips:

| chip | products today | offers |
|---|---|---|
| Intel Core Ultra 5 245 (65 W, no K) | 1 | 1pc + tms |
| Intel Core Ultra 5 245K | **4** | `cpu:ksp:ksp-340388` (Box, 890), `cpu:ksp:ksp-340399` (Tray, 819), `model:cpu:coreultra5245k-tray` (1pc ×2 + tms), `mpn:cpu:at807680640f-tray` (yahav) |
| Intel Core Ultra 5 245KF | **5** | `cpu:ksp:ksp-340400` (Box, 690), `cpu:ksp:ksp-340404` (Tray, 690), `model:cpu:coreultra5245kf-tray` (1pc ×2 + tms), `mpn:cpu:at8076806414-tray` (yahav), `mpn:cpu:bx80768245kf` (yahav Box) |

The KSP pair is the one you spotted: **340400 ("Box", 690) and 340404
("Tray", 690) are the same chip at the same price.** KSP's own listing tags
confirm they are twins — identical `מעבד` (Intel Core Ultra 5 - 245KF),
identical `משך אחריות` (3 שנים), identical branch stock (חיפה רוממה),
identical labels, identical price — and only the `תכונות` tag differs
(Box vs Tray). By contrast the 245K pair at KSP (Box 890 / Tray 819) is a
genuine box-vs-tray pair: the box costs 71 NIS more.

### 1.2 Root cause — four defects, not one

**D‑1 — Orphan fall-through (`scraper/matching.py:5103`).**
The model-merge tier drops any subgroup with fewer than two members:

```python
if len(sub) < 2:
    continue          # <-- the only "Box" offer of a chip falls out here
```

A listing that is alone in its packaging subgroup (a chip sold boxed by one
vendor and tray by everyone else) is therefore **not** claimed by the model
tier. It falls through to the MPN tier, then the SKU tier, and ends up with a
vendor-specific product id (`mpn:cpu:bx80768245kf`,
`cpu:ksp:ksp-340400`). One chip, two products. This is exactly how
`245KF` became five products.

**D‑2 — Pid namespace divergence (`scraper/matching.py:5259-5294`).**
The model tier mints `model:<cat>:<code>` pids; the MPN and SKU tiers mint
`mpn:<cat>:<key>` and `sku:<cat>:<key>`. Tier 4b only reunites pids that
share the *same* key suffix, so `model:cpu:coreultra5245kf-tray` (1pc + tms)
and `mpn:cpu:at8076806414-tray` (yahav) — the same Intel 245KF chip — can
never meet, even though they were found by different tiers. The `model:` pid
also wins the tier race purely by being first, which is an accident of
ordering, not evidence.

**D‑3 — Identity is free text, not a code.**
`model_identity()` keys on a vendor's own `model` row
(`attrs["model"]`), cleaned. That row is written by a human at each vendor:
TMS prints `Core Ultra 5 245KF`, yahav prints
`Ultra 5 Processor 245KF`, ivory prints `ULTRA-5-250K`, 1PC prints
`C245KFT`. The matcher has no notion of "Intel Core Ultra 5 245KF" as an
identity, so it cannot see that four different strings are one chip. For
memory it is worse: TeamGroup's `model` row is the *series* (`TEAM GROUP
DELTA`), which is shared by **14** different products.

**D‑4 — No variant-axis model.**
The only variant axis the matcher knows is CPU packaging (hard-coded, Box vs
Tray). Everything else that changes the physical part — memory capacity,
module count, latency, RGB lighting; case colour; fan size and pack count;
radiator size; storage interface and capacity — is invisible to the merge
logic. So the matcher cannot tell "same part, different variant" (must stay
apart) from "same part, same product" (must merge).

### 1.3 Scale

Listings that share a category and a normalised model text, but land on more
than one product id:

| category | split groups | redundant products | category | split groups | redundant products |
|---|---|---|---|---|---|
| case | 157 | 177 | motherboard | 50 | 52 |
| case_fan | 113 | 123 | psu | 38 | 44 |
| memory | 100 | 143 | cooler_air | 27 | 29 |
| storage | 78 | 145 | gpu | 17 | 18 |
| aio | 71 | 83 | other | 1 | 4 |
| cpu | 53 | 90 | accessories | 1 | 1 |

**909 is an upper bound, not a target.** The audit keys on raw vendor model
text, so it also counts false splits: G.Skill `6000J3036F16GX2TZ5RK` (RGB
black) vs `...TZ5RS` (non-RGB silver) share the model text but are
genuinely different kits, and must stay apart. The real number will be
smaller once the variant axes are modelled — §2.3.

### 1.4 The K/F constraint — measured, not assumed

Checked every CPU product for offers whose model codes disagree only by a
letter suffix:

- **No contamination today.** Every CPU product holds exactly one suffix
  (`245K` products hold only `k`, `245KF` products only `kf`). Intel 14700
  spans 4 suffixes across **12** products; Intel 14900 spans 4 across 11.
- **A numeric-only key would be a disaster.** Keying CPUs on the numeric
  core alone collapses 14700 / 14700F / 14700K / 14700KF (12 → 4) and
  245K / 245KF into each other.

So the K/F separation is currently safe **by accident** — it comes from
differing free text, not from a rule. Any rework that keys CPUs more loosely
destroys it unless it introduces an explicit, tested rule. §2.2 makes that
rule a first-class, checked invariant.

---

## 2. Target model

> A **product** is one physical SKU.
> Its identity is *(category, canonical model code, variant axes)*.
> Its **offers** are the vendor listings of that SKU.

### 2.1 New module `scraper/identity.py`

The single source of truth for identity. Four public pieces:

| function | purpose |
|---|---|
| `model_code(category, listing) -> str \| None` | canonical code for the part, e.g. `coreultra5-245kf` |
| `variant_axes(category) -> tuple[str, ...]` | the spec fields that change the physical part |
| `variant_conflict(category, a, b) -> bool` | two known-but-different axis values |
| `part_number_class(value) -> "manufacturer" \| "vendor" \| None` | is this a maker part number or a retailer's own SKU? |

`scraper/specs/schema.py` stays the owner of field names and types; the
identity module only *selects* fields from it.

### 2.2 CPU identity — the reference implementation

`cpu_model_code()` builds the code from three parts:

1. **family** — `Core Ultra 5`, `Core i9`, `Ryzen 7`… (normalised, brand stripped)
2. **core** — the numeric code: `245`, `14700`, `9950`
3. **suffix** — the **full** trailing letter cluster, verbatim: `K`, `KF`,
   `F`, `X`, `X3D`, `G`, `GT`, `T`, `KS`, `PLUS`, `F`…

```
Intel Core Ultra 5 245K    -> coreultra5-245k
Intel Core Ultra 5 245KF   -> coreultra5-245kf      # never equal to the above
Intel Core i9-14900KF      -> corei9-14900kf
AMD Ryzen 9 9950X3D        -> ryzen9-9950x3d
```

Rules that make this safe:

- The suffix is compared **exactly**. `k` ≠ `kf` ≠ `f` ≠ `kf` vs `K` after
  case folding only. No prefix/suffix truncation, no "affix" tolerance
  (that logic exists today for GPU part numbers and must never touch CPU
  model codes).
- The Intel **series** tag (`225` vs `225 series 2`) is an axis, not part of
  the code, and it splits only when both sides state it (today's
  majority-ride rule is kept).
- Socket (`LGA1851` vs `LGA1700`) is an axis too, and a disagreement blocks a
  merge outright — an LGA1700 chip is never an LGA1851 chip.

### 2.3 Variant axes per category

Real field names from `scraper/specs/schema.py`:

| category | axes |
|---|---|
| `cpu` | `series`, `packaging`, `includes_cooler`, `socket` |
| `memory` | `memory_type`, `total_gb`, `module_count`, `speed_mhz`, `cas_latency`, `form_factor`, `lighting`, `color` |
| `gpu` | `chipset`, `memory_gb`, `memory_type` |
| `motherboard` | `chipset`, `form_factor`, `wireless`, `memory_type` |
| `storage` | `capacity_gb`, `type`, `interface`, `form_factor`, `pcie_gen`, `rpm` |
| `case` | `type`, `color`, `rackmount` |
| `psu` | `wattage_w`, `efficiency`, `modular`, `color` |
| `case_fan` | `size_mm`, `quantity`, `led`, `color` |
| `aio` | `radiator_size_mm`, `color`, `lighting` |
| `cooler_air` | `height_mm`, `fan_size_mm`, `color`, `lighting` |

Axis semantics (one rule, applied uniformly):

- **known vs known and different** → different products. Never merge.
- **known vs unknown** → mergeable; the unknown side rides with the group.
- **unknown vs unknown** → mergeable.

`packaging` stays an axis, which is what keeps D1 (Box and Tray are two
products) true — and, per the existing decision, the site's packaging filter
keeps working.

### 2.4 Part-number classes

A shared manufacturer part number is the strongest possible identity
evidence. But two *different* manufacturer part numbers usually mean two
different variants of the same model (`6000J3036F16GX2TZ5RK` RGB vs
`...TZ5RS` non-RGB). Retailers also print their own catalogue codes
(`C245KFT` at TMS, `340404` at KSP, `171975` at 1PC), which say nothing
about identity.

`part_number_class()` separates the two:

| pair | outcome |
|---|---|
| same manufacturer PN | **merge** (strongest evidence) |
| one manufacturer PN + one retailer SKU | **merge**, flagged as weaker evidence |
| two different manufacturer PNs | **do not merge**, flagged as a variant conflict |
| two retailer SKUs | **merge** on the model code, flagged |

---

## 3. The rework

### 3.1 New tier 2 — identity tier (replaces the CPU-only model tier)

Replaces `matching.py:5048-5144`. For every category:

1. Group unassigned listings by `(category, model_code)`. Listings with no
   usable model code are skipped and fall through to the part-number tiers
   as today.
2. Split each group by variant axes (§2.3).
3. Within an axis subgroup, split again on the part-number class rule (§2.4).
4. Apply the existing blocked-pair veto (a human `not_match` still wins).
5. **Every surviving subgroup gets a stable pid — including one-member
   subgroups.** ← this is the fix for D‑1. The pid is
   `model:<cat>:<code>` plus an axis suffix (`-tray`, `-rgb`, …) only when
   more than one variant exists for that code, so single-variant codes keep a
   clean pid.

### 3.2 New step — reconciliation (fixes D‑2)

After the MPN and SKU tiers have run, compare every `model:` pid with every
`mpn:`/`sku:` pid in the same category:

- if the two pids' listings agree on model code and on all variant axes, and
  their manufacturer part numbers do not contradict each other → the `model:`
  pid is the survivor and the part-number pid's listings move onto it;
- otherwise both pids stay, and the pair is written to the QA page as a
  `split_candidate` case.

The `model:` pid always wins because the model code is the physical identity
and the part number is only evidence about it. This is a change of rule, not
of order — today's tier 4b already prefers the `mpn:` pid for URL stability,
so the reconciliation must also keep the **old pid in the URL map** (see
§3.6) so existing product URLs and price history keep resolving.

### 3.3 Packaging-conflict detection (your KSP case)

New check, run on the merged catalogue:

- **trigger**: one vendor lists the same model code twice with conflicting
  `packaging` labels.
- **corroboration**: identical price **and** an identical vendor spec-tag
  fingerprint (KSP's `תכונות`/`משך אחריות`/`זמין בסניף` tags), or a shared
  manufacturer part number.
- **corroborated** → the mislabelled listing joins the corroborated product
  (KSP 340400 joins the 245KF Tray product, becoming a second KSP offer of
  it) and the case is flagged `packaging_conflict` in the QA page.
- **not corroborated** → both keep their labels; the case is still flagged.
- **always** overridable from `data/matching/manual_products.json`.

This implements D3 for the one case where the vendor's own data contradicts
itself, and it does not change D1: Box and Tray remain two products.

### 3.4 Naming from identity (kills chimera names)

Today the canonical name is rebuilt from the *merged* `attributes["model"]`,
which is whichever offer's row won — so a product can inherit another
offer's model text. After the rework the name is built from the identity:

```
Intel + model code + axis words  ->  "Intel Core Ultra 5 245KF Tray"
```

plus the part number only when two products in the category would otherwise
read the same (`_disambiguate_duplicate_names` keeps working). The `245`
family then reads:

```
Intel Core Ultra 5 245 Tray
Intel Core Ultra 5 245K Box
Intel Core Ultra 5 245K Tray
Intel Core Ultra 5 245KF Box
Intel Core Ultra 5 245KF Tray
```

### 3.5 QA page — new case kinds

| kind | meaning |
|---|---|
| `identity_merge` | merged on the model code with no shared manufacturer part number |
| `packaging_conflict` | one vendor, two SKUs, conflicting Box/Tray labels (§3.3) |
| `variant_conflict` | two listings whose manufacturer part numbers disagree — not merged, worth a look |
| `split_candidate` | a `model:` pid and an `mpn:`/`sku:` pid that could not be reconciled (§3.2) |

Existing kinds (`duplicate_vendor`, `naming_conflict`, fuzzy review) are
untouched. New cases flow to `data/review_queue.json` and `data/site/qa.json`
(`/#/qa` filters by kind).

### 3.6 Id churn — history, saved builds, bookmarks

Product ids change (`mpn:cpu:bx80768245kf` → `model:cpu:coreultra5245kf-box`).
Three things are keyed by product id and must survive it:

1. **Price history** — `data/site/history/<category>.json` is keyed by product
   id (`{"dates": [...], "timestamps": [...], "cpu:1pc:1pc-171977": {...}}` —
   231 cpu series today). The history builder must fold each old id's series
   into its successor's series, so a merged product inherits the price curve
   of every product it absorbed.
2. **Shared builds** — `/list/<id>` is a *build* link (6-char id in D1
   `LISTS_DB`, `site/migrations/0001_lists.sql`), and the stored `build`
   JSON embeds product ids. Rows are insert-only, so old links cannot be
   rewritten — the client must resolve an unknown id through the alias map.
3. **Bookmarks** — product pages are hash routes (`#/p/<category>/<pid>`,
   `site/src/state.ts:369`). Not indexable (decisions.md: hash routes are not
   indexable), so there is no SEO cost, but a bookmarked pid must redirect to
   its successor.

So the catalogue emits a **pid alias map** (`old id → new id`) alongside
`data/site/*.json`:

- `site_data` writes it into `data/site/index.json` (one map, all
  categories);
- the client resolves a stored build's product ids through it, and
  `#/p/<category>/<old pid>` redirects to the successor;
- the history builder uses it to join series before writing the next
  `data/site/history/`.

---

## 4. Work breakdown

| phase | work | done when |
|---|---|---|
| **P0** | Measurement harness: `scripts/check_identity_merge.py` (3 invariants below) + a per-category delta reporter that diffs catalogue shape against `git show HEAD:data/catalog.json` | the reporter prints today's baseline for all 11 categories |
| **P1** | `scraper/identity.py`: `model_code`, `variant_axes`, `variant_conflict`, `part_number_class` + per-category tables | unit-checkable on the current catalogue: every CPU listing gets a code, `245k` ≠ `245kf` |
| **P2** | Rework tier 2 + add the reconciliation step (`matching.py`) | 245KF → 2 products, 245K → 2, 245 → 1 |
| **P3** | CPU reference implementation: suffix rule, series/socket axes, packaging-conflict detection | invariant I3 holds; KSP 340400/340404 = 2 offers of one product, flagged |
| **P4** | Extend to the remaining 10 categories (axes tables only, no engine changes) | every category's product count drops and each drop is explained |
| **P5** | Naming from identity (§3.4) | no product name mixes two offers' model texts |
| **P6** | QA kinds + site wiring (qa.json, review_queue.json, `/#/qa` filters, pid alias map + history join + build/pid redirect) | the four new kinds appear in `/#/qa`; an old build link and an old `#/p/…` pid still resolve |
| **P7** | Golden anchors + collapse-guard baseline: `python scripts/check_golden_resolution.py --update-anchors --apply`, then a reviewed baseline bump for the category-collapse guard | `check_golden_resolution.py` exits 0; the per-category delta table is recorded in `decisions.md` |
| **P8** | Verification: single-spider test crawl + local normalize run + `npm --prefix site run build` | site shows the expected 5 rows for "245"; build clean |

### Invariants the harness enforces (P0)

- **I1** — no product contains two offers with different canonical model codes.
- **I2** — no two products share `(category, model code, variant axes)`
  unless the pair is flagged in the QA file.
- **I3** — CPU suffix separation: for every numeric core, the suffixes across
  products form a partition; `…245k` and `…245kf` never share a product id.

I3 is the executable form of "K and F are two different things". It fails the
build if any future change regresses it.

---

## 5. Acceptance criteria

1. Search `245` returns **5** rows: `245 Tray`, `245K Box`, `245K Tray`,
   `245KF Box`, `245KF Tray` — down from 10.
2. `245KF` is **2** products: Box (yahav BX80768245KF) and Tray (1pc ×2 +
   tms + **ksp 340400 + ksp 340404** + yahav AT8076806414) — the KSP pair
   collapses into one product per criterion 4, so the Box product keeps only
   the offer whose manufacturer part number says retail-box (BX80768245KF).
3. `245K` is **2** products: Box (ksp 340388) and Tray (1pc ×2 + tms +
   ksp 340399 + yahav AT807680640F).
4. KSP 340400 + 340404 are **two offers of one product**, flagged
   `packaging_conflict`.
5. I1, I2, I3 all hold (`scripts/check_identity_merge.py` exits 0).
6. Every one of the 11 categories has a **smaller** product count, and each
   category's delta is listed in `decisions.md` with the reason.
7. No product's name mixes two different model texts.
8. `python scripts/check_golden_resolution.py` exits 0 and
   `npm --prefix site run build` is clean.
9. Price history for a merged product contains the joined series of every
   product it absorbed; an old shared build link still resolves its parts;
   a bookmarked `#/p/<category>/<old pid>` redirects to the successor.

---

## 6. Risks

| risk | mitigation |
|---|---|
| **Over-merging** — two different parts share a model code | the part-number class rule blocks the merge when two manufacturer PNs disagree; every weaker merge is flagged in the QA page; I1/I2 catch regressions |
| **Under-merging** — the model code is too strict | codes are per-category tables, tuned per category in P4 with a measured delta per category |
| **Catalogue collapse trips CI** — the golden gate fails a category at −15 % / the catalogue at −10 % | the collapse is the *goal* here, so the baseline bump in P7 is a reviewed, recorded step, not a silent threshold change |
| **Product ids churn** — URLs, history and fixtures break | the alias map (§3.6) plus `--update-anchors --apply`; the golden gate's exit-code contract (`0` clean, `2` churn, `1` failure) is respected |
| **Names change site-wide** | names are rebuilt from identity; a name diff is part of the P5 report, reviewed before commit |
| **Vendor label conflicts mis-resolved** | packaging conflicts are flagged, never silently corrected without corroboration, and are overridable from the manual file |

---

## 7. Files

**New**
- `scraper/identity.py` — identity engine
- `scripts/check_identity_merge.py` — the three invariants
- `scripts/report_identity_delta.py` — per-category before/after

**Changed**
- `scraper/matching.py` — tier 2 rework, reconciliation step, packaging-conflict detection
- `scraper/normalize_and_match.py` — pid alias map emission
- `scraper/build_price_history.py` — join each old id's series into its successor's
- `scraper/site_data.py` — alias map + new QA kinds
- `scraper/specs/schema.py` — only if an axis needs a field that does not exist yet
- `site/src/state.ts` — resolve/redirect a stale pid through the alias map
- `site/src/api.ts`, `site/src/types.ts` — the alias map shape
- `site/src/**` — `/#/qa` filters for the new kinds
- `site/worker.ts` — only if a build link must resolve a stale pid server-side
- `decisions.md` — the decisions, one line each
- `data/matching/manual_products.json` — overrides for the flagged conflicts

**Never touched**: `data/raw/**` (append-only input), `data/images/**`,
anything under `.env` / keys / `.wrangler/`.

---

## 8. Rollback

Everything is regenerated from `data/raw/`:

```powershell
git revert <merge-commit>          # code back to the old matcher
python -m scraper.normalize_and_match   # catalogue back to the old shape
```

The catalogue is a build artefact, so the rollback is one command plus a
rebuild. No raw data is rewritten, so nothing is lost.
