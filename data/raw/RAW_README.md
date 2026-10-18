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

## data/images/ (cover photos)

Covers downloaded from the vendors' detail pages live next to the raw
snapshots' data, one folder per vendor: `data/images/<vendor>/<sku>.webp`.

- Format: WebP quality 76, long edge at most 640px, transparency
  composited onto white. Thumbnails are derived at site build time
  (`site/scripts/copy-data.mjs`) and are not committed.
- Only covers the site can show are kept (selected cover + one runner-up per
  product). `python -m scraper.download_images --prune` lists what it would
  delete; `--prune --apply` deletes it. The detail job skips SKUs the
  catalog does not want, so pruned files are not fetched again.
- `--from-catalog` fetches covers for products that have none;
  `--refetch-alpha` re-fetches kept covers whose source format can carry
  transparency (tms excluded unless `--vendor tms`, home-IP rules);
  `--upgrade` refetches low-resolution covers once (ledger:
  `data/images/upgrade_ledger.json`).
- `python scripts/check_image_files.py` is the gate (WebP only, size budget,
  black-border detector; genuine dark-backdrop shots are listed in
  `data/matching/image_dark_ok.json`).
