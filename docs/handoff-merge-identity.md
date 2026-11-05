# Handoff — merge-identity rework (DONE 2026-11-06)

Status: **DONE 2026-11-06 — every handoff step green. Ready to commit/push.**
Branch: `main` (uncommitted changes on top of `01baacc2 normalize: catalog for 2026-11-05`).
Everything below is the audit trail (verified this session; see
`scripts/report_identity_delta.py` for the reproducible delta).

## Objective (from `docs/merge-identity-plan.md`, owner-approved 2026-11-04)

One physical part = one product across all 11 categories. The "245" CPU search used to show
10 rows for 3 chips; it must show **5**: `245 Tray`, `245K Box`, `245K Tray`, `245KF Box`,
`245KF Tray` (D1: Box/Tray stay two products; D2: all 11 categories in one pass;
D3: ambiguous merges are flagged on the QA page, never held in a manual queue).

## Verified right now (re-run this session, from `data/catalog.json` on disk)

- **245 = exactly 5 rows** (`tmp/probe_245b.py`):
  - `model:cpu:245-tray` n=2 — 1pc C245T, tms C245T
  - `model:cpu:245k` n=1 — ksp 340388 (Box)
  - `model:cpu:245k-tray` n=5 — 1pc 171974, 1pc C245KT, ksp 340399, tms C245KT, yahav AT807680640F
  - `model:cpu:245kf` n=1 — yahav BX80768245KF (Box)
  - `model:cpu:245kf-tray` n=6 — 1pc 171975, 1pc C245KFT, ksp 340400, ksp 340404, tms C245KFT, yahav AT8076806414
    (KSP 340400+340404 are two offers of one product, flagged `packaging_conflict`)
- Products **4,687 → 4,471** (−216), listings unchanged at 7,132. By tier:
  identity 3,711 / mpn 498 / singleton 201 / manual 51 / sku 13.
- Per-category delta vs `git show HEAD:data/catalog.json`:
  cpu 256→215 (−41), memory 572→538 (−34), case 746→714 (−32), motherboard 779→751 (−28),
  aio 295→271 (−24), psu 366→350 (−16), gpu 367→356 (−11, color-split-adjusted), storage 412→399 (−13),
  cooler_air 257→246 (−11), case_fan 540→537 (−3), accessories 73→73 (0), other 24→24 (0).
  ⚠️ Plan acceptance §5.6 says "every one of the 11 categories has a smaller product count" —
  accessories/other are not identity categories, so 0 there is expected; record the reason in decisions.md.
- `data/site/meta.json` carries `pid_aliases` (4,022 entries); `data/site/qa.json` has 1,370 cases
  with `identity_cases` = {identity_merge: 1272, variant_conflict: 40, split_candidate: 7, packaging_conflict: 51};
  `data/catalog.json` has `pid_aliases` (4,022) + `identity_cases` (1,373).
- `python scripts/check_identity_merge.py` → **exit 0** (I1: 1,841 checked; I2: 3,700; I3: 10 fixtures + 215 CPU).

## The 2 remaining failures (root causes)

### F1 — I1: `model:gpu:dual-radeon-rx-9060-xt-gddr6-16gb` — RESOLVED (matcher fix, not a checker exemption)

Root cause: ASUS Dual RX 9060 XT 16GB is sold in **two MPN variants of one model
code** — Black `90YV0LG2` and White `90YV0LG3`. The matcher's
`part_number_subgroups()` saw two manufacturer-PN clusters and attached the
no-MPN KSP pair (435010 Black + 435011 White) wholesale to the larger (Black)
cluster via "unclassified rides with the largest cluster". That merge had no
evidence edge under I1's definition, and it was physically wrong for the white card.

Fix: **`color` added to the GPU variant axes** in `scraper/identity.py`
(`gpu: ("chipset", "memory_gb", "memory_type", "color")`). Physical SKU colours
are identity, and the MPN split itself (LG2 Black vs LG3 White) proves color is
the discriminator here. With the axis present, `variant_subgroups()` placed
KSP 435010 (Black) with the LG2 triple and KSP 435011 (White) with the LG3
pair. No change to `part_number_subgroups()` was needed — the axis did the work.

Residual I1 path (real refinement, posted in decisions.md): KSP 435010's only
tie to the LG2 product is the verified maker model — one vendor prints "16GB"
in the model name, another doesn't. The checker's maker_model evidence now strips
VRAM-size tokens and pins memory_gb in the bucket key (8GB ≠ 16GB regardless).

New side effects of the color axis, measured: total products 4,471 → 4,474
(+3; gpu category delta is −11 not −14 vs HEAD — the color splits cost +3 GPU
products that the stale run had wrongly merged). QA case counts are on
`scripts/report_identity_delta.py` output. This was justified because the colors pair
with distinct MPNs (LG2 vs LG3) — a genuine SKU axis. Physical truth did not
add the assumption; it confirmed it.

### F2 — I3: `model:cpu:3240` vs `3240t` — RESOLVED (checker bug, as suspected)

Booked-point exemption looked up the `-tray`-stripped family id instead of the
real pid. Fix builds a family→real-products map (`family_products`) so the
shared-part-number exemption sees the actual offers of `model:cpu:3240-tray`.
Also: I2 now exempts `manual` products (human curator is itself the evidence,
same rationale as I1 — the Lian Li A4-H2O manual pair otherwise false-failed).

## Steps 1–7 (all green this session, in order)

1. ✅ Re-ran normalize (`python -m scraper.normalize_and_match`) — regenerated
   catalog/site from the current matcher; **4,474 products**, 245 = 5 rows, confirmed.
2. ✅ Fixed F2 (checker bug) + resolved F1 (matcher fix: GPU `color` axis; recorded above);
   `python scripts/check_identity_merge.py` → **exit 0** (I1/I2/I3 all hold).
3. ✅ Wrote `scripts/report_identity_delta.py` (P0/P7) — per-category before/after
   vs `git show HEAD:data/catalog.json` + 245 rows + QA counts (replaces ad-hoc tmp probes).
4. ✅ `npm --prefix site run build` — clean (exit 0).
5. ✅ P7: `check_golden_resolution.py` → **pass 74 checks, exit 0**;
   `scraper.specs.golden.check_golden --baseline <HEAD catalog>` → **exit 2 churn-only**
   (warnings; CI treats as warning, and the new catalog becomes the baseline once
   committed — the reviewed baseline bump). All other offline CI gates green
   (spec_sync, migrate_mfr_schema --check, tms_detail, spec_merge, categories,
   xref_fixtures, extract, backtest_rules --check, spec_coverage (+self-test),
   image_pick, image_files, site_images, site_size, publish_set (+self-test)).
6. ✅ P8: single-spider test crawl (`scrapy crawl ivory`, 647 items, exit 0) +
   local normalize + site build (AGENTS.md hygiene rule).
7. ✅ Updated `decisions.md` (GPU color axis deviation from plan §2.3, I1 VRAM
   evidence refinement, I2 manual exemption, I3 family→pid lookup fix,
   per-category deltas, meta.json alias deviation, collapse-guard baseline).

## Remaining

- Show the user the delta report (`python scripts/report_identity_delta.py`).
  **Only then commit and push to `main`** (user authorized the push once everything
  is green; nothing here is red).

## What was changed (working tree, uncommitted)

- **New**: `scraper/identity.py` (model codes, CPU `245k`≠`245kf` suffix rule, variant axes,
  part-number classes, PN-seeded `variant_subgroups`), `scripts/check_identity_merge.py` (I1/I2/I3),
  `docs/merge-identity-plan.md` (the approved plan).
- `scraper/matching.py`: identity tier (union-find over model code + any printed MPN, per-subgroup
  pids incl. singletons = D1 orphan fix), step 4d reconciliation with `_pid_aliases`/`_absorb()`
  (manual pids win, others alias), step 6 packaging-conflict resolution, `offer_from_listing`
  emits catalog-only `model_code`.
- `scraper/normalize_and_match.py`: `catalog["pid_aliases"]` + `catalog["identity_cases"]`,
  `_carry_pid_aliases()` (previous build's ids → today's, single-successor only, chains resolved).
- `scraper/site_data.py`: `meta.json` `pid_aliases`; `qa.json` identity cases (per-kind cap 500)
  + `identity_cases`.
- `scraper/build_price_history.py`: old-pid series grafted onto successors.
- Site: `api.ts` `resolveProductAlias()`, `types.ts` (`SiteMeta.pid_aliases`, `QaFile.identity_cases`,
  identity `QaCase` kinds), product page redirects stale pids, builder `parts.ts` follows aliases,
  `qa.ts` kind filters (`#/qa?kind=`), i18n keys he+en.
- Generated outputs also modified: `data/catalog.json`, `data/review_queue.json`,
  `data/site/*.json`, `data/site/history/*.json`, `data/spec_gaps.json` — these are committed
  outputs in this repo's history ("normalize: catalog for …"), so include them in the push.

## Environment notes

- Windows/PowerShell: no `&&`/`grep`; `Select-String` instead; scripts set
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` (Hebrew vendor labels).
- Credentials must never be written to any repo file or chat log (AGENTS.md hygiene rule).
- Large-file note: `data/catalog.json` and site JSONs are big; use targeted probes
  (e.g. `tmp/probe_245b.py`) rather than dumping them.
