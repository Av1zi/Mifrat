"""
xref/runner.py - catalog products -> retailer search -> product page -> data/xref/<site>/<brand>.json.

Only products below the per-product coverage target are asked about (the
scoreboard's residual), at most one search plus two product pages each. A page
joins only on the MPN / EAN it prints itself.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..mfr.client import Blocked, PoliteClient
from ..mfr.common import base_mpn, norm_mpn, norm_upc
from ..specs import schema

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT / "data" / "catalog.json"
OUT_ROOT = ROOT / "data" / "xref"
SITES = ("overclockers", "ldlc")


def _below_target(product: dict) -> bool:
    sys.path.insert(0, str(ROOT / "scripts"))
    from fill_report import PRODUCT_TARGET, product_score  # noqa: E402

    return product_score(product)["pct"] < PRODUCT_TARGET


def _codes(product: dict) -> tuple[list[str], set[str]]:
    codes: list[str] = []
    keys: set[str] = set()
    for value in (product.get("specs") or {}).get("part_numbers") or []:
        text = str(value or "").strip()
        for key in (norm_mpn(text), base_mpn(text), norm_upc(text)):
            if key:
                keys.add(key)
        if len(norm_mpn(text)) >= 5 and re.search(r"\d", text) and re.search(r"[A-Za-z]", text):
            if norm_mpn(text) not in {norm_mpn(c) for c in codes}:
                codes.append(text)
    return codes[:2], keys


def run(site: str, *, limit: int | None = None, dry_run: bool = False,
        offline: bool = False, verbose: bool = True) -> dict:
    module = importlib.import_module(f"scraper.xref.{site}")
    client = PoliteClient(f"xref-{site}", module.BASE_URL, offline=offline,
                          identify=getattr(module, "IDENTIFY", False))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    summary = {"products": 0, "searches": 0, "pages": 0, "matched": 0, "blocked": False}
    entries: dict[str, dict[str, dict]] = {}
    for product in catalog["products"]:
        category = product.get("category")
        if category not in module.CATEGORIES or not _below_target(product):
            continue
        brand = str((product.get("specs") or {}).get("manufacturer") or product.get("brand") or "")
        codes, ours = _codes(product)
        if not brand or not codes:
            continue
        summary["products"] += 1
        if dry_run:
            continue
        if limit is not None and summary["searches"] >= limit:
            break
        try:
            for code in codes:
                summary["searches"] += 1
                page = client.get(module.search_url(code))
                if not page:
                    continue
                hit = None
                for url in module.tile_urls(page):
                    summary["pages"] += 1
                    body = client.get(url)
                    parsed = module.parse_page(body or "")
                    if module.page_keys(parsed) & ours:
                        hit = (url, parsed)
                        break
                if hit is None:
                    continue
                url, parsed = hit
                specs = module.specs_for(category, parsed["rows"])
                if specs:
                    slug = re.sub(r"[^a-z0-9]+", "", brand.lower()) or "unknown"
                    entries.setdefault(slug, {})[url] = {
                        "url": url,
                        "fetched": datetime.now(timezone.utc).date().isoformat(),
                        "category": category, "brand": brand, "title": parsed.get("title"),
                        "keys": sorted(module.page_keys(parsed) | {norm_mpn(code)}),
                        "names": [], "specs": specs,
                    }
                    summary["matched"] += 1
                break
        except Blocked as error:
            print(f"[xref:{site}] STOP: {error}")
            summary["blocked"] = True
            break
    summary["requests"] = client.requests
    if not dry_run:
        _write(site, entries, merge=limit is not None)
    if verbose:
        print(f"[xref:{site}] " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return summary


def _write(site: str, entries: dict[str, dict[str, dict]], *, merge: bool) -> None:
    out_dir = OUT_ROOT / site
    out_dir.mkdir(parents=True, exist_ok=True)
    for slug, rows in sorted(entries.items()):
        path = out_dir / f"{slug}.json"
        existing: dict = {}
        if merge and path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                if old.get("schema_version") == schema.SCHEMA_VERSION:
                    existing = old.get("entries") or {}
            except ValueError:
                existing = {}
        payload = {"brand": next(iter(rows.values()))["brand"],
                   "schema_version": schema.SCHEMA_VERSION, "source": f"xref:{site}",
                   "generated": datetime.now(timezone.utc).date().isoformat(),
                   "entries": dict(sorted({**existing, **rows}.items()))}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
