"""
Eilat prices: the VAT-free price a vendor charges at its Eilat stores.

Scraped, never calculated: some vendors have no Eilat store, some items are
sold only in Eilat (TMS) and some only outside it, and the discount is not a
flat 1/1.18 (Ivory: no exemption on monitors over 25").

Prefer an Eilat price observed alongside the regular listing; KSP's current
price response contains both. A separate spider is needed only where the
regular source lacks that price or a separate view discovers Eilat-only items.
Legacy snapshots remain supported: data/raw/<night>/<vendor>_eilat.jsonl, with
`channel: "eilat"` on every row and the Eilat price in `price_ils`:

  tms_eilat    TMS category pages in the site's Eilat mode (`?eilat=1`); stock
               from the Claris widget's Eilat branch. Lists Eilat-only items.
  ivory_eilat  Ivory category pages, whose tiles print the Eilat price next to
               the regular one. Only items with an Eilat price get a row.
               Retired 2026-11-25 after the pages returned 13x403 and never
               produced a snapshot; parser and spider stay for a future
               permitted source.
  ksp_eilat    KSP's live-price call (/m_action/api/bms/<uins>) for the uins of
               tonight's KSP snapshot. Only items sold in Eilat get a row.

Eilat rows never enter matching as ordinary listings: they are joined onto the
regular listing with the same listing key (`attach`), and become an offer of
their own only when the vendor sells the item in Eilat alone (`eilat_only`,
no regular price). A row with no regular twin is only trusted that far when
both of the vendor's snapshots are fresh and the Eilat crawl looks complete.
Price history reads the regular files only (build_price_history), so an
Eilat price never draws a line or a price-drop badge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

EILAT_CHANNEL = "eilat"


@dataclass(frozen=True)
class EilatSource:
    vendor: str          # canonical vendor id ("tms", "ivory", "ksp")
    main_spider: str     # regular snapshot file stem
    spider: str          # Eilat snapshot file stem
    min_rows: int        # run_spider warning floor (~75% of a normal night)
    # A row with no regular twin is an Eilat-only item. Only TMS's Eilat
    # crawl covers the same category pages as its regular one; Ivory's
    # catalog pages list more than its PC-builder API, so a missing twin
    # there says nothing.
    discovers_eilat_only: bool


SOURCES: dict[str, EilatSource] = {
    s.vendor: s
    for s in (
        EilatSource("tms", "tms", "tms_eilat", 1400, True),
        EilatSource("ivory", "ivory", "ivory_eilat", 350, False),
        EilatSource("ksp", "ksp", "ksp_eilat", 600, False),
    )
}

# An Eilat crawl matching fewer of the vendor's regular listings than this is
# treated as partial: its prices are still used, but its absences are not read
# as "not sold in Eilat" and it creates no Eilat-only items.
MIN_COVERAGE = 0.5

# The Eilat price is the regular price without VAT (1/1.18 = 0.847), or the
# same price where no exemption applies. Outside this band the row is a
# misread (a tile's other price, a stray digit) and is dropped.
MIN_RATIO = 0.75
MAX_RATIO = 1.0

# Vendor freshness states shipped to the site (meta.json `eilat_vendors`).
FRESH, STALE, PARTIAL, MISSING = "fresh", "stale", "partial", "missing"
# Channels retired after an observed block or a missing source. The dated reason
# is shipped for transparency but no longer raises a daily warning; legacy
# prices stay eligible for stale-forwarding, and the spider/parser stay for a
# future permitted path. This is not a "no Eilat store" claim.
DROPPED = {
    "ivory": "Eilat category pages returned 13x403 on 2026-11-17 and never produced a snapshot; "
             "channel retired 2026-11-25. Regular Ivory prices are unaffected.",
}


def spider_names() -> list[str]:
    return [s.spider for s in SOURCES.values()]


def min_counts() -> dict[str, int]:
    return {s.spider: s.min_rows for s in SOURCES.values()}


def _price(value) -> int | None:
    """A positive whole-shekel price, else None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
        if not math.isfinite(number):
            return None
        price = round(number)
    except (ValueError, OverflowError, TypeError):
        return None
    return price if price > 0 else None


def _stamp(row: dict) -> datetime:
    try:
        at = datetime.fromisoformat(str(row.get("scraped_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def newest_rows(rows: list[dict], key_of) -> dict[str, dict]:
    """One row per listing key: the newest `scraped_at` wins."""
    out: dict[str, dict] = {}
    for row in rows:
        key = key_of(row)
        if key not in out or _stamp(row) >= _stamp(out[key]):
            out[key] = row
    return out


def inline_rows(vendor: str, listings: list[dict]) -> dict[str, dict]:
    """Observed prices at the listing seam, not VAT arithmetic or null guesses.

    The canonical vendor_meta.eilat observation carries price_ils and a
    boolean availability verdict. Read KSP's older positive metadata too;
    its missing/null fields never establish that an item is not sold there.
    Rows retain the listing's crawl stamp so newer separate observations win.
    """
    out = {}
    for listing in listings:
        meta = listing.get("vendor_meta") or {}
        observation = meta.get("eilat")
        available = None
        if isinstance(observation, dict):
            price = _price(observation.get("price_ils"))
            available = observation.get("available")
        elif vendor == "ksp":
            price = _price(meta.get("stream_eilat_price")) or _price(meta.get("eilat_price"))
        else:
            continue
        if available is False:
            # Explicit negative beats an older positive observation; an
            # unknown/malformed field does not erase a valid old price.
            price = None
        elif price is None or not plausible(price, listing.get("price_ils")):
            continue
        out[str(listing["listing_key"])] = {
            **listing, "price_ils": price, "in_stock": listing.get("in_stock"),
            "eilat_available": available, "_eilat_stale": bool(listing.get("stale")),
        }
    return out


def plausible(eilat: int, regular) -> bool:
    regular = _price(regular)
    if regular is None:
        return True
    return MIN_RATIO * regular <= eilat <= MAX_RATIO * regular


@dataclass
class Attached:
    state: str
    matched: int = 0
    implausible: int = 0
    eilat_only: list[dict] = field(default_factory=list)


def attach(vendor: str, listings: list[dict], eilat_rows: dict[str, dict], *,
           eilat_stale: bool, main_stale: bool, seen_day: str | None,
           snapshot_day: str | None) -> Attached:
    """Join one vendor's Eilat rows onto its enriched regular listings.

    `listings` are the vendor's regular listings (mutated in place: each twin
    gets `eilat_price_ils`, `eilat_in_stock`, `eilat_stale`); `eilat_rows`
    maps listing key -> raw Eilat row. Returns the vendor's freshness state
    and the raw rows that should become Eilat-only listings.
    """
    source = SOURCES[vendor]
    by_key = {str(e.get("listing_key")): e for e in listings}
    out = Attached(state=STALE if eilat_stale else FRESH)
    observed_absences = 0
    orphans: list[dict] = []
    for key, row in eilat_rows.items():
        listing = by_key.get(key)
        if row.get("eilat_available") is False:
            if listing is not None:
                for name in ("eilat_price_ils", "eilat_in_stock", "eilat_stale"):
                    listing.pop(name, None)
                observed_absences += 1
            continue
        price = _price(row.get("price_ils"))
        if price is None:
            continue
        if listing is None:
            orphans.append(row)
            continue
        if not plausible(price, listing.get("price_ils")):
            out.implausible += 1
            continue
        stock = row.get("in_stock")
        listing["eilat_price_ils"] = price
        # Ivory and KSP publish no Eilat stock: their Eilat stores sell from
        # the same network stock, so the regular flag stands in.
        listing["eilat_in_stock"] = stock if isinstance(stock, bool) else listing.get("in_stock")
        listing["eilat_stale"] = row.get("_eilat_stale", eilat_stale)
        out.matched += 1

    if listings and out.matched + observed_absences < MIN_COVERAGE * len(listings):
        out.state = PARTIAL
    if source.discovers_eilat_only and out.state == FRESH and not main_stale:
        for row in orphans:
            only = dict(row)
            only.pop("channel", None)
            only["eilat_price_ils"] = _price(row.get("price_ils"))
            stock = row.get("in_stock")
            only["eilat_in_stock"] = stock if isinstance(stock, bool) else None
            only["eilat_stale"] = False
            only["eilat_only"] = True
            # No regular price: the offer never sets a regular minimum,
            # sort or total, and draws no history line.
            only["price_ils"] = None
            only["in_stock"] = False
            for field in ("price_promo_ils", "price_was_ils", "promo_kind", "promo_text_raw"):
                only.pop(field, None)
            only["last_seen"] = snapshot_day
            only["seen_day"] = seen_day or snapshot_day
            only["stale"] = False
            out.eilat_only.append(only)
    return out


# Vendors with no Eilat store (checked 2026-11-16: neither site nor branch
# list names one). Their offers are "no Eilat store", never "not sold there".
NO_EILAT_STORE = ("1pc", "yahav")


def site_meta(states: dict[str, dict]) -> dict:
    """meta.json `eilat`: per-vendor Eilat data state for the site."""
    vendors = {vendor: {"state": s.get("state", MISSING), "last_seen": s.get("last_seen")}
               for vendor, s in sorted(states.items())}
    for vendor, reason in DROPPED.items():
        vendors.setdefault(vendor, {"state": MISSING, "last_seen": None})["dropped"] = reason
    for vendor in NO_EILAT_STORE:
        vendors[vendor] = {"state": "no_store", "last_seen": None}
    return {"vendors": vendors}
