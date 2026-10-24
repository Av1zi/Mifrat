"""
extract/runner.py - catalog residual -> Claude -> verified facts -> data/extract/products.json.

Two modes:

- fill (default): every product below the per-product target, asked only about
  its applicable fields that are still empty and extractable.
- audit (--audit N): N products asked about fields a SOURCED tier already
  filled (vendor table, maker page, reference, Icecat, override). Verified
  answers are compared with those values (backtest_rules.agrees) and the
  per-field tally is written to data/extract/trust.json. The store uses a field
  only after the audit measured it: MIN_OVERLAP overlaps at no more than
  MAX_DISAGREE disagreement.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..specs import schema
from .client import PROMPT_VERSION, Extractor, NoKey, RateLimited, prompt, provider_models
from .verify import extractable, product_text, text_hash, verified

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT / "data" / "catalog.json"
OUT_DIR = ROOT / "data" / "extract"
PRODUCTS = OUT_DIR / "products.json"
TRUST = OUT_DIR / "trust.json"
MIN_TEXT = 80
MAX_FIELDS = 30
MIN_OVERLAP = 10
MAX_DISAGREE = 0.03
_SOURCED = ("vendor", "manufacturer", "reference", "override", "catalog")
NOT_SCORED = {"other"}
# Claude Haiku 5.5 list prices, USD per million tokens (prompts <= 100K).
_PRICE_IN, _PRICE_OUT = 0.10, 0.50


def _scripts():
    sys.path.insert(0, str(ROOT / "scripts"))
    import backtest_rules  # noqa: E402
    import fill_report  # noqa: E402

    return fill_report, backtest_rules


def _by_product(catalog: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for listing in catalog.get("listings") or []:
        out[str(listing.get("product_id"))].append(listing)
    return out


def trust_models() -> dict[str, dict]:
    """{model: {"category.field": {overlap, agree, examples}}} from trust.json.
    The first file format held one model's fields under "fields"."""
    try:
        data = json.loads(TRUST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("prompt_version") != PROMPT_VERSION:
        return {}
    if "models" in data:
        return {model: (slot.get("fields") or {}) for model, slot in data["models"].items()}
    return {data["model"]: data.get("fields") or {}} if data.get("model") else {}


def _verdicts(good: bool) -> set[tuple[str, str, str]]:
    out = set()
    for model, fields in trust_models().items():
        for key, slot in fields.items():
            overlap, agree = slot.get("overlap", 0), slot.get("agree", 0)
            if overlap < MIN_OVERLAP:
                continue
            if (1 - agree / overlap <= MAX_DISAGREE) == good:
                category, _, field = key.partition(".")
                out.add((model, category, field))
    return out


def trusted_fields() -> set[tuple[str, str, str]]:
    """(model, category, field) the audit measured as safe, per model."""
    return _verdicts(True)


def _distrusted() -> set[tuple[str, str, str]]:
    """(model, category, field) measured over the limit: not worth asking again."""
    return _verdicts(False)


def _requests(catalog: dict, audit: int | None):
    """(product, fields, text) per request, in catalog order."""
    fill_report, _ = _scripts()
    listings = _by_product(catalog)
    bad = _distrusted()
    models = [model or "?" for _, model in provider_models()]
    skip = {(c, f) for (_, c, f) in bad if all((m, c, f) in bad for m in models)}
    products = [p for p in catalog["products"] if p.get("category") not in NOT_SCORED]
    if audit:
        # Spread the sample over the catalog: every k-th product with sourced cells.
        step = max(1, len(products) // max(1, audit))
        products = products[::step]
    for product in products:
        category = product.get("category") or ""
        specs = product.get("specs") or {}
        sources = product.get("spec_sources") or {}
        if audit:
            fields = [name for name in specs
                      if specs.get(name) is not None and extractable(category, name)
                      and str(sources.get(name) or "").split(":", 1)[0] in _SOURCED]
        else:
            if fill_report.product_score(product)["pct"] >= fill_report.PRODUCT_TARGET:
                continue
            fields = [name for name in fill_report.product_score(product)["missing"]
                      if extractable(category, name) and (category, name) not in skip]
        fields = fields[:MAX_FIELDS]
        text = product_text(listings.get(str(product.get("product_id")), []))
        if fields and len(text) >= MIN_TEXT:
            yield product, fields, text


def run(*, limit: int | None = None, dry_run: bool = False, offline: bool = False,
        audit: int | None = None, verbose: bool = True) -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    extractor = Extractor(offline=offline)
    summary = {"model": ",".join(m or "?" for _, m in extractor.providers), "mode": "audit" if audit else "fill",
               "products": 0, "fields_asked": 0, "claimed": 0, "verified": 0}
    entries = _load_entries()
    tally: dict = defaultdict(lambda: defaultdict(
        lambda: {"overlap": 0, "agree": 0, "examples": []}))      # model -> category.field -> slot
    _, backtest = _scripts()
    est_in = 0
    for product, fields, text in _requests(catalog, audit):
        if limit is not None and summary["products"] >= limit:
            break
        summary["products"] += 1
        summary["fields_asked"] += len(fields)
        category = product["category"]
        if dry_run:
            est_in += (len(prompt(category, fields, text)) + 1200) // 3
            continue
        try:
            claims = extractor.facts(category, fields, text)
        except NoKey as error:
            print(f"[extract] STOP: {error}. Add the secret, or use --dry-run.")
            summary["stopped"] = str(error)
            break
        except RateLimited as error:
            print(f"[extract] rate limited ({error}); answers so far are cached, "
                  "re-run later to continue.")
            summary["rate_limited"] = True
            summary["daily_quota"] = error.daily
            break
        specs: dict = {}
        quotes: dict = {}
        for claim in claims or []:
            summary["claimed"] += 1
            field = claim.get("field")
            if field not in fields or field in specs:
                continue
            value = verified(category, field, claim.get("value"), claim.get("quote"), text)
            if value is None:
                continue
            summary["verified"] += 1
            specs[field], quotes[field] = value, claim.get("quote")
        if audit:
            for field, value in specs.items():
                slot = tally[extractor.last_model][f"{category}.{field}"]
                slot["overlap"] += 1
                actual = product["specs"].get(field)
                if backtest.agrees(category, field, value, actual):
                    slot["agree"] += 1
                elif len(slot["examples"]) < 3:
                    slot["examples"].append([product.get("canonical_name"), value, actual,
                                             quotes[field]])
        elif specs:
            entries[str(product["product_id"])] = {
                "category": category, "model": extractor.last_model,
                "text_hash": text_hash(text), "specs": specs, "quotes": quotes}
    summary.update(requests=extractor.requests, cached=extractor.cached,
                   refused=extractor.refused, input_tokens=extractor.input_tokens,
                   output_tokens=extractor.output_tokens)
    if summary.get("stopped"):
        pass                              # nothing was asked: write nothing
    elif dry_run:
        summary["estimated_input_tokens"] = est_in
        summary["estimated_usd"] = round(est_in / 1e6 * _PRICE_IN
                                         + summary["fields_asked"] * 40 / 1e6 * _PRICE_OUT, 2)
    elif audit:
        _write_trust(tally)
    elif summary["products"]:
        _write_entries(entries)
    if verbose:
        print("[extract] " + ", ".join(f"{k}={v}" for k, v in summary.items()))
        if audit and not dry_run:
            _print_trust(tally)
    return summary


def _load_entries() -> dict:
    try:
        data = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("schema_version") != schema.SCHEMA_VERSION:
        return {}
    return data.get("entries") or {}


def _write_entries(entries: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS.write_text(json.dumps({
        "schema_version": schema.SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "entries": dict(sorted(entries.items()))}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")


def _write_trust(tally: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    old = trust_models()
    for model, fields in tally.items():
        merged = old.setdefault(model, {})
        for key, slot in fields.items():
            prev = merged.get(key) or {"overlap": 0, "agree": 0, "examples": []}
            merged[key] = {"overlap": prev["overlap"] + slot["overlap"],
                           "agree": prev["agree"] + slot["agree"],
                           "examples": (prev.get("examples") or []) + slot["examples"]}
    TRUST.write_text(json.dumps({
        "prompt_version": PROMPT_VERSION,
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "models": {model: {"fields": dict(sorted(fields.items()))}
                   for model, fields in sorted(old.items())}},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _print_trust(tally: dict) -> None:
    for model, fields in sorted(tally.items()):
        print(f"== {model}")
        print(f"{'category.field':<36}{'overlap':>8}{'agree':>7}{'disagree%':>11}")
        for key, slot in sorted(fields.items()):
            rate = 1 - slot["agree"] / slot["overlap"]
            print(f"{key:<36}{slot['overlap']:>8}{slot['agree']:>7}{rate * 100:>10.1f}%")
            if rate > MAX_DISAGREE:
                for name, ours, theirs, quote in slot["examples"]:
                    print(f"      model={ours!r} sourced={theirs!r} quote={quote!r}  {str(name)[:50]}")
