# Duplicate fixes: handoff

State as of 2026-11-08. The duplicate-fix audit (`docs/duplicate-groups-audit.md`)
has been worked through root cause by root cause. Everything below is verified
locally: `check_identity_merge.py` exit 0 (also under several
`PYTHONHASHSEED`s), `check_publish_set.py` pass, `report_identity_delta.py`
clean, `npm --prefix site run build` green.

## What is done

| Root cause | Change | Where |
|---|---|---|
| R6 | `-PC` tail is a bundle marker, not a maker suffix (`apply_bundle_mpn`, also run after detail-spec merge) | `scraper/matching.py`, `scraper/normalize_and_match.py` |
| R1 | `model_code` falls back to the title, accepts 3-char codes when the brand is known, sorts code tokens | `scraper/identity.py` |
| R4 | `GX/GZ/GB/BK/BL` maker prefixes, prefix test before retailer shapes, one-sided 1-char affix guard | `scraper/identity.py`, `scraper/matching.py` |
| R3 | maker-shaped vendor SKUs join the identity tier as `("pn", category, key)` | `scraper/identity.py` (`sku_part_number_key`), `scraper/matching.py` |
| R2 | **measured, then rejected** — see below | — |
| R5, R7 | deliberately **no merge** — QA only | — |

Products 4459 -> 4397, listings unchanged (7080 after the 2026-11-08 snapshots).

## R2: measured, not applied

Two variants were built and run end to end.

**(a) The audit's safe subset** (`series case tower fan fans cooler aio liquid
cpu kit pack` + size tokens + `dimm`/`ddr`):

- products 4397 -> 4385 (-12: aio -6, cooler_air -3, gpu -2, case -1)
- **breaks I1 on 3 products.** The matcher had bridged offers by evidence the
  shipped offers do not carry (one vendor lists a part with and without `RGB`
  in the model row; another lists it with no MPN at all), so a product ends up
  holding two code groups nothing connects, e.g.
  `240-icue-link-rgb-rx-titan-240mm-white` vs `240-icue-link-rx-titan`.

**(b) The noun-only subset** (`series tower case kit pack`, no
`aio`/`cooler`/`cpu`/`fan`, no sizes):

- passes I1 and I2, products 4397 -> 4395 (one AIO, one case)
- but renames **322 product ids** (391 new alias entries) to gain 2 rows.

The audit's 38-group estimate for R2 predates R1/R3/R4; with those landed the
marginal yield is negligible against the URL churn. `_MODEL_NOISE` therefore
stays at the original ten words. If R2 is ever revisited, fix the I1 cause
first: a product must not contain an offer whose only tie to the rest exists
inside the matcher and not in the shipped offer attributes.

## The I2 flake (fixed 2026-11-08)

Symptom: `check_identity_merge.py` passed under some `PYTHONHASHSEED`s and
failed under others:

```
[fail] I2: motherboard / aorus-elite-wifi7-z890 held by 2 products
       ['model:motherboard:1851-7-aorus-...-z890-atx',
        'model:motherboard:aorus-elite-wifi7-z890-atx']
```

Two causes:

1. The cross-group collision sweep ran **inside** `match_listings`, before
   reconciliation. Tier 5b (code merge) moves offers between pids afterwards, so
   the base board's TMS offer (no `form_factor`) sat alone under a 3-axis key
   pre-merge, while the shipped product inherits `atx` from the Yahav offer and
   matches the Plus board's 4-axis key. Matcher and checker were reading two
   different groupings.
2. The checker's `max(set(codes), key=codes.count)` tie-break depends on hash
   order whenever a product's offers spell the code two ways (that pid tied 1-1).

Fix: the sweep is now `matching.flag_identity_collisions(products, existing)`,
called from `normalize_and_match.build_catalog` **after** the spec merge. It
registers each product under every code it carries (a tie cannot hide a
collision) and flags both sides of a differing-manufacturer-PN collision. The
old in-matcher block is a pointer comment.

Same pass also removed 11 QA cases that named pids the catalog no longer ships
(10 `identity_merge`, 1 `variant_conflict`): cases are remapped through
`pid_aliases` (full chain) and dropped when the survivor is gone.

## Alias chains (fixed 2026-11-08)

A fresh normalize emitted 1549 alias entries whose chain ended at a pid a later
tier had already retired — a bookmark would redirect to nothing. `_absorb`
writes the alias when it retires a pid, and that target can itself be absorbed
later, so `_carry_pid_aliases` now keeps a chain only when its last hop is in the
shipped product set. Aliases 8520 -> 6971, dangling targets 1549 -> 0 (the
committed catalog carried 69 of them).

## Current catalog facts

- 4397 products, 7080 listings, 1288 identity cases, 6971 pid aliases.
- `matched_by`: identity 4245, singleton 76, manual 51, mpn 24, sku 1.
- Under the checker's own key derivation: 15 duplicate groups / 30 products; 14
  flagged, and the one "silent" pair (`case:lian-li:a4-h2o-pcie4` vs
  `a4-h2o-silver`) is two **manual** products with different maker PNs
  (`PC-A4H2OA4` vs `A4H2OA5`) — a real colour variant, correctly separate. So:
  0 real unflagged duplicates.
- KSP raw is the 2026-11-07 snapshot (923 listings).

## Gotchas

- `decisions.md` is gitignored (`.gitignore:28`) — recording there is local only,
  by owner instruction.
- Do not append to `decisions.md` through PowerShell double-quoted strings: a
  backtick is an escape there (`` `n ``, `` `r ``, `` `a `` silently corrupt the
  entry). Write the text with a file-editing tool instead.
- `tmp/` scripts shadow stdlib `inspect` on `sys.path`; run with `python -P` if
  one imports `matching` and blows up on `inspect`.
- Normalize takes ~290 s; don't kill it halfway, the catalog and `data/site/*`
  must come from one run or `check_publish_set.py` trips.
- `scripts/git_commit_push.sh` only publishes an explicit path list; anything
  else changed in the tree is stashed and discarded after a rebase.
- Probes that reproduce the numbers: `tmp/sweep_measure.py`,
  `tmp/remaining_dups.py`, `tmp/dangling.py`, `tmp/alias_targets.py`,
  `tmp/r2_churn.py`.
