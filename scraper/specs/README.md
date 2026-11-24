# Typed, tiered specs

One fixed schema per category; `null` means unknown. Facts are typed at the
boundary, merged by trust, validated and reported. This is the current guide;
[the preserved long reference](../../docs/archive/2026-11-22/specs-README.md)
contains historical parser examples and coverage measurements.

## Where to change behaviour

| Area | Owner |
|---|---|
| Fields, units, enums, applicability, filter/display metadata | `schema.py` |
| Canonical spelling and typed coercion | `canon.py`, `values.py` |
| Vendor labels and structured cells | `labels.py`, `resolvers/vendor_struct.py` |
| Title/SKU readers | `text.py`, `resolvers/title_parse.py` |
| Fact ranking and conflict records | `merge.py` |
| Packaging evidence and title witnesses | `witness.py` |
| Cross-field checks and derived-value validation | `validate.py` |
| Evidence-backed inference and lookup tables | `derive.py`, `tables/` |
| Product orchestration / external API | `build.py`, `api.py` |
| Transitional attributes / frontend schema export | `legacy.py`, `export_site.py` |
| Coverage, label gaps, schema misses and QA | `report.py` |

## Build order

`build_listing_attributes` supplies derived attributes for matching.
`build_product_specs` builds the authoritative product sheet:

1. Collect per-listing vendor/title/weak facts and the computed identity bridge.
2. Provisionally merge those facts to anchor reference matching.
3. Add reference, manufacturer, Icecat, xref, extracted facts and overrides.
4. Merge and check the product's own titles against the result.
5. Fill derived values, cross-check, infer only missing values, validate
   inference, witness newly inferred fields and cross-check again.
6. Store full `specs`, provenance and the derived `attributes` view; report
   conflicts, refused values, label gaps and coverage.

The order is a contract: inference must not preserve a contradictory value or
escape validation. Public category JSON omits nulls for size; `site/src/api.ts`
re-expands the schema on load. New public fields also need the `site_data.py`
trimming allowlist.

## Source trust

| Tier | Source | Detail guide |
|---|---|---|
| Override | Cited human correction, highest priority | `data/specs/overrides.json` |
| 0 | Verified reference rows / exact part-number dataset | `resolvers/reference.py` |
| 0.5 | Manufacturer product pages | [Manufacturer sources](../mfr/README.md) |
| 0.75 | Open Icecat sheets, field-level trust gated | [Icecat](../icecat/README.md) |
| 1 | Vendor structure, detail tables, computed bridge, exact xref | `resolvers/vendor_struct.py`, `scraper/xref/` |
| 1.5 | Quoted, audited extraction from own listings | [Extraction](../extract/README.md) |
| 2 | Typed title/SKU readers | `resolvers/title_parse.py` |
| 3 | Weak vendor prose, fill-only | `resolvers/weak_vendor.py` |

Lower tiers never overwrite higher ones. Equal-tier conflicts retain the
higher-confidence value and record both for QA. Overrides still obey schema
validation and must be sourced and change output. Explicit negatives use
"No", not "None" (a placeholder for unknown). Values inapplicable to a product
are not coverage gaps.

QA automation uses optional `Fact.evidence` from cached manufacturer sheets:
match method/key, source URL, typed-sheet fingerprint, field meaning/unit and
origin. Missing metadata retains normal source ranking but grants no automatic
closure authority. `resolution.py` owns the off/shadow/enabled rollout; only
exact-key fan-performance facts are in its first rule family. Final identity
flags, equally qualified contradictions and invalid/changed final values keep
cases open. Automatic decisions recompute each build and never write the human
dismissal ledger. Strict comparisons preserve explicit negatives, vector order
and meaningful model suffixes; only declared set fields ignore ordering.

### Reference identity

An authoritative spec is unsafe if linked to the wrong product. Joins require
exact names or a constrained fuzzy/identity match with brand agreement,
distinctive model tokens and hard structured anchors. At least one anchor
must agree and none may contradict. Ambiguous different-name ties are refused;
same-name variant rows contribute only values they all share. Non-exact
variant facts (colour, lighting, efficiency, modularity) rank below titles at
tier 2.5. Missing reference data reduces coverage, not correctness.

After changing a join, run `python scripts/audit_reference_matches.py`; it
normalizes in memory and writes its report under ignored `tmp/`.

### Witnesses, packaging and inference

- Title witnesses may replace a contradicted value only with at least two
  independent sources; one produces QA. An override is never replaced.
- CPU packaging follows the listing's title, then its attribute, then maker
  part number, else Box + QA. A copied retailer C-code is not evidence.
  Default Box is identity-only, not a sourced spec.
- Inference fills nulls only, marks `derived:<rule>` and must have lineup,
  platform, curated-table or explicit evidence—not an assumed per-SKU value.
  Run `scripts/backtest_rules.py --check` when changing inference.
- CPU socket/generation memory-limit inference is quarantined: unsupported
  exact models stay unknown; sourced and curated values remain. The rejected
   candidate is still measured, labelled `[quarantined]`, by rule-health backtests.
   Its disagreements remain diagnostic, not active-rule regressions; re-enabling
   the rule subjects its actual predictions to the unchanged regression test.
- Curated tables must state only facts invariant for their anchor; variant
  ambiguity stays empty. `scripts/fill_report.py --check-tables` measures them
  against sourced catalog facts.

## Vendor detail and missing fields

`labels.py` translates category-aware labels. A cell may expand into several
fields via action tokens; use `labels._is_token()` rather than inventing a
prefix allowlist. English relaxed matches require unambiguous contained
tokens; Hebrew labels need explicit vocabulary. Clean Hebrew units/booleans,
but refuse surviving prose that could invert meaning. Retailer SKU rows are
not manufacturer part numbers.

Unmapped labels remain `label_gaps` evidence. Bookkeeping with no spec meaning
is explicitly ignored; unsupported facts need a schema decision before a new
reader. Enum refusals become `schema_misses`, not silent losses.

Detail ledgers mean **usable specs on disk**, not merely "visited once".
Missing/empty detail results remain pending. Use the bounded source runner and
the [root scraping rules](../../README.md#scraping-rules), not an arbitrary
backfill. Historical selector failures and label examples are in the archive.

## The transitional attributes view

`legacy.to_attributes()` derives compatibility/legacy aliases from `specs`.
It is not a separate authority. Consumers are migrating at different rates:
inspect the consumer before removing an alias, and retire the view only when
all readers have moved to typed specs.

## Adding or changing a spec field

1. Edit `schema.py`: name, type/unit, enum/range, aliases, applicability,
   filter/display flags and Hebrew/English labels.
2. For a breaking change, bump `SCHEMA_VERSION`, update golden schema version,
   add/run `scripts/migrate_mfr_schema.py`. Manufacturer files at another
   version are skipped; migration is necessary to retain those facts.
3. Teach the relevant resolver to emit the field.
4. Run `python -m scraper.specs.export_site`, then
   `python scripts/check_spec_sync.py`.
5. Verify reader/merge/inference fixtures and an isolated normalize. Frontend
   labels, filter metadata and sheet order come from the schema export.

## Golden fixtures

Resolution tries the fixture's own product id first, then append-only historical
ids, listing keys, part numbers and manufacturer/model anchors. A live own-id
with wrong values is a regression; another sibling must not rescue it.
Expected part numbers use containment, not equality.

Raw exits are `0` clean, `2` identity churn only, `1` failure. **The central
runner treats golden exits 1 and 2 as quality warnings**, not publish blockers.
Separate population integrity checks protect empty/collapsed catalogs. Resolver
and self-test failures remain blocking code checks. The declared levels in
`scripts/run_checks.py` are authoritative, not historical workflow descriptions.

After normalize, an independently reviewed repair can append anchors only for
cases passing their own expectations (CI never writes fixtures):

```bash
python -m scraper.specs.golden.check_golden --update-anchors         # preview
python -m scraper.specs.golden.check_golden --update-anchors --apply # approved write
```

Repairs refuse a catalog older than three days unless explicitly forced; old
anchors remain. `--baseline <catalog>` checks population, `--strict` makes
missing fixtures fail. Thresholds and budgets live in the checker itself.

## Verification

```bash
python scripts/diagnose_spec_coverage.py  # fast offline gap/fill view
python scripts/run_checks.py --suite code
npm --prefix site test
npm --prefix site run build
```

For behaviour changes, also normalize and run the publish suite in an isolated
environment. Its quality warnings are evidence to investigate, not reasons to
raise budgets or weaken fixtures. [Project verification](../../PROJECT_OVERVIEW.md#11-how-to-verify-changes)
explains the code/integrity/quality split.
