"""Operations reporting: what was scraped, when, and what changed.

`python -m scraper.ops.report` reads data/raw/ (every crawl in the window) and
writes data/ops/: status.json (crawls per vendor), changes.json (new / gone /
returned / price events) and ledger.json (per-listing state carried between
runs). The admin page (/admin/) and the Worker's alert cron read the first two.
"""
