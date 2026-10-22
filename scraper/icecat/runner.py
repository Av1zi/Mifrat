"""
icecat/runner.py - catalog products -> Open Icecat sheets -> data/icecat/<brand>.json.

For each product: ask by brand + each real part number (and by barcode when
one is known), accept a sheet only when the sheet's own part number or one of
its barcodes equals ours, map its features to schema fields, and store one
entry per Icecat product, keyed on the identifiers the sheet itself prints.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ..mfr.common import base_mpn, norm_mpn, norm_upc
from ..specs import schema
from .client import NOT_OPEN, Blocked, IcecatClient
from .mapping import features_of, specs_for

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT / "data" / "catalog.json"
OUT_DIR = ROOT / "data" / "icecat"

CATEGORIES = ("cpu", "gpu", "motherboard", "memory", "storage", "psu", "case",
              "case_fan", "cooler_air", "aio", "cooling_other")
# Catalog brand -> Icecat's brand name, where they differ.
BRAND_ALIASES = {
    "kingston": "Kingston Technology",
    "western digital": "Western Digital",
    "team group": "Team Group", "teamgroup": "Team Group",
    "patriot": "Patriot Memory",
    "g.skill": "G.Skill",
    "arctic": "ARCTIC",
    "be quiet!": "be quiet!",
    "minis forum": "MINISFORUM",
}
MAX_CODES = 2            # part numbers asked per product


def _variants(brand: str, code: str) -> list[str]:
    """The codes worth asking for one of our part numbers. Israeli vendors
    drop Gigabyte's 'GV-' prefix from graphics-card order codes
    ('N5060AEROOC8GD' is 'GV-N5060AERO OC-8GD' on the box)."""
    out = [code]
    if brand.lower() == "gigabyte" and re.match(r"^[NR]\d", code, re.I):
        out.append("GV-" + code)
    return out


def _slug(brand: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", brand.lower()) or "unknown"


def _codes(product: dict) -> tuple[list[str], list[str]]:
    """(part numbers worth asking, barcodes) from the product's part_numbers."""
    codes: list[str] = []
    gtins: list[str] = []
    for value in (product.get("specs") or {}).get("part_numbers") or []:
        text = str(value or "").strip()
        if re.fullmatch(r"\d{12,14}", text):
            gtins.append(text)
        elif len(norm_mpn(text)) >= 5 and re.search(r"\d", text) and not text.isdigit():
            if norm_mpn(text) not in {norm_mpn(c) for c in codes}:
                codes.append(text)
    return codes[:MAX_CODES], gtins[:1]


def _sheet_keys(data: dict) -> set[str]:
    info = data.get("GeneralInfo") or {}
    keys = {norm_mpn(info.get("BrandPartCode")), base_mpn(info.get("BrandPartCode"))}
    for code in info.get("BrandPartCode", "").split(","):
        keys.add(norm_mpn(code))
    for gtin in info.get("GTIN") or []:
        keys.add(norm_upc(gtin))
        keys.add(norm_upc(str(gtin).lstrip("0")))
    return {k for k in keys if k}


def run(*, brands: set[str] | None = None, limit: int | None = None,
        dry_run: bool = False, offline: bool = False, verbose: bool = True) -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    client = IcecatClient(offline=offline)
    if verbose and client.username == "openIcecat-live":
        print("[icecat] ICECAT_USERNAME not set: using the public openIcecat-live account")
    summary = {"products": 0, "asked": 0, "ok": 0, "not_open": 0, "not_found": 0,
               "rejected": 0, "matched_products": 0, "blocked": False}
    entries: dict[str, dict[str, dict]] = {}
    for product in catalog["products"]:
        category = product.get("category")
        if category not in CATEGORIES:
            continue
        brand = str((product.get("specs") or {}).get("manufacturer") or product.get("brand") or "")
        if not brand or (brands and brand.lower() not in brands):
            continue
        codes, gtins = _codes(product)
        if not codes and not gtins:
            continue
        summary["products"] += 1
        if dry_run:
            summary["asked"] += len(codes) + len(gtins)
            continue
        if limit is not None and summary["asked"] >= limit:
            break
        icecat_brand = BRAND_ALIASES.get(brand.lower(), brand)
        variants = [v for c in codes for v in _variants(brand, c)]
        ours = {k for c in variants + gtins for k in (norm_mpn(c), base_mpn(c), norm_upc(c)) if k}
        own_keys = {k for c in codes + gtins for k in (norm_mpn(c), norm_upc(c)) if k}
        queries = [{"gtin": g} for g in gtins] + [{"brand": icecat_brand, "code": v}
                                                   for v in variants]
        for query in queries:
            summary["asked"] += 1
            try:
                status, data = client.lookup(**query)
            except Blocked as error:
                print(f"[icecat] STOP: {error}")
                summary["blocked"] = True
                break
            if status != "ok":
                summary[status if status == NOT_OPEN else "not_found"] += 1
                continue
            summary["ok"] += 1
            keys = _sheet_keys(data)
            if not keys & ours:
                summary["rejected"] += 1        # Icecat's lenient lookup, not our part
                continue
            specs = specs_for(category, features_of(data))
            if not specs:
                continue
            info = data.get("GeneralInfo") or {}
            icecat_id = str(info.get("IcecatId") or info.get("ProductId") or sorted(keys)[0])
            entries.setdefault(_slug(brand), {})[icecat_id] = {
                "url": f"https://icecat.biz/p/product/{icecat_id}",
                "fetched": datetime.now(timezone.utc).date().isoformat(),
                "category": category,
                "brand": brand,
                "title": info.get("Title"),
                # The sheet's identifiers plus our spelling of the one that
                # matched (so the merge joins on the code the offers carry).
                "keys": sorted(keys | own_keys),
                "names": [],
                "specs": specs,
            }
            summary["matched_products"] += 1
            break
        if summary["blocked"]:
            break
    summary["requests"] = client.requests
    if not dry_run:
        _write(entries, merge=bool(brands) or limit is not None)
    if verbose:
        print("[icecat] " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return summary


def _write(entries: dict[str, dict[str, dict]], *, merge: bool) -> None:
    """One file per brand. A partial run (--brand / --limit) merges into what
    is on disk; a full run replaces each brand file it produced entries for."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, rows in sorted(entries.items()):
        path = OUT_DIR / f"{slug}.json"
        existing: dict = {}
        if merge and path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                if old.get("schema_version") == schema.SCHEMA_VERSION:
                    existing = old.get("entries") or {}
            except ValueError:
                existing = {}
        brand = next(iter(rows.values()))["brand"]
        payload = {"brand": brand, "schema_version": schema.SCHEMA_VERSION,
                   "source": "icecat",
                   "generated": datetime.now(timezone.utc).date().isoformat(),
                   "entries": dict(sorted({**existing, **rows}.items()))}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
