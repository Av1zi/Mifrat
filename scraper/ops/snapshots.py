"""Read data/raw/ as a list of crawls.

A raw file is one vendor-day, but not always one crawl: the pre-fix Nano
`run_tms.sh` appended a second night's crawl to an existing file
(2026-11-09 and 2026-11-11 each hold two TMS crawls ~23h apart), and the file
day can differ from the crawl's UTC day (a local-time date). So a file is
split into crawls wherever `scraped_at` jumps by more than
`matching._SAME_CRAWL_HOURS` (6h), and every crawl carries its own start/end.

Rows are keyed with `matching.listing_key` after the same text cleaning
normalize applies (`text_hygiene.clean_text`: a U+200E in a SKU would be a
second key), so a key here is the catalog's listing key. Only the fields the
report reads are cleaned (cleaning whole rows, vendor_meta included, was 70%
of the run time). A key seen twice in one crawl keeps its newest row.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scraper.matching import _SAME_CRAWL_HOURS, listing_key, normalize_price
from scraper.ops.registry import NIGHT_END_UTC_HOUR, NIGHT_START_UTC_HOUR, VENDORS
from scraper.text_hygiene import clean_text

# The fields listing_key / the report read. `url` is a link field, which
# clean_tree leaves alone too.
_CLEANED_FIELDS = ("vendor_id", "vendor_sku", "title_raw", "category_guess")

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Row:
    title: str
    url: str
    price: int | None
    in_stock: bool | None
    category_guess: str
    sku: str


@dataclass
class Crawl:
    vendor: str
    file_day: str
    start: datetime
    end: datetime
    rows: int                       # raw lines, repeats included
    items: dict[str, Row] = field(default_factory=dict)
    crawls_in_file: int = 1

    @property
    def keys(self) -> int:
        return len(self.items)

    @property
    def misfiled(self) -> bool:
        """The file is named for another day than the crawl started (UTC)."""
        return self.start.strftime("%Y-%m-%d") != self.file_day

    @property
    def outside_window(self) -> bool:
        """Started outside the 21:00-04:00 UTC night window."""
        h = self.start.hour
        return not (h >= NIGHT_START_UTC_HOUR or h < NIGHT_END_UTC_HOUR)


def _stamp(value) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _row(raw: dict) -> Row:
    stock = raw.get("in_stock")
    return Row(
        title=str(raw.get("title_raw") or ""),
        url=str(raw.get("url") or ""),
        price=normalize_price(raw.get("price_ils")),
        in_stock=stock if isinstance(stock, bool) else None,
        category_guess=str(raw.get("category_guess") or ""),
        sku=str(raw.get("vendor_sku") or ""),
    )


def split_crawls(vendor: str, file_day: str, rows: list[dict]) -> list[Crawl]:
    """One vendor-day file's rows -> its crawls, oldest first."""
    vendor_id = "1pc" if vendor == "onepc" else vendor
    fallback = datetime.fromisoformat(file_day).replace(tzinfo=timezone.utc)
    stamped = []
    for raw in rows:
        raw.setdefault("vendor_id", vendor_id)
        at = _stamp(raw.get("scraped_at"))
        stamped.append((fallback if at is _EPOCH else at, raw))
    stamped.sort(key=lambda pair: pair[0])

    gap = timedelta(hours=_SAME_CRAWL_HOURS)
    crawls: list[Crawl] = []
    for at, raw in stamped:
        if not crawls or at - crawls[-1].end > gap:
            crawls.append(Crawl(vendor, file_day, at, at, 0))
        crawl = crawls[-1]
        crawl.end = at
        crawl.rows += 1
        # Sorted by time, so a later row of the same key replaces the earlier.
        crawl.items[listing_key(raw)] = _row(raw)
    for crawl in crawls:
        crawl.crawls_in_file = len(crawls)
    return crawls


def read_rows(path: Path) -> list[dict]:
    """A raw JSONL file's rows, report fields cleaned like normalize does.

    Lines that are not one JSON object are skipped (normalize's
    concatenated-object recovery matters for a hand-pasted file, not for the
    crawl counts this report shows).
    """
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            for name in _CLEANED_FIELDS:
                value = raw.get(name)
                if isinstance(value, str):
                    raw[name] = clean_text(value)
            rows.append(raw)
    return rows


def load_crawls(raw_dir: Path, today: datetime, days: int) -> dict[str, list[Crawl]]:
    """Every crawl of every registry vendor in the last `days` day folders.

    Returns vendor -> crawls sorted by start. A file outside the registry is
    ignored (the registry is the list of vendors that exist).
    """
    oldest = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    out: dict[str, list[Crawl]] = {v: [] for v in VENDORS}
    if not raw_dir.is_dir():
        return out
    for day_dir in sorted(raw_dir.iterdir()):
        if not day_dir.is_dir() or not DAY_RE.match(day_dir.name) or day_dir.name < oldest:
            continue
        for vendor in VENDORS:
            path = day_dir / f"{vendor}.jsonl"
            if not path.is_file():
                continue
            out[vendor].extend(split_crawls(vendor, day_dir.name, read_rows(path)))
    for crawls in out.values():
        crawls.sort(key=lambda c: c.start)
    return out
