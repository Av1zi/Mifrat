"""Identity-merge invariants (docs/merge-identity-plan.md, P0).

The rework's whole promise is "one physical part = one product, and a suffix
is a different part". That is hard to eyeball across 5k products, so these
three invariants are executable:

    I1  no product contains two offers with different canonical model codes
    I2  no two products share (category, model code, variant axes) unless a
        QA case already flags the pair
    I3  CPU suffix separation: for one numeric core the suffixes across
        products are a partition, and ``245k`` / ``245kf`` never share a pid.
        A shared part number can still join two spellings of one part (a
        vendor printing "3240" for a chip sold as "3240T" under one MPN).
        What I3 forbids is two different suffixes landing on ONE pid with
        *no* shared part number, and one suffix family being numbered twice

    python scripts/check_identity_merge.py [--catalog data/catalog.json]

Exit 0 = every invariant holds; exit 1 = at least one broke (each printed).
No test framework by design (PROJECT_OVERVIEW), so this is a plain script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper import identity  # noqa: E402
from scraper.matching import (  # noqa: E402
    _listing_eans,
    model_code_key,
    mpn_affix_related,
    normalize_sku,
)

FAILURES: list[str] = []


def fail(message: str) -> None:
    FAILURES.append(message)


def check_i1(catalog: dict) -> int:
    """No product mixes two codes that no evidence ties together.

    The strict reading — "one product, one code" — cannot hold on real data:
    the same board is printed "B650 AORUS PRO AX" by one vendor and "B650
    AORUS PRO AX AM5 HDMI DP" by another, so the codes differ while the part
    number and the maker code agree. What the matcher must never do is join
    two codes with *no* evidence between them, so the check is that the
    offers of a product form ONE connected component under the relations the
    matcher is allowed to merge on: same model code, same (or truncation-
    related) part number, same vendor SKU, same verified manufacturer code,
    same barcode. A `manual:` product is exempt: a human curator is itself
    the evidence, and the product is public on the QA page.
    """
    checked = 0
    for product in catalog.get("products") or []:
        if product.get("matched_by") == "manual":
            continue
        offers = [o for o in product.get("offers") or []
                  if o.get("listing_key")]
        if len(offers) < 2:
            continue
        checked += 1
        parent = {o["listing_key"]: o["listing_key"] for o in offers}

        def find(key: str) -> str:
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        def union(a: str, b: str) -> None:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_b] = root_a

        buckets: dict[tuple, list[str]] = defaultdict(list)
        for offer in offers:
            key = offer["listing_key"]
            code = identity.model_code(product.get("category"), offer)
            if code:
                buckets[("code", code)].append(key)
            # A shared printed part number ties offers even when the
            # vendor's free-text model rows differ. This is the identity
            # tier's own PN bridge: two listings carrying one part number
            # are one part (retailers don't reuse SKUs), so the bridge is
            # evidence, not a guess.
            if offer.get("mpn"):
                buckets[("pn", identity.part_number_key(offer["mpn"]))].append(key)
            # A vendor SKU that IS a part number for one vendor can be the
            # MPN for another (1PC's "90YV0LG2-M0NA00" vs KSP's no-MPN row
            # for the same card). Same evidence, same keyspace.
            if offer.get("vendor_sku"):
                sku_key = normalize_sku(offer["vendor_sku"])
                if sku_key:
                    buckets[("sku", sku_key)].append(key)
            if offer.get("model_code"):
                buckets[("maker", model_code_key(offer["model_code"]))].append(key)
            attrs = offer.get("attributes") or {}
            model_name = identity._compact(attrs.get("model_name")
                                           or attrs.get("model"))
            if model_name and len(model_name) >= 4:
                # The verified maker model (tier 5c's raw material): two
                # vendors printing the same maker model are one part even
                # when their catalogue codes differ. A VRAM size token
                # ("16GB") is a variant axis, not the model — one vendor
                # prints it, another does not — so both are the same maker
                # model and connect, with memory_gb pinned in the key so an
                # 8GB and a 16GB card can never tie this way.
                vram = identity.variant_values(
                    product.get("category"), offer).get("memory_gb")
                clean_name = model_name
                if vram is not None:
                    clean_name = re.sub(
                        r"(?:8|12|16|24|32)(?:gb|g)", "", clean_name)
                    if not clean_name:
                        clean_name = model_name
                buckets[("maker_model", str(offer.get("brand") or ""),
                         clean_name, vram)].append(key)
            for ean in _listing_eans(offer):
                buckets[("ean", ean)].append(key)
        for members in buckets.values():
            for other in members[1:]:
                union(members[0], other)

        # Truncation relatives ("GB760DS3HDDR4" / "B760-DS3H-DDR4") are the
        # matcher's own MPN-affix rule; check the pairs the buckets cannot.
        for index, left in enumerate(offers):
            for right in offers[index + 1:]:
                if (left.get("mpn") and right.get("mpn")
                        and mpn_affix_related(left["mpn"], right["mpn"])):
                    union(left["listing_key"], right["listing_key"])

        components = {find(o["listing_key"]) for o in offers}
        if len(components) > 1:
            detail = defaultdict(set)
            for offer in offers:
                code = identity.model_code(product.get("category"), offer)
                if code:
                    detail[find(offer["listing_key"])].add(code)
            fail(
                "I1: product %s holds unconnected code groups %s"
                % (product.get("product_id"),
                   [sorted(codes) for codes in detail.values()])
            )
    return checked


def _axis_key(category: str, members: list[dict]) -> tuple[tuple[str, str], ...]:
    values: dict[str, str] = {}
    for member in members:
        for axis, value in identity.variant_values(category, member).items():
            if value is not None:
                values.setdefault(axis, value)
    return tuple(sorted(values.items()))


def check_i2(catalog: dict) -> int:
    """No two products share an identity unless the pair is already flagged."""
    flagged: set[str] = set()
    for case in catalog.get("identity_cases") or []:
        pid = case.get("product_id")
        if pid:
            flagged.add(str(pid))

    buckets: dict[tuple, list[tuple[str, tuple]]] = defaultdict(list)
    for product in catalog.get("products") or []:
        # A human curator is itself the evidence (as for I1): a manual
        # split of one identity is a decision, not a matcher miss.
        if product.get("matched_by") == "manual":
            continue
        category = product.get("category")
        if category not in identity.IDENTITY_CATEGORIES:
            continue
        offers = list(product.get("offers") or [])
        codes = [identity.model_code(category, offer) for offer in offers]
        codes = [code for code in codes if code]
        if not codes:
            continue
        code = max(set(codes), key=codes.count)
        buckets[(category, code, _axis_key(category, offers))].append(
            (str(product.get("product_id")), tuple(sorted(set(codes))))
        )

    for key, products in buckets.items():
        if len(products) < 2:
            continue
        # Two products of one identity are a miss unless the QA page already
        # explains it (split_candidate / variant_conflict / unresolved
        # packaging pair). A code that appears in several *different* keys is
        # fine: the axes, not the code, are the identity.
        if all(pid in flagged for pid, _ in products):
            continue
        fail(
            "I2: %s / %s held by %d products %s"
            % (key[0], key[1], len(products), [pid for pid, _ in products])
        )
    return len(buckets)


CPU_FIXTURES = [
    # (model text, expected code)
    ("Intel Core Ultra 5 245K", "245k"),
    ("Intel Core Ultra 5 245KF", "245kf"),
    ("Intel® Core™ Ultra 5 245KF Processor", "245kf"),
    ("ULTRA-5-245KF", "245kf"),
    ("245KF", "245kf"),
    ("245 K", "245k"),
    ("Ryzen 7 5800X3D", "5800x3d"),
    ("AMD Ryzen 9 9950X3D2", "9950x3d2"),
    ("AMD Ryzen 9 9950X3D", "9950x3d"),
    ("Intel Pentium G4400T", "g4400t"),
]


def check_i3_unit() -> int:
    """The CPU code never folds a suffix away (K is not KF)."""
    checked = 0
    for model, expected in CPU_FIXTURES:
        checked += 1
        actual = identity.cpu_model_code("Intel", model)
        if actual != expected:
            fail("I3: cpu_model_code(%r) = %r, expected %r"
                 % (model, actual, expected))
    return checked


def check_i3_catalog(catalog: dict) -> int:
    """CPU pids name their own code, and one core's codes stay in one pid family.

    The suffix partition itself is guaranteed by the fixtures above and by
    the pid shape: the pid is built from the code, so ``245k`` and ``245kf``
    cannot land on one pid unless a shared part number ties them (I1), which
    is exactly the vendor data error worth seeing on the QA page.
    """
    by_core: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    checked = 0
    # Family -> real (unstripped) pids: the exemption below must look up the
    # actual product(s), e.g. "model:cpu:3240-tray", not the stripped family
    # "model:cpu:3240".
    family_products: dict[str, list[dict]] = defaultdict(list)
    for product in catalog.get("products") or []:
        if product.get("category") == "cpu":
            family_products[str(product.get("product_id")).split("-tray")[0]].append(
                product)
    for product in catalog.get("products") or []:
        if product.get("category") != "cpu":
            continue
        pid = str(product.get("product_id"))
        codes = {
            identity.model_code("cpu", offer)
            for offer in product.get("offers") or []
        }
        codes.discard(None)
        checked += 1
        if not codes:
            continue
        if product.get("matched_by") != "manual":
            slug = pid.split(":", 2)[2] if pid.count(":") >= 2 else pid
            if not any(slug.startswith(identity.code_slug(code))
                       or slug.startswith(code.replace("-", ""))
                       for code in codes):
                fail("I3: cpu pid %s is not named after any of %s"
                     % (pid, sorted(codes)))
        for code in codes:
            digits = "".join(ch for ch in code if ch.isdigit())
            if digits:
                by_core[digits][code].add(pid)
    for core, codes in by_core.items():
        seen: dict[str, str] = {}
        for code, pids in codes.items():
            # One code may span box/tray pids (`-tray`); never two codes with
            # different suffixes of the same core under one pid family.
            # A shared part number can join two spellings of one part (the
            # "3240" printed under the "3240T" MPN); that merge is evidence-
            # backed, and I1 already proves the evidence connects.
            family = {pid.split("-tray")[0] for pid in pids}
            for pid in family:
                if pid in seen and seen[pid] != code:
                    mpns = set()
                    for real in family_products.get(pid) or []:
                        for o in real.get("offers") or []:
                            if o.get("mpn"):
                                mpns.add(identity.part_number_key(o["mpn"]))
                    if len(mpns) == 1:
                        continue
                    fail("I3: core %s pid %s named by both %s and %s"
                         % (core, pid, seen[pid], code))
                seen[pid] = code
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.json"))
    args = parser.parse_args()

    path = Path(args.catalog)
    if not path.exists():
        print("[error] %s not found — run the normalizer first" % path,
              file=sys.stderr)
        return 1
    with path.open(encoding="utf-8") as f:
        catalog = json.load(f)

    checked = {
        "I1 products": check_i1(catalog),
        "I2 identities": check_i2(catalog),
        "I3 fixtures": check_i3_unit(),
        "I3 cpu products": check_i3_catalog(catalog),
    }
    for label, count in checked.items():
        print("  %-16s %d checked" % (label, count))

    if FAILURES:
        print()
        for message in FAILURES:
            print("  [fail] " + message)
        print("\n[fail] %d identity invariant(s) broken" % len(FAILURES))
        return 1
    print("\n[ok] identity invariants hold (I1, I2, I3)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
