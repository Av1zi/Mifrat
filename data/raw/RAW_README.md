# data/raw/

One folder per UTC date, one JSONL file per vendor spider, written by
`scraper/run_spider.py`:

```
data/raw/2026-10-17/ivory.jsonl
data/raw/2026-10-17/onepc.jsonl
data/raw/2026-10-17/tms.jsonl
data/raw/2026-10-17/yahav.jsonl
```

- `ivory`, `onepc` and `yahav` are written by the `scrape-cloud` GitHub
  Actions workflow (~03:30 UTC).
- `tms` is written by the Jetson Nano (`nano/`), once a day.
- `plonter` was dropped on 2026-09-29 (datacenter-IP block). Its last
  snapshot is 2026-09-27; the spider and its older snapshots stay in the
  repo in case it is re-enabled.
- `detail/` holds the per-vendor detail-page enrichment
  (`scrapy crawl <vendor>_detail`), merged by `normalize_and_match.py`.
- `scraper/normalize_and_match.py` reads the latest file per vendor, falling
  back to the most recent prior day for up to 14 days (the stale-forward
  rule), and builds `data/catalog.json` and `data/site/*.json`.
- `weekly-downsample.yml` collapses day folders older than 90 days.
