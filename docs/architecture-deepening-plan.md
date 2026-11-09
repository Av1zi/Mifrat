# Plan: deepening the most-churned modules

Status: **approved by the owner 2026-11-09, nothing built yet** (except the
product-id length fix, see §0). Source: architecture review of the files most
changed since 2026-09-09 (`scraper/matching.py` 25 commits, `site/src/i18n.ts`
24, `normalize-and-deploy.yml` 23, `scraper/specs/{labels,vendor_struct}.py` 19).
Terms: `GLOSSARY.md` for the domain; module / interface / seam / adapter /
depth / locality / leverage for the architecture.

Rules for every step below:

- **Refactor first, byte-identical.** A deepening ships as a pure refactor
  whose outputs (`data/catalog.json`, `data/review_queue.json`,
  `data/spec_gaps.json`, `data/site/**`) are byte-identical to a stashed run
  under the default `PYTHONHASHSEED` and `42`. Behaviour fixes come after, one
  commit each, with the measured delta written to `decisions.md`.
- **Tests at the interface.** Python modules get a `scripts/check_<x>.py
  --self-test` with inline fixtures (the repo convention; no pytest), wired
  into `normalize-and-deploy.yml` and `site-checks.yml`. Site modules get
  vitest files under `site/test/`.
- **No product id churn** unless a step says so and measures it.

## Build order

| # | Step | Why this position |
|---|---|---|
| 0 | Product id length limit | live bug, done |
| 1 | Durable lookups through one key module (§2) | recovers lost paid extraction data |
| 2 | Grouping ledger (§1) | highest churn, unlocks §3 |
| 3 | Socket knowledge (§5) | small, latent bugs |
| 4 | Compat rule table (§7) | builder and picker disagree today |
| 5 | Product lookup on the site (§8) | pid aliases ignored on 4 pages |
| 6 | Identity case catalogue (§6) | QA tool mishandles identity kinds |
| 7 | Merge evidence and veto (§3) | needs §1 |
| 8 | Spec resolution (§4) | large, byte-identical refactor |
| 9 | Site data contract + roster (§9) | reduces `i18n.ts` churn |
| 10 | Publish run out of YAML (§10) | smallest slice only |

## 0. Product id length (done 2026-11-09)

305 of 4,409 shipped product ids were longer than 80 chars (max 141), and
`site/src/lists.ts` rejected any id over 80, so builds holding those parts
could not be saved as short links. Limit raised to 200; the charset allowlist
is unchanged. Product ids are not shortened (that would rename 305 products).

## 1. Grouping ledger

New `scraper/grouping.py` owns listing→product membership inside
`match_listings`.

- Owns: assign / move one listing / absorb a product / release listings (4c
  split), the reverse index, `product_meta`, the blocked-pair veto on **every**
  move, "a manual product is never retired", a record of every retirement, and
  one alias resolver seeded from today's retirements **and** the previous
  build's listing-key→product-id map (replaces the two chain walkers
  `_remap_identity_cases` and `_carry_pid_aliases`).
- Tiers keep: evidence, order, survivor choice. `_identity_info` stays in the
  identity tier; lookups go through the resolver (replaces 4d's manual
  re-keying).
- Moving onto a retired product id raises (no silent transitive merges).
  Refused merges return "refused"; tiers skip as today. Two manual products
  never merge: refuse and print a warning.
- `match_listings` keeps its return keys. The previous catalog is still read
  from disk in `main()` and handed over as data.
- Fixes after the refactor (measured 2026-11-09): identity cases are remapped
  through pid aliases instead of dropped (1 today, the Z890 Aorus Elite
  `variant_conflict`); every retirement whose chain lands on a shipped product
  is published as a pid alias (+58, all in-run tier 5c/5b ids); tier 6 honours
  blocked pairs.
- Retirements per tier on 2026-11-09: 4b 0, 4c 0, 4d 22, 5b 2, 5c 60, 6 0.
- Gate: `scripts/check_grouping.py --self-test`.

## 2. Part-number keys, product id format, durable lookups

One module (e.g. `scraper/part_keys.py`) owns:

- **The part-number key.** Today ~9 copies. On the committed catalog they
  agree on all 5,017 distinct `mpn`/`vendor_sku` values except one rule:
  `_compact_key` and `_mpn_keys` skip the Gigabyte `GV` strip (55 values). All
  copies converge on `mpn_part_key` behaviour; if switching those two changes
  any product id in the byte-diff, keep that variant as a named exception.
  Latent divergences (URL/HTML/NFKC cleanup only in the SKU tier, `ß`/ligature
  expansion from `.upper()`, `build.py:157` stripping `gv` without a digit
  check) are settled inside the module.
- **Minting and parsing product ids** (`model:`/`mpn:`/`sku:`/`manual:`/
  singleton), used by matching, `promote_decisions`, `_disambiguate_duplicate_names`,
  `check_identity_merge`.
- **Durable lookup**: every store keyed by product id resolves an entry by
  exact id → pid alias chain → part-number keys. Measured 2026-11-09:
  - extraction cache `data/extract/products.json`: 1,107 entries, ~125 lost
    today (46 alias-only, 79 orphaned) because the store never follows pid
    aliases;
  - `data/specs/overrides.json`: 3, recovered by the part-number fallback;
  - `data/matching/qa_dismissed.json`: 2, both dead (exact-only);
  - golden fixtures: no alias step (anchors still resolve all 13).
- The site gets an explicit `sku` field so `utils.ts` stops splitting ids.
- Legacy manual ids (`case:antec:…`) rank like singletons in `_pid_rank`;
  the ledger's manual rule (by `matched_by`) protects them instead.

## 3. Merge evidence and veto

One module answers, for listings or groups: what evidence ties them (model
code, manufacturer part number, retailer-SKU bridge, EAN, verified maker code)
and what vetoes them (variant axis, two manufacturer part numbers, hard spec
conflict, blocked pair). Replaces the per-tier predicates
(`variant_subgroups`, `part_number_subgroups`, `_split_packaging_subgroups`,
`critical_conflict`, `_model_token_conflict`, `_codes_differ`/`_VARIANT_TOKENS`).
Tiers keep only the order of asking. Check I1 is rewritten against this
relation; I2 and I3 stay independent so the checker is not grading itself.
Fixture pairs from `docs/duplicate-groups-audit.md` (245K vs 245KF, Z890 Elite
vs Plus, GX870 vs …WIFI7I, PF120 single vs 3-pack, KSP 340400/340404) are the
self-test.

## 4. Spec resolution

One module resolves one product: (product, its listings, a list of source-tier
adapters) → specs, spec sources, spec conflicts, issues, gaps. It owns the
ordering (provisional merge → anchors → final merge → fill → cross-check →
infer → cross-check) and the precedence policy (tier order, public names with
fuzzy reference kept distinct, the `model`/`wireless`/GPU-memory rules),
replacing `merge._rank`, `validate._TIER_ORDER` and `backtest_rules._TRUSTED`.
The mfr / icecat / xref / extract / reference stores become adapters of one
shape; "without Icecat" is a shorter source list, not `MIFRAT_NO_ICECAT`.
`backtest_rules.py` and `audit_reference_matches.py` become ordinary callers
(no private imports, no monkeypatching). Byte-identical refactor.

## 5. Socket knowledge

One module knows sockets: recognising one in text, canonical spelling, valid
shape, chipsets and memory type. Its tables are stored in canonical spelling;
`text`, `canon`, `validate`, `derive`, `title_parse`, `weak_vendor` and the KSP
tag map read from it (also removes the `canon → title_parse` import cycle).
Fixes (latent, no current product affected, verify 0 catalog delta):

- `canon_socket("LGA2011-v3")` returns `LGA2011` (confirmed), so an X99/C612
  title loses its chipset in `cross_check`. Canonical: `LGA2011-3`.
- `fill_derived` upper-cases the socket before looking up `SOCKET_MEMORY`, so
  `sTR5`/`sWRX8`/`sTRX4` never match.
- Plain `LGA2011` is DDR3 (`SOCKET_MEMORY` says DDR4; `CHIPSET_INFO["C602"]`
  and `canon` say DDR3).

## 6. Identity case catalogue

One module defines each case kind (`identity_merge`, `packaging_conflict`,
`variant_conflict`, `split_candidate`, plus the duplicate-vendor and naming
cases): its fields, one offer shape, and the action that resolves it. It owns
emission, remapping through pid aliases (§1 resolver) and the per-kind cap for
publication. `site_data` stops re-deriving the duplicate-vendor and naming
cases. `qa_tool` reads the uncapped list from `data/catalog.json` (today it sees
500 of 1,172 `identity_merge` cases) and offers per-kind actions:

- `identity_merge`: split = blocked pairs between the merged-from listings
  and the rest of the product;
- `variant_conflict` / `split_candidate`: confirm as separate (dismiss) or
  manual merge;
- `packaging_conflict`: confirm or undo the move.

Today's generic split blocks every pair inside one product, which is wrong for
the identity kinds.

## 7. Build compatibility rule table (site)

One table in `site/src/build.ts`: each rule names its two slots, how it
evaluates, and a severity. The builder summary, the "passed" list, the picker
filter and the implied filter values all derive from it; `i18n.ts` keeps only
the message text keyed by rule. Severity policy: an **error** means the part
does not work in this build and hides it in the picker; a **warning** is shown
and never hides. Today the two copies disagree. Aligned values:

| Rule | Severity |
|---|---|
| cooler socket support | error (was: warn in builder, hidden in picker) |
| radiator / cooler fits the case | error (same) |
| RAM speed above board/CPU support | warning (was: hidden in picker) |
| PSU vs GPU, PSU headroom | warning (unchanged; picker never used them) |

`site/test/build.test.ts` moves over; new test: builder verdict and picker
filter agree for every rule.

## 8. Product lookup on the site

One module next to `api.ts` turns product ids into products: index lookup,
fetch only the category files it needs, follow pid aliases, report missing ids
the same way everywhere. Replaces the six copies in `category/data.ts`
(`loadBuildParts`), `builder/parts.ts` (`findProduct`), `homeBuild.ts`,
`saved.ts`, `compare.ts`, `product/index.ts`. Today only the builder and the
product page follow pid aliases; saved parts, saved builds, compare, the home
build card and the category compat context silently drop retired product ids.
Vitest with fixture JSON.

## 9. Site data contract and roster

Extend `scraper/specs/export_site.py` (which already generates
`specSchema.generated.ts`) to also generate:

- payload types for product, offer, index row, meta, QA case and spec report,
  from Python declarations next to `site_data.py` (fixes drift such as
  `label_gaps` missing from `SpecReport`);
- the QA kind list;
- the site category map (`aio`/`cooler_air` → `cpu_cooler`), used by
  `site_data`, `build_price_history`, `check_publish_set` and `state.ts`
  instead of four copies;
- a roster with one entry per category (label, icon key, build slot, menu
  placement, variant keys, legacy aliases) and per vendor (label, monogram,
  colour token, active, home or cloud vendor).

`i18n.ts` keeps only UI strings. `check_spec_sync.py` becomes the drift gate
for all of it.

## 10. Publish run out of workflow YAML (smallest slice only)

Only two pieces, the rest deferred:

- the post-normalize cover backfill reports what it fetched as an exit code or
  return value; the "re-normalize if anything was fetched" rule stops grepping
  `downloaded [1-9]` in the log;
- one `scripts/run_checks.py --suite publish|code` used by both
  `normalize-and-deploy.yml` and `site-checks.yml`, preserving the golden
  0/2/1 exit-code contract.

`REQUIRE_CLEAN_TREE`, the narrow publish paths passed to
`git_commit_push.sh`, and the night window stay exactly as in `decisions.md`.

## Not chosen

- Moving naming out of `matching.py` (2,600 lines): revisit after §1/§4 settle
  where validated specs are available; today names are built twice.
- Pipeline-wide pytest: the `--self-test` convention is kept.
- Shortening product ids: rejected in §0 (rename cost).
