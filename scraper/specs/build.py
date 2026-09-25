"""
specs/build.py — orchestration: raw listings -> typed facts -> merged specs.

Two entry points:

- `build_listing_attributes(listing)` — per-listing pass, called from
  matching.enrich_listing(). Resolves tiers 1-3 for ONE listing and returns
  the derived `attributes` view, so matching keeps working unchanged.
- `build_product_specs(products, listings)` — product-level pass, called from
  normalize_and_match after match_listings(). Merges every offer's facts plus
  Tier-0 reference data and manual overrides into `product["specs"]`, applies
  cross-field validation, sets `spec_sources`, re-derives `attributes`, and
  returns the coverage report.

Order inside the product pass matters and is deliberate:
1. collect per-offer facts (tier 1-3) and the post-match bridge values;
2. provisional merge (no Tier 0) -> anchors + the legacy view;
3. reference matching with those anchors (plan §5), plus overrides;
4. final merge with all tiers -> the authoritative sheet;
5. cross-field checks, fill derived fields, projection to `attributes`.
"""

from __future__ import annotations

from . import legacy
from . import text as text_module
from .derive import infer_specs
from .merge import TIER_REFERENCE, Fact, merge_facts
from .resolvers import reference, title_parse, vendor_struct, weak_vendor
from .validate import cross_check, fill_derived, revalidate_derived


def listing_text(listing: dict) -> str:
    """The text Tier-2 parses: match_text plus Ivory prose (same as before)."""
    meta = listing.get("vendor_meta") or {}
    text_value = listing.get("match_text") or text_module.clean_text(
        f"{listing.get('vendor_sku', '')} {listing.get('title_raw', '')}")
    extra = " ".join(
        str(meta[key]) for key in ("title", "description")
        if isinstance(meta.get(key), str)
    )
    if extra:
        text_value = f"{text_value} {text_module.clean_text(extra)}"
    return text_value.strip()


def listing_facts(category: str | None, listing: dict) -> dict[str, list[Fact]]:
    """Every tier 1-3 fact for one listing."""
    facts = vendor_struct.parse_vendor_struct(category, listing)
    for key, value in title_parse.parse_title(category, listing_text(listing)).items():
        facts.setdefault(key, []).extend(value)
    for key, value in weak_vendor.parse_weak(category, listing).items():
        facts.setdefault(key, []).extend(value)
    for key, value in vendor_struct.parse_listing_identity(category, listing).items():
        facts.setdefault(key, []).extend(value)
    return facts


def build_listing_attributes(listing: dict) -> dict:
    """Derived `attributes` view for one enriched listing (matching's input)."""
    category = listing.get("category_normalized") or ""
    facts = listing_facts(category, listing)
    merged = merge_facts(category, facts, run_validators=False)
    return legacy.to_attributes(category, merged.specs)


def reference_query(product: dict, specs: dict, category: str | None) -> str:
    """Cleanest available query text for a reference lookup."""
    if category in ("cpu", "gpu"):
        parts = (specs.get("manufacturer") or product.get("brand") or "",
                 specs.get("model") if category == "cpu" else specs.get("chipset"))
        combined = " ".join(str(part) for part in parts if part).strip()
        # A bare brand ("AMD", "Gigabyte") matches everything and nothing:
        # fall back to the canonical name unless we have a real model/chip.
        if len(combined.split()) >= 2:
            return combined
    return str(product.get("canonical_name") or "")


def _pckombo_facts(category: str | None, pckombo: dict) -> dict[str, list[Fact]]:
    """Exact-MPN reference facts from the PC Kombo dataset (Tier 0)."""
    specs = pckombo.get("specs") if isinstance(pckombo, dict) else None
    if not isinstance(specs, dict):
        return {}
    facts: dict[str, list[Fact]] = {}
    for key, value in vendor_struct.ingest_computed_attributes(category, specs).items():
        for fact in value:
            facts.setdefault(key, []).append(
                Fact(value=fact.value, tier=TIER_REFERENCE,
                     source="reference:pckombo", confidence=0.95))
    return facts


def _extras(product: dict) -> dict:
    """Non-schema attribute keys worth carrying into the derived view."""
    allowed = ("bundle_only",)
    attributes = product.get("attributes") or {}
    return {key: attributes[key] for key in allowed if key in attributes}


def build_product_specs(products: list[dict], listings: list[dict] | None = None,
                        *, report=None, verbose: bool = True) -> dict:
    """Merge and validate specs for every product (mutates `products`)."""
    from .report import CoverageReport

    if report is None:
        report = CoverageReport()

    by_product: dict[str, list[dict]] = {}
    for listing in listings or []:
        product_id = listing.get("product_id")
        if product_id:
            by_product.setdefault(str(product_id), []).append(listing)

    derived_total = 0

    for product in products:
        category = product.get("category")
        facts: dict[str, list[Fact]] = {}

        for listing in by_product.get(str(product.get("product_id")), []):
            for key, value in listing_facts(category, listing).items():
                facts.setdefault(key, []).extend(value)

        # Post-match bridge: `attributes` computed during matching (brand,
        # model, mpn, accessory_type, product-level merges).
        for key, value in vendor_struct.ingest_computed_attributes(
                category, product.get("attributes")).items():
            facts.setdefault(key, []).extend(value)

        provisional = merge_facts(category, facts).specs

        # Tier 0 — anchor-verified reference row + exact-MPN PC Kombo specs.
        query = reference_query(product, provisional, category)
        match = reference.match_reference_row(category, query, provisional)
        reference_row, score, method = match or (None, None, None)
        if reference_row is not None:
            confidence = min(1.0, float(score or 0) / 100.0)
            for key, value in reference.reference_facts(
                    category, reference_row, confidence).items():
                facts.setdefault(key, []).extend(value)
        for key, value in _pckombo_facts(category, product.get("pckombo") or {}).items():
            facts.setdefault(key, []).extend(value)

        # Manual overrides are king.
        for key, value in reference.overrides_for(product).items():
            facts.setdefault(key, []).extend(value)

        merged = merge_facts(category, facts)
        fill_derived(category, merged.specs, merged.sources)
        # cross_check FIRST, then inference. The order matters: a consistency
        # rule may null a contradictory value (a tray CPU that claims a bundled
        # cooler), and inference only ever fills nulls — running it before the
        # drop left those fields empty even though the rule that emptied them
        # implies the answer. Inference reads packaging/socket/etc., never the
        # fields cross_check drops, so nothing it writes is checked afterwards.
        issues = cross_check(category, merged.specs, merged.sources)
        derived_fields = infer_specs(category, merged.specs, merged.sources)
        # Inference is intentionally untrusted output: validate both its
        # individual values and any new cross-field relationships.
        issues.extend(revalidate_derived(
            category, merged.specs, merged.sources))
        issues.extend(cross_check(category, merged.specs, merged.sources))
        derived_total += len(derived_fields)

        product["specs"] = merged.specs
        product["spec_sources"] = merged.sources
        product["attributes"] = legacy.to_attributes(
            category, merged.specs, passthrough=_extras(product))
        # The reference sidecars are redundant now: their facts are merged.
        product.pop("pcpartdb", None)
        product.pop("pckombo", None)

        report.add_product(
            product_id=str(product.get("product_id") or ""),
            category=category,
            specs=merged.specs,
            sources=merged.sources,
            conflicts=merged.conflicts_as_dicts(),
            invalid=merged.invalid_as_dicts(),
            reference={"matched": reference_row is not None, "method": method,
                       "score": round(score, 1) if score is not None else None,
                       "name": (reference_row or {}).get("name")},
            issues=issues,
        )

    if verbose:
        report.print_summary()
        if derived_total:
            print(f"[specs] {derived_total} field(s) filled by rule-based "
                  "inference (source=derived:<rule>)")
    return report.to_dict()
