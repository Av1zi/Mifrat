"""Listing lifecycle across crawls: new, missing, gone, returned, price moves.

`replay(crawls, catalog, memory, onboarding)` walks every crawl in the window,
oldest first, and returns the events they produced, one summary per crawl
and each listing's final state. It is recomputed from data/raw/ on every run,
so there is no ledger to drift or merge; the only carried state is `memory`
(listing key -> the product it last belonged to), so a listing that has left
the catalog can still name the product it was.

States of one listing key (owner, 2026-11-12):

  active    seen in the vendor's latest valid crawl
  missing   absent from the latest valid crawl only ("may be delisted": 1PC
            drops and re-adds ~50 rows a day, so one absence is noise)
  gone      absent from >= 2 consecutive valid crawls spanning >= 36h
            -> one `gone` event; seen again later -> one `returned` event

A crawl is *suspect* (partial) when it holds fewer keys than the vendor's
registry floor or than 85% of the median of its last 7 valid crawls. A
suspect crawl updates what it saw but never counts an absence, so a
half-blocked night cannot mass-delist a vendor. A vendor's first crawl in
the window is its baseline and produces no `new` events.

Product events, derived from the listing events and today's catalog:
  new_product   a product all of whose listings are new (first seen after
                their vendor's baseline); a renamed or split product keeps
                old listings, so it is never "new"
  vendor_added  a new listing joined a product that already had listings
  vendor_lost   a listing is gone and its product is still in the catalog
  product_gone  a listing is gone and its product is no longer in the
                catalog (and is no pid alias of a live one)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from scraper.ops.registry import VENDORS
from scraper.ops.snapshots import Crawl

DELIST_MIN_ABSENCES = 2
DELIST_MIN_HOURS = 36
SUSPECT_SHARE = 0.85
BASELINE_CRAWLS = 7
# Price events kept: moves of at least this share. Every move is still
# counted per crawl (1PC reprices ~150 rows on a normal day; 2026-11-03 TMS
# repriced 434 rows, half under 5%).
PRICE_EVENT_SHARE = 0.05


def iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


@dataclass
class ListingState:
    vendor: str
    first: datetime
    last: datetime
    title: str = ""
    url: str = ""
    price: int | None = None
    state: str = "active"          # active | missing | gone
    misses: int = 0
    missing_since: datetime | None = None
    gone_at: datetime | None = None
    is_new: bool = False           # first seen after the vendor's baseline


class CatalogView:
    """The parts of data/catalog.json the replay reads, plus `memory`.

    memory = {"pids": {listing key: pid}, "products": {pid: [name, category]}}
    from the previous run, for listings today's catalog no longer holds.
    """

    def __init__(self, catalog: dict, memory: dict | None = None):
        memory = memory or {}
        self.products = {str(p.get("product_id")): p for p in catalog.get("products") or []}
        self.pid_of: dict[str, str] = {}
        self.members: dict[str, list[str]] = {}
        for row in catalog.get("listings") or []:
            key, pid = row.get("listing_key"), row.get("product_id")
            if key and pid:
                self.pid_of[str(key)] = str(pid)
                self.members.setdefault(str(pid), []).append(str(key))
        self.aliases = {str(k): str(v) for k, v in (catalog.get("pid_aliases") or {}).items()}
        self.old_pid_of: dict[str, str] = dict(memory.get("pids") or {})
        self.old_products: dict[str, list[str]] = dict(memory.get("products") or {})

    def product_of(self, key: str) -> dict:
        """The listing's product now, else the one it last belonged to."""
        pid = self.pid_of.get(key) or self.old_pid_of.get(key)
        if not pid:
            return {}
        pid = self.aliases.get(pid, pid)
        live = self.products.get(pid)
        if live is not None:
            return {"pid": pid, "product": str(live.get("canonical_name") or ""),
                    "category": str(live.get("category") or ""), "live": True}
        name, category = (self.old_products.get(pid) or ["", ""])[:2]
        return {"pid": pid, "product": name, "category": category, "live": False}


@dataclass
class Replay:
    view: CatalogView
    events: list[dict] = field(default_factory=list)
    crawls: list[dict] = field(default_factory=list)
    listings: dict[str, ListingState] = field(default_factory=dict)


def suspect_reason(crawl: Crawl, recent_keys: list[int]) -> str | None:
    """Why this crawl is too small to trust for absences, or None."""
    floor = VENDORS[crawl.vendor].min_rows
    if crawl.keys < floor:
        return f"{crawl.keys} items, floor {floor}"
    if recent_keys:
        typical = median(recent_keys[-BASELINE_CRAWLS:])
        if crawl.keys < SUSPECT_SHARE * typical:
            return f"{crawl.keys} items vs typical {int(typical)}"
    return None


def replay(crawls: dict[str, list[Crawl]], catalog: dict, memory: dict | None,
           onboarding: set[str]) -> Replay:
    """Walk every vendor's crawls. `onboarding`: vendors whose first-ever
    snapshot is inside the window (their baseline crawl says so)."""
    out = Replay(CatalogView(catalog, memory))
    for vendor in sorted(crawls):
        _replay_vendor(vendor, crawls[vendor], out, vendor in onboarding)
    out.events.extend(_product_events(out))
    out.events.sort(key=lambda e: (e["at"], e["type"], e.get("vendor", ""), e.get("key", "")))
    return out


def _event(kind: str, at: datetime, key: str, state: ListingState,
           view: CatalogView, **extra) -> dict:
    info = view.product_of(key)
    info.pop("live", None)
    return {"at": iso(at), "type": kind, "vendor": state.vendor, "key": key,
            "title": state.title, "url": state.url, "price": state.price,
            **info, **extra}


def _replay_vendor(vendor: str, crawls: list[Crawl], out: Replay, onboarding: bool) -> None:
    recent: list[int] = []
    listings, view = out.listings, out.view
    for index, crawl in enumerate(crawls):
        baseline = index == 0
        reason = None if baseline else suspect_reason(crawl, recent)
        summary = {
            "vendor": vendor, "file_day": crawl.file_day, "start": iso(crawl.start),
            "end": iso(crawl.end), "rows": crawl.rows, "keys": crawl.keys,
            "crawls_in_file": crawl.crawls_in_file, "misfiled": crawl.misfiled,
            "outside_window": crawl.outside_window, "suspect": reason,
            "baseline": baseline, "onboarding": baseline and onboarding,
            "new": 0, "missing": 0, "gone": 0, "returned": 0, "price_changes": 0,
        }
        at = crawl.start
        for key, row in crawl.items.items():
            state = listings.get(key)
            if state is None:
                state = ListingState(vendor, at, at, row.title, row.url, row.price,
                                     is_new=not baseline)
                listings[key] = state
                if not baseline:
                    summary["new"] += 1
                    out.events.append(_event("new", at, key, state, view))
            elif state.state == "gone":
                summary["returned"] += 1
                gone_days = (at - state.last).days
                state.title, state.url, state.price = row.title, row.url, row.price
                out.events.append(_event("returned", at, key, state, view, gone_days=gone_days))
            elif state.price and row.price and state.price != row.price:
                summary["price_changes"] += 1
                if abs(row.price - state.price) / state.price >= PRICE_EVENT_SHARE:
                    old = state.price
                    state.title, state.url, state.price = row.title, row.url, row.price
                    out.events.append(_event("price", at, key, state, view, old=old))
            state.title, state.url, state.price = row.title, row.url, row.price
            state.last, state.state, state.misses = at, "active", 0
            state.missing_since = state.gone_at = None

        if reason is None:
            recent.append(crawl.keys)
            for key, state in listings.items():
                if state.vendor != vendor or key in crawl.items or state.state == "gone":
                    continue
                state.misses += 1
                if state.state == "active":
                    state.state = "missing"
                    state.missing_since = at
                    summary["missing"] += 1
                hours = (at - state.last).total_seconds() / 3600
                if state.misses >= DELIST_MIN_ABSENCES and hours >= DELIST_MIN_HOURS:
                    state.state = "gone"
                    state.gone_at = at
                    summary["gone"] += 1
                    out.events.append(_event("gone", at, key, state, view,
                                             last_seen=iso(state.last)))
        out.crawls.append(summary)


def _product_events(out: Replay) -> list[dict]:
    events: list[dict] = []
    view, listings = out.view, out.listings
    for pid, keys in view.members.items():
        states = [(k, listings[k]) for k in keys if k in listings]
        if not states:
            continue
        product = view.products.get(pid) or {}
        base = {"pid": pid, "product": str(product.get("canonical_name") or ""),
                "category": str(product.get("category") or "")}
        if all(s.is_new for _, s in states):
            key, first = min(states, key=lambda ks: ks[1].first)
            best = product.get("best_offer") or {}
            events.append({**base, "at": iso(first.first), "type": "new_product", "key": key,
                           "price": best.get("price_ils"),
                           "vendors": sorted({s.vendor for _, s in states})})
            continue
        for key, state in states:
            if state.is_new:
                events.append({**base, "at": iso(state.first), "type": "vendor_added",
                               "vendor": state.vendor, "key": key, "title": state.title,
                               "url": state.url, "price": state.price})

    gone_by_pid: dict[str, list[tuple[str, ListingState]]] = {}
    for key, state in listings.items():
        if state.state == "gone":
            info = view.product_of(key)
            if info.get("pid"):
                gone_by_pid.setdefault(info["pid"], []).append((key, state))
    old_members: dict[str, list[str]] = {}
    for key, pid in view.old_pid_of.items():
        old_members.setdefault(view.aliases.get(pid, pid), []).append(key)
    for pid, gone in gone_by_pid.items():
        info = view.product_of(gone[0][0])
        if not info.get("live"):
            siblings = [listings[k] for k in old_members.get(pid, []) if k in listings]
            # Not every listing it had is gone yet (one is only missing, so
            # may still come back): decide once it is.
            if any(s.state == "missing" for s in siblings):
                continue
            # The pid left the catalog without an alias, but a listing it held
            # may still be on sale under a new pid (a split): then the part is
            # still sold, and this is one vendor leaving it.
            for sibling in old_members.get(pid, []):
                state = listings.get(sibling)
                live = view.product_of(sibling)
                if state is not None and state.state == "active" and live.get("live"):
                    info = {**live}
                    break
        if info.get("live"):
            pid = info["pid"]
            for key, state in gone:
                events.append({"at": iso(state.gone_at), "type": "vendor_lost",
                               "vendor": state.vendor, "key": key, "pid": pid,
                               "product": info["product"], "category": info["category"],
                               "title": state.title, "url": state.url, "price": state.price})
        else:
            events.append({"at": iso(max(s.gone_at for _, s in gone)), "type": "product_gone",
                           "pid": pid, "product": info["product"], "category": info["category"],
                           "vendors": sorted({s.vendor for _, s in gone}),
                           "price": min((s.price for _, s in gone if s.price), default=None),
                           "last_seen": iso(max(s.last for _, s in gone))})
    return events


def next_memory(out: Replay) -> dict:
    """Key -> product for every key the window knows, for the next run.

    All keys, not only absent ones: a listing that vanishes from tomorrow's
    crawl is also gone from tomorrow's catalog (normalize builds from the
    vendor's newest snapshot), so today is the last time its product is
    known. Sorted, so the committed file changes by small deltas.
    """
    pids: dict[str, str] = {}
    products: dict[str, list[str]] = {}
    for key in out.listings:
        info = out.view.product_of(key)
        if info.get("pid"):
            pids[key] = info["pid"]
            products[info["pid"]] = [info["product"], info["category"]]
    return {"pids": dict(sorted(pids.items())), "products": dict(sorted(products.items()))}


def absent_listings(out: Replay, now: datetime, days: int) -> list[dict]:
    """Listings missing from the latest crawl, or gone within `days`."""
    cutoff = now - timedelta(days=days)
    rows = []
    for key, s in out.listings.items():
        if s.state == "active" or (s.state == "gone" and s.gone_at and s.gone_at < cutoff):
            continue
        info = out.view.product_of(key)
        rows.append({"key": key, "vendor": s.vendor, "state": s.state, "title": s.title,
                     "url": s.url, "price": s.price, "last_seen": iso(s.last),
                     "since": iso(s.gone_at or s.missing_since or s.last),
                     "pid": info.get("pid"), "product": info.get("product", ""),
                     "category": info.get("category", ""),
                     "product_live": bool(info.get("live"))})
    rows.sort(key=lambda r: r["since"], reverse=True)
    return rows
