# data/raw/

One folder per scrape night (UTC start + 3h), one atomic JSONL file per vendor
spider, written by
`scraper/run_spider.py`:

```text
data/raw/2026-10-17/ivory.jsonl
data/raw/2026-10-17/onepc.jsonl
data/raw/2026-10-17/tms.jsonl
data/raw/2026-10-17/yahav.jsonl
data/raw/2026-10-29/ksp.jsonl      # first KSP snapshot (vendor added 2026-10-30 UTC)
```

Examples before Nov 15 use the historical UTC start-date convention. New
folders use the night-ending date; `MIFRAT_NIGHT` pins it in wrappers. A
second run can replace a snapshot only if it is at least as complete; never
append nightly listings. None of this authorizes a second crawl after a block.

- `ivory` and `yahav` are written by `scrape-cloud`. The schedule targets
  Israel night hours, with a hard scheduled-start cutoff at 09:00 Israel;
  workflows and `scripts/scrape_window.py` own exact timing.
- `tms`, `onepc` and `ksp` are written by the Jetson Nano (`nano/`), once a
  night. KSP was added 2026-10-30; its raw rows carry the Hebrew `tags` table in
  `vendor_meta`.
- `plonter` was dropped on 2026-09-29 (datacenter-IP block). Its last
  snapshot is 2026-09-27; the spider and its older snapshots stay in the
  repo in case it is re-enabled.
- `detail/` holds the per-vendor detail-page enrichment
  (`scrapy crawl <vendor>_detail`), merged by `normalize_and_match.py`.
  KSP detail was implemented Nov 13 but is currently disabled during listing
  recovery. KSP is paused after Nov 22 rejection; historical success is not
  permission to rerun. [Current status](../../docs/ksp-stream-transport.md).
  Already fetched detail rows survive a block; later KSP requests stop.
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
- KSP covers are 300×300 listing JPEGs (its larger detail gallery is
  WAF-blocked), rank last in `data/matching/image_vendor_priority.json`, and
  are deliberately skipped by the cloud `--from-catalog` run (its image host
  blocks datacenter IPs). The home-side
  `python -m scraper.download_images --from-catalog --vendor ksp` backfill
  ran on 2026-10-31 (946/946 covers, 0 failures). New products need a home-side
  backfill when permitted, not while KSP is paused; otherwise they show a placeholder.
- `python scripts/check_image_files.py` is the gate (WebP only, size budget,
  black-border detector; genuine dark-backdrop shots are listed in
  `data/matching/image_dark_ok.json`).
