# Previous-findings reassessment — partial

All historical JSONL rows are indexed in [previous-instance-anchors.json](reproduce/previous-instance-anchors.json). Retired ids resolve through current listing keys and aliases, never reconstructed slugs. Anchor existence is not resolution of a finding. Historical prose counts sometimes exceeded their JSONL; those unenumerated historical instances remain unverified.

| Current reassessment | Evidence and later fix |
|---|---|
| A/A2 wrong-variant merges: partially resolved | Two-PN splitter/I4, title axis QA, sibling narrowing in current identity.py; gates pass. Remaining 27 visible same-vendor products still need physical variant adjudication. Flagging is not proof the underlying merge is fixed. |
| D CPU Box/Tray: resolved for rule regression; residual evidence ambiguity accepted | Current title/attribute/maker/default basis; copied C-code removed in 317c703d. I6 passes. Same-code G4400/A10 candidates rejected as unsafe merges; default Box is identity-only and QA, not a sourced packaging spec. |
| E newest observation: price-selection fix resolved on pinned inputs; Nano rollout unverified | check_snapshot_rows passes; TMS latest snapshot still contains two sessions. Marker code fixed (02b9d084) but no Nano deployment state inspected. Old raw remains immutable. |
| H conditional/sale prices: core fixes resolved on pinned publish set | 234 bundle offers retained and conditional gates pass; sale repair deployed locally, tile_parser2 not proven on Nano. No wrong shown sale price inferred from older flags. |
| P twins: partially resolved | 53 aliases now suppressed; 27 products still visibly repeat a vendor; both can contain wrong variant specs. Cross-product residual splits RC-004. |
| I categorization: prior classifier fixes present; full physical census incomplete | is-a/anchored-inclusion rules f969553c and category gates pass; all historical anchors mapped below. KSP SO-DIMM scope discrepancy and adapter/SSD cooler side finds need policy/source adjudication. |
| F/G chipset/threads/GDDR fixes: largely resolved, residuals not all adjudicated | New invariants/witness pass. H81 null, single-source cache conflict and title-versus-detail 5080/5060 Ti remain evidence checks, not assumed resolved. |
| J text hygiene: resolved by current full corpus gate | 02b9d084, all strings/keys gate passes. |
| N brand repair: partially resolved / new projection omission | product.brand repaired, but 8 products retain chip manufacturer spec/name (RC-002). Existing gate checks brand only. |
| M enum/schema: fixes present; residual validation whitelist gap | chipset/socket/2U/SSI-CEB/x4 changes plus schema misses gate pass; sourced5066 MHz is still refused (RC-003). |
| O count parsing: fixed cases/latent fixtures pass; broader semantics unexamined | Decimal guards in 317c703d do not fix RPM tolerance; RC-001 confirms old lane05 RPM suspicion and new case_fan affected instances. |
| K extract routing: resolved for aliases, residual semantic verification risk | f4ccf0e7/set_run_aliases + check_extract pass, 17 unreached entries <=25. Pump quote can verify as fan speed; most flagged claims untrusted and safely inert. No trust expansion recommended. |
| L ledgers: accepted retained budgets / partial | Empty overrides; orphan enrichment/detail/images budgets pass. Future refresh remains limited to newly missing detail, no age/version queue. |
| V pending live checks: still unverifiable | 1PC206013 price jump, TMS query links, BW025767 CFM, Hyper212height25, Zalman60MM cannot be confirmed by outlier alone. Environment/source eligibility not established; zero live requests. |

## Every historical emitted family

| Lane / family | Historical rows | Current anchor-linked rows | Status |
|---|---:|---:|---|
| 01 / R-1 | 58 | 58 | intentional/accepted historical rejection |
| 01 / R-2 | 18 | 0 | intentional/accepted historical rejection |
| 01 / R-3 | 1 | 0 | intentional/accepted historical rejection |
| 01 / S1-1 | 22 | 22 | partially resolved / individual re-adjudication remains |
| 01 / S1-2 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 01 / S1-3 | 4 | 4 | partially resolved / individual re-adjudication remains |
| 01 / S1-4 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 01 / S2-4 | 18 | 18 | partially resolved / individual re-adjudication remains |
| 01 / S2-5 | 37 | 37 | partially resolved / individual re-adjudication remains |
| 01 / S3-6 | 63 | 63 | partially resolved / individual re-adjudication remains |
| 01 / S3-7 | 6 | 6 | partially resolved / individual re-adjudication remains |
| 02 / F-01 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-02 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-03 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-04 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-05 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-06 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-07 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-08 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-09 | 4 | 4 | partially resolved / individual re-adjudication remains |
| 02 / F-10 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-11 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-12 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-13 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-14 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-15 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-16 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-17 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-18 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-19 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 02 / F-20 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-21 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 02 / F-22 | 1 | 0 | disappeared/unverifiable |
| 02 / F-23 | 1 | 0 | disappeared/unverifiable |
| 03 / F1 | 5 | 5 | partially resolved / individual re-adjudication remains |
| 03 / F10 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 03 / F11 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 03 / F12 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 03 / F13 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 03 / F2 | 4 | 4 | partially resolved / individual re-adjudication remains |
| 03 / F3 | 4 | 4 | partially resolved / individual re-adjudication remains |
| 03 / F4 | 6 | 6 | partially resolved / individual re-adjudication remains |
| 03 / F5 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 03 / F6 | 3 | 3 | partially resolved / individual re-adjudication remains |
| 03 / F8 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 03 / F9 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 04 / S1-brand-empty-name-has-brand | 110 | 105 | partially resolved / individual re-adjudication remains |
| 04 / S1-chipset-dropped-by-socket-rule | 12 | 12 | partially resolved / individual re-adjudication remains |
| 04 / S2-best-offer-null-price-missing | 81 | 81 | partially resolved / individual re-adjudication remains |
| 04 / S2-chipset-code-not-in-schema | 4 | 4 | partially resolved / individual re-adjudication remains |
| 04 / S2-vendor-value-accepted-alone-product-null | 19 | 18 | partially resolved / individual re-adjudication remains |
| 04 / S3-image-null-offer-image-blocked | 5 | 5 | partially resolved / individual re-adjudication remains |
| 04 / S3-model-null-specs-has-model | 1 | 1 | partially resolved / individual re-adjudication remains |
| 04 / S3-value-rejected-by-validator | 64 | 62 | partially resolved / individual re-adjudication remains |
| 05 / F01 | 5 | 5 | partially resolved / individual re-adjudication remains |
| 05 / F02 | 4 | 4 | partially resolved / individual re-adjudication remains |
| 05 / F03 | 5 | 5 | partially resolved / individual re-adjudication remains |
| 05 / F04 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 05 / F05 | 3 | 3 | partially resolved / individual re-adjudication remains |
| 05 / F06 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 05 / F07 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 05 / F08 | 2 | 2 | partially resolved / individual re-adjudication remains |
| 05 / F09 | 1 | 0 | disappeared/unverifiable |
| 05 / F10 | 3 | 3 | partially resolved / individual re-adjudication remains |
| 05 / F11 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 05 / F12 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 06 / 06-F1 | 206 | 206 | partially resolved / individual re-adjudication remains |
| 06 / 06-F2 | 67 | 67 | partially resolved / individual re-adjudication remains |
| 06 / 06-F3 | 42 | 42 | partially resolved / individual re-adjudication remains |
| 06 / 06-F4 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 06 / 06-F5 | 40 | 39 | partially resolved / individual re-adjudication remains |
| 07 / F1 TMS two crawls in one raw day file; catalog price from older crawl where newest is higher | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F1 TMS two crawls: catalog keeps older lower price where newest is higher (25 keys) | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F2 TMS in-run dedupe keeps lowest price across crawls, no log line | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F3 product holds two offers from same vendor (flagged) | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F3 product holds two yahav offers, not flagged | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F4 HTML entity &#39;&#39 left in product model text | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F4 Ivory title_raw keeps &#39; entities (99 rows) | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F5 U+200E in yahav vendor_sku and mpn | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / F6 NBSP and RLM marks in raw titles | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / S-a KSP cooler tag claim order changes category (latent) | 1 | 0 | disappeared/unverifiable |
| 07 / S-b TMS keys present in only one crawl | 1 | 1 | partially resolved / individual re-adjudication remains |
| 07 / S-c detail specs disagree between duplicate rows (Ivory 2 SKUs, 1PC 1 SKU) | 1 | 0 | disappeared/unverifiable |
| 08 / F1 | 28 | 28 | partially resolved / individual re-adjudication remains |
| 08 / F10 | 1 | 1 | partially resolved / individual re-adjudication remains |
| 08 / F11 | 1 | 0 | disappeared/unverifiable |
| 08 / F12 | 1 | 0 | disappeared/unverifiable |
| 08 / F2 | 21 | 21 | partially resolved / individual re-adjudication remains |
| 08 / F3 | 16 | 16 | partially resolved / individual re-adjudication remains |
| 08 / F4 | 1 | 0 | disappeared/unverifiable |
| 08 / F5 | 1127 | 1109 | partially resolved / individual re-adjudication remains |
| 08 / F6 | 1 | 0 | disappeared/unverifiable |
| 08 / F7 | 1 | 0 | disappeared/unverifiable |
| 08 / F8 | 1 | 0 | disappeared/unverifiable |
| 08 / F9 | 1 | 1 | partially resolved / individual re-adjudication remains |

## Duplicate-groups audit R1–R7
R1/R3/R4/R6 implemented in current model fallback/PN union/verified-code/tail paths; residual all-letter PN bridges RC-004 partially escape R3. R2 noise/axis stripping is an explicitly rejected proposal (2 merges vs322 renamed ids), not a missing fix. R5/R7 remain intentional QA-only variant separation. Current missing-code/multi-vendor/title scans do not imply blanket merging. Full per-original-group live adjudication remains unfinished.
