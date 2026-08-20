# data/raw/

One folder per UTC date, one JSONL file per vendor spider, written by
`scraper/run_spider.py` (§5 of pc-parts-il-plan.md):

```
data/raw/2026-08-21/onepc.jsonl
data/raw/2026-08-21/plonter.jsonl
data/raw/2026-08-21/tms.jsonl
```

- `onepc.jsonl` and `plonter.jsonl` are written by the `scrape-cloud`
  GitHub Actions workflow (~03:30 UTC).
- `tms.jsonl` is written by the Jetson Nano (`nano/`) (~06:00 UTC + jitter).
- `scraper/normalize_and_match.py` reads the latest available file per
  vendor (falling back to the most recent prior day if today's is missing
  — the stale-forward rule) and builds `data/catalog.json`.

This file itself (and this directory) exists so the layout is visible in
the repo before the first real scrape has run.
