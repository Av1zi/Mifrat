"""
mfr/runner.py - the brand-independent fetch loop.

    catalog products of the brand  ->  brand.match() to a manufacturer page
    ->  PoliteClient.get() (robots, 1 req/s, cache)  ->  brand.parse()
    ->  data/mfr/<brand>.json

The loop never fetches a page no catalog product matched, never retries, and
stops the whole brand on the first 403/429 (`Blocked`). The JSON it writes is
the only artifact that is committed; raw pages stay in the gitignored cache.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..specs import schema
from .client import Blocked, PoliteClient
from .common import base_mpn, norm_mpn, norm_upc, strict_name

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT / "data" / "catalog.json"
OUT_DIR = ROOT / "data" / "mfr"


def _identity_keys(product: dict, brand: str) -> tuple[list[str], str]:
    keys: list[str] = []
    for value in (product.get("specs") or {}).get("part_numbers") or []:
        for key in (norm_mpn(value), base_mpn(value), norm_upc(value)):
            if key and key not in keys:
                keys.append(key)
    return keys, strict_name(product.get("canonical_name"), brand)


def run(brand: str, *, limit: int | None = None, dry_run: bool = False,
        verbose: bool = True) -> dict:
    module = importlib.import_module(f"scraper.mfr.{brand}")
    client = PoliteClient(brand, module.BASE_URL)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    products = [p for p in catalog["products"]
                if str((p.get("specs") or {}).get("manufacturer") or "").lower()
                == module.BRAND.lower() and p.get("category") in module.CATEGORIES]

    entries = module.index(client)
    by_key = {entry["key"]: entry for entry in entries}
    if verbose:
        print(f"[mfr:{brand}] {len(entries)} manufacturer pages indexed, "
              f"{len(products)} catalog products in scope")

    # product -> page; one page may serve several products (colour variants).
    wanted: dict[str, dict] = {}
    unmatched = 0
    for product in products:
        entry = module.match(by_key, product)
        if entry is None:
            unmatched += 1
            continue
        slot = wanted.setdefault(entry["url"], {"entry": entry, "products": []})
        slot["products"].append(product)
    if verbose:
        print(f"[mfr:{brand}] {len(wanted)} pages cover "
              f"{sum(len(v['products']) for v in wanted.values())} products "
              f"({unmatched} unmatched)")
    # Brands whose pages carry a product identifier (UPC / MPN) fetch every
    # in-scope page, not only those a catalog product matched by name: the join
    # then happens at merge time on the identifier the page itself states.
    extra = 0
    if hasattr(module, "classify"):
        for entry in entries:
            if entry["url"] not in wanted and module.in_scope(entry):
                wanted[entry["url"]] = {"entry": entry, "products": []}
                extra += 1
        if verbose:
            print(f"[mfr:{brand}] +{extra} identifier-join pages beyond the name matches")
    if dry_run:
        return {"pages": len(wanted), "unmatched": unmatched}

    existing = {}
    out_path = OUT_DIR / f"{brand}.json"
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8")).get("entries", {})
        except ValueError:
            existing = {}

    results: dict[str, dict] = {}
    today = datetime.now(timezone.utc).date().isoformat()
    blocked = None
    for index, (url, slot) in enumerate(sorted(wanted.items())):
        if limit is not None and index >= limit:
            break
        category = slot["products"][0]["category"] if slot["products"] else None
        try:
            page = client.get(url)
        except Blocked as error:
            blocked = str(error)
            break
        if page is None:
            continue
        if hasattr(module, "classify"):
            category = module.classify(slot["entry"], page) or category
        if category is None:
            continue
        parsed = module.parse(page, category)
        # A page that sells several models (Lian Li fan families, case + LCD kit)
        # returns "_blocks": one spec dict per model, each with its own category.
        blocks = parsed.pop("_blocks", None)
        if blocks is None:
            items = [("", category, parsed)]
        else:
            items = [(f"#{n}", block.pop("_category", None), block)
                     for n, block in enumerate(blocks)]
        for suffix, item_category, specs in items:
            if item_category is None:
                continue
            extra_ids = [specs.pop("_upc", None), specs.pop("_mpn", None),
                         *(specs.pop("_ids", None) or [])]
            keys: list[str] = []
            names: list[str] = []
            for product in slot["products"] if not suffix else []:
                product_keys, name = _identity_keys(product, module.BRAND)
                keys += [k for k in product_keys if k not in keys]
                if name and name not in names:
                    names.append(name)
            for raw in extra_ids:
                for key in (norm_upc(raw), norm_mpn(raw), base_mpn(raw)):
                    if key and key not in keys:
                        keys.append(key)
            entry_key = slot["entry"].get("key")
            if entry_key and not suffix:
                # Entry keys are stored in the store's lookup form (upper-case
                # alphanumeric) so a slug that IS a part number joins exactly.
                for key in (entry_key, norm_mpn(entry_key)):
                    if key and key not in keys:
                        keys.append(key)
            results[url + suffix] = {"url": url + suffix, "fetched": today,
                                     "category": item_category, "keys": keys,
                                     "names": names, "specs": specs}
        if verbose and index % 25 == 0:
            print(f"[mfr:{brand}] {index + 1}/{len(wanted)} fetched ({client.requests} requests)")

    # Entries from an earlier run that this run did not reach stay as they were
    # (a --limit run or a block must not erase the committed data).
    merged = {**existing, **results}
    payload = {"brand": module.BRAND, "schema_version": schema.SCHEMA_VERSION,
               "source": "manufacturer", "generated": today,
               "entries": dict(sorted(merged.items()))}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    summary = {"pages": len(results), "requests": client.requests,
               "robots_skipped": client.skipped_robots, "blocked": blocked,
               "unmatched": unmatched}
    if verbose:
        print(f"[mfr:{brand}] wrote {out_path.relative_to(ROOT)}: {summary}")
        if blocked:
            print(f"[mfr:{brand}] STOPPED - {blocked}. Per the scraping rules a block "
                  "is a stop signal: do not retry, drop the brand if it repeats.")
    return summary
