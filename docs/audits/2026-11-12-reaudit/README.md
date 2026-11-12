# Full-catalog re-audit — PARTIAL checkpoint

**Audit only; no production fixes applied. Stop for owner review before implementation.**

## Outcome

Four confirmed root-cause families affect **42 unique products / 50 listing keys**. There are **83 distinct observation-level instances** (listing-level and product-level spec failures are separate records, not additive product counts). **25 products** have confirmed buyer-facing S1 projection/spec errors. No unusual price, similar title or passing gate is treated as correctness proof.

| Priority | Family | Confirmed impact | Durable fix boundary |
|---|---|---|---|
| 1 | RC-001 — RPM tolerance parsed as speed | 71 listing/product-field instances, 27 products / 27 listing keys. ±10% becomes minimum10RPM; a source900–1800 can ship10–900. Broad range bounds/backtest pass. | RPM-specific endpoint/tolerance grammar; preserve explicit0; lone maximum does not state a minimum. Full raw-to-fact gate. |
| 2 | RC-002 — partner repair leaves stale spec/name | 8 products / 15 listings. Product.brand repaired to partner, but GPU/board manufacturer specs and names still NVIDIA/AMD. | Resolve partner before final name/spec/legacy projection; preserve legitimate official chip-maker cards. |
| 3 | RC-003 — real sourced profile refused | KSP148642 Ripjaws5066: `speed_mhz=null` while speedDDR4-5066 and latency7.9 remain. | Review sourced profile whitelist, consistent speed-field validation, no guessed profiles. |
| 4 | RC-004 — all-letter manufacturer-code bridges missed | 3 split groups / 6 products / 7 listing keys: FLUX-PRO, CXMIRROR, ERA-ITX-BU. TMS SKU equals other-vendor printed identifier but digit-required bridge refuses. | Corroborated exact category+brand+physical-axis bridge; not blanket fuzzy/noise merges. Pid/history preservation required. |

Expected values for RPM come from exact cached detail wording excluding tolerance, not model memory. For lone RPM rates the unsupported minimum should be unknown, not an invented lower bound. The split claims include exact bridges and dimensions/axes; no rule prototype was applied to production and post-fix catalog/price/id impact is **unmeasured**. Recommended merge/split and S1 claims received fresh coordinator reconstruction only; **independent review unavailable**.

## Pinned baseline

- Repository `D:\Mifrat`; HEAD/localmain/localoriginmain `e7cd95223d684cbbdfe72cc2ca76ef568451e963` at pin. No pull/fetch/checkout/commit/push/deploy/issues. Remote freshness unknown.
- Catalog built `2026-11-12T12:22:28.077467+00:00`; effective comparison date2026-11-12UTC. Schema3 from source, **catalog has no schema-version key**.
- Immutable scratch archive plus local decisions and available pcpartdb/pckombo JSON inputs; 7405input files hashed. Existing `docs/prompts/` preserved. Manufacturer page caches were not included in immutable git archive; stored facts are pinned, uncaptured source wording remains a limitation.
- Inputs: TMS 11-11 (latest 21:36:47 UTC), other four 11-12; no newer dated snapshot beyond build-day selection. All 7075 catalog keys accounted for from 9296 selected rows, 2221 duplicates. Saved TMS day holds two sessions; latest-row gate passes, Nano code rollout unproven.

## Coverage actually achieved

- 4402products,7075listings,12pipeline categories/11sitecategories,50manualproducts,1869multivendorproducts,2479one-listing singletons,53aliases;27products visibly repeat a vendor. No bucket excluded by QA dismissal, accessories, other, already-multi or lack of brand.
- Exact per-product/per-field schema applicability:92439applicable cells,67338filled,25101null. Null does not mean bug; recoverability/source omission remains unverified for most.
- 30offline workflowdiagnostics against scratch:29exit0, goldenexit2(identitychurnonly;10of13fixtures resolve via anchors). No real gatefailure; Python3.14local vs3.12CI is recorded. Ref refresh/download/build/publish not invoked. All actual command logs in manifest/reproduce/gates.
- 4661initial heuristic candidates plus audit-instance/policy registrations; **4745 registry records total, 4629 unresolved**. These records overlap and are NOT unique defects. Every candidate has a disposition, but thousands have not been individually adjudicated.
- All4402publishedproducts/specs and8760image refs mechanically checked, no observed specprojection mismatch or missing reference; **0visually verified images,0live pages**. 3656reachableextractclaims/2010entries inventoried;17unreached. Historical JSONL anchors all indexed, family-by-family source reassessment incomplete.

## Important unsettled cases / accepted limits

- 1PC213833 title5060Ti8GVENTUS2X versus cacheddetail5080INSPIRE16G/catalog5080+8GB: wrong-source/join direction unknown; requires exact public-source identity verification, not a guessed correction.
- BW025airflow767CFM, Hyper212height25mm, Zalman60mm and KSP/other residualaxes remain leads, not confirmed physical values without original/live wording.
- KSP detail stays blocked/listingonly. README/code permits429retry4x while bindingstop rules are stricter; this audit uses zerotraffic/stricterstop. No banned-source reprobe, browser workaround, APIusage or fullscrape.
- Manufacturer truth/variant joins, fullhistoryreplay, vendorlivecensus, detailage/refresh, rarepartaxis and visually wrongcovers remain incomplete. No missing-vendor-listing census count claimed.
- Existing raw two-sessionTMS snapshots, staleTMSoffers, nullrequestprices, retainedmanual/orphanledgers, Box/Tray default uncertainty and untrusted extraction facts are not newly invented current defects. R2 blanketnoise stripping remains explicitly rejected.

## Reports and evidence

[Manifest](manifest.json) · [Coverage](coverage.json) · [Findings](findings.jsonl) · [Candidate registry](candidates.jsonl) · [Gap inventory](spec-gaps.jsonl) · [Rejections](rejected.jsonl) · [Previous fixes](previous-findings.md) · [Progress/resume](progress.md) · [Reproduce](reproduce/)

Lane files01–08 document methods and limitations. Exact unique/instance totals are recomputed in `reproduce/finding-totals.json`; examples are illustrative. **This is not a completed audit or a guarantee of no other defects.**
