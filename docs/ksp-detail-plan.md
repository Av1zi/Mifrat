# KSP detail ingestion

**Implemented Nov 13; currently disabled during listing recovery.** KSP remains
paused after Nov 22 rejection. Read [stream status](ksp-stream-transport.md)
before any live request. The [original Nov 9 plan and Nov 13 evidence](archive/2026-11-22/ksp-detail-plan.md)
are historical, not instructions to repeat probes or enable timers.

## Phase 2: shipped detail contract

- `scraper/spiders/ksp_detail.py` reads item JSON into append-only
  `data/raw/detail/ksp.jsonl`; `nano/run_ksp_detail.sh` runs on the home IP only.
- Bounded 150-item chunks, KSP-only products first, following the night's
  successful listing publication. No overlap, one request at a time, 3–9s
  delay. First 403/429 stops and shares the persistent pause with every phase.
- Captured rows survive a block and usable specs are marked/published before
  reporting failure. Unfetched or empty-table results stay pending. A skipped
  service is not proof of successful detail collection.
- The Hebrew `דגם` row is retained as `extra.model_row`. Normalize adopts it
  as a manufacturer part number **only when another vendor in the category
  prints that exact code**. An Intel CPU model name is not a part number.
- Spec rows pass the normal category-aware label vocabulary; unmapped labels
  remain evidence. Listing tags can fill existing schema fields without any
  new request (`scripts/audit_ksp_tags.py`, `check_ksp_tags.py`).

`run_ksp_detail.sh` currently skips while `scraper/ksp_schedule.json` exists,
even on a manual service start. `KSP_DETAIL_FORCE` does not remove that guard
or bypass a block. Do not remove recovery config or markers to activate it.

## Evidence and remaining gaps

On Nov 13 the owner received item JSON on the Nano. CPU uin 280943's model
row was `i5-14600K`, not a maker code; Kingston uin 193193 carried
`KF556C40BBK2-32`. Those two samples justified guarded adoption, not assuming
every model row is a part number. The product page itself supplied no usable
structured product data in that observation. Full captures, feasibility and
tag-coverage results remain in the original plan archive.

Still requires separate decisions: warranty/importer presentation, category
port-tag mappings and any schema expansion. Coverage changes require a
same-input measurement, not guessed values or lower floors. A sanctioned KSP
affiliate/product feed remains an alternative; no feed has been established
here. Current access is unresolved, so historical HTTP200 is not permission
to fetch now.

## Offline verification

```bash
python scripts/check_ksp_detail.py
python scripts/check_ksp_tags.py
python scripts/check_detail_pending.py
python scripts/check_scrape_outcomes.py
```

For identity changes, inspect `scripts/check_identity_merge.py` and
`report_identity_delta.py` against an isolated normalize. Preserve product-id
aliases and price history. Apply the [root scraping rules](../README.md#scraping-rules),
owner-only attribution and narrow publication paths for any later authorized
release; this document grants no probe, crawl, timer or push approval.
