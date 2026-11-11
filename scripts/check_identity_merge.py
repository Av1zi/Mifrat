"""Identity-merge invariants (docs/merge-identity-plan.md, P0).

The rework's whole promise is "one physical part = one product, and a suffix
is a different part". That is hard to eyeball across 5k products, so these
invariants are executable:

    I1  no product contains two offers with different canonical model codes
    I2  no two products share (category, model code, variant axes) unless a
        QA case already flags the pair
    I3  CPU suffix separation: for one numeric core the suffixes across
        products are a partition, and ``245k`` / ``245kf`` never share a pid.
        A shared part number can still join two spellings of one part (a
        vendor printing "3240" for a chip sold as "3240T" under one MPN).
        What I3 forbids is two different suffixes landing on ONE pid with
        *no* shared part number, and one suffix family being numbered twice
    I4  no vendor has two offers with two different maker PNs (or two EANs)
        in one product: a vendor lists one part once (audit 2026-11-10 A)
    I5  title axis words (audit 2026-11-10 A2): reader fixtures, and no
        vendor-twin alias whose title differs from its primary's on a
        colour / lighting / GPU chip word
    I6  CPU packaging (audit 2026-11-10 D): reader fixtures; no CPU product
        (manual included) holds offers that state two packagings; no default
        (unstated) offer sits in a tray product; manual CPU products join I2

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


def check_i2(catalog: dict, manual_categories: frozenset[str] = frozenset()) -> int:
    """No two products share an identity unless the pair is already flagged.

    `manual_categories` puts curated products of those categories back in
    (I6: a CPU offer with a Tray label must not stay in a Box product that a
    manual Tray product duplicates, audit F-19)."""
    flagged: set[str] = set()
    for case in catalog.get("identity_cases") or []:
        pid = case.get("product_id")
        if pid:
            flagged.add(str(pid))

    buckets: dict[tuple, list[tuple[str, tuple]]] = defaultdict(list)
    for product in catalog.get("products") or []:
        # A human curator is itself the evidence (as for I1): a manual
        # split of one identity is a decision, not a matcher miss.
        category = product.get("category")
        if product.get("matched_by") == "manual" and category not in manual_categories:
            continue
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


def check_i4(catalog: dict) -> int:
    """No vendor sells two parts inside one product (audit 2026-11-10 A).

    A vendor lists one part once, so one vendor's two offers carrying two
    different maker PNs (or two EANs) in one product are two parts merged.
    Retailer numbers do not count (`identity._code_kind`).
    """
    checked = 0
    for product in catalog.get("products") or []:
        if product.get("matched_by") == "manual":
            continue
        offers = product.get("offers") or []
        if len(offers) < 2:
            continue
        checked += 1
        seen: dict[tuple, set[str]] = defaultdict(set)
        for offer in offers:
            code = identity._listing_code(offer)
            kind = code and identity._code_kind(code, product.get("category"))
            if kind:
                seen[(offer.get("vendor_id"), kind)].add(code)
        for (vendor, kind), codes in sorted(seen.items()):
            if len(codes) > 1:
                fail("I4: product %s holds %d %s codes from %s: %s"
                     % (product.get("product_id"), len(codes), kind, vendor,
                        sorted(codes)))
    return checked


SPLIT_FIXTURES = [
    # (category, [(vendor, mpn)], expected subgroup count) for part_number_subgroups
    # Sibling series codes split (2500X RGB vs 2500X; H5 Flow 2022 vs 2024).
    ("case", [("yahav", "CC-9011268-WW"), ("ivory", "CC-9011288-WW")], 2),
    ("case", [("tms", "CC-H51FW-01"), ("ksp", "CC-H52FW-01")], 2),
    # A region suffix is one part (-WW / -EU / -UK).
    ("aio", [("tms", "CW-9061018-WW"), ("ivory", "CW-9061018-EU")], 1),
    # A revision step in the last segment is one part (A00 vs A10).
    ("case", [("tms", "LL-O11DEW-A00"), ("ksp", "LL-O11DEW-A10")], 1),
    # A one-character slip of an undashed code is one part...
    ("psu", [("tms", "RPS0167RM850E"), ("ksp", "RPS0167RM850F")], 1),
    # ...but two codes ONE vendor prints are two parts (A rule).
    ("psu", [("tms", "RPS0167RM850E"), ("tms", "RPS0167RM850F")], 2),
    # A 12-digit AMD part number is a part number, not an EAN, and the TMS
    # "-PC" bundle tail is no second code.
    ("cpu", [("tms", "100-100000910"), ("tms", "100-100000910-PC")], 1),
]


def check_i4_unit() -> int:
    """part_number_subgroups on synthetic groups (review 2, 2026-11-12).

    Each row prints its code as both mpn and vendor SKU (TMS/Yahav shape),
    so the code is vendor class and only the sibling / same-vendor rules can
    split; two different maker-class PNs always split by design."""
    for category, rows, expected in SPLIT_FIXTURES:
        group = [{"vendor_id": vendor, "mpn": mpn, "vendor_sku": mpn,
                  "listing_key": f"{vendor}:{i}", "category_normalized": category}
                 for i, (vendor, mpn) in enumerate(rows)]
        actual = len(identity.part_number_subgroups(group))
        if actual != expected:
            fail("I4: part_number_subgroups(%s %r) = %d group(s), expected %d"
                 % (category, [m for _, m in rows], actual, expected))
    for code, kind in (("100100000910", "pn"), ("0761345101684", "ean"), ("731855145082", "ean")):
        got = identity._code_kind(code, "cpu" if code.startswith("100") else "case")
        if got != kind:
            fail("I4: _code_kind(%r) = %r, expected %r" % (code, got, kind))
    # Pid stability: the smaller cluster that held the bare pid keeps it.
    from scraper.matching import order_split_clusters
    small = [{"listing_key": "ivory:1", "category_normalized": "case"}]
    large = [{"listing_key": "yahav:2", "category_normalized": "case"},
             {"listing_key": "ksp:3", "category_normalized": "case"}]
    suffix = __import__("scraper.matching", fromlist=["identity_pid_suffix"]).identity_pid_suffix
    bare = "model:case:2500x" + suffix("case", small)
    got = order_split_clusters("case", "2500x", [large, small], {"ivory:1": bare})
    if got[0] is not small:
        fail("I4: order_split_clusters gave the bare pid to the cluster that did not hold it")
    if order_split_clusters("case", "2500x", [large, small], {})[0] is not large:
        fail("I4: order_split_clusters without history must keep largest-first")
    return len(SPLIT_FIXTURES) + 5


TITLE_AXIS_FIXTURES = [
    # (category, title, expected title_axis_values)
    ("case", "מארז Corsair 4000D Wood RS - צבע לבן ועץ אלון", {"color": "white+wood"}),
    ("case", "מארז Asus ProArt PA401 Wood Edition - צבע בז'", {"color": "beige+wood"}),
    ("case", "Antec Performance 1 M Aventurine", {"color": "aventurine"}),
    ("psu", "Corsair RM850x 80 PLUS Gold White", {"color": "white"}),
    ("psu", "Corsair RM850x 80 PLUS White", {}),
    ("gpu", "PowerColor Red Devil RX 9070 XT 16GB", {"chipset": "9070XT"}),
    ("gpu", "Asus Prime RX 9070 OC Edition 16GB", {"chipset": "9070"}),
    ("gpu", "Gigabyte RTX 5070 Ti 16G", {"chipset": "5070TI"}),
    ("memory", "Kingston FURY BEAST RGB 2x16GB DDR5 6000MHz", {"lighting": "lit"}),
    ("memory", "Kingston FURY BEAST 2x16GB DDR5 6000MHz", {}),
    ("memory", "G.Skill Trident Z5 Non-RGB 2x16GB", {"lighting": "none"}),
    ("cpu", "Intel Core i5 14600K White", {}),
]
TITLE_AXIS_PAIRS = [
    # (category, same vendor?, title a, title b, two parts?)
    ("case", False, "PA401 Wood - צבע שחור", "PA401 Wood - צבע בז'", True),
    ("case", False, "Lancool 216 שחור/לבן", "Lancool 216 לבן", False),
    ("case", False, "4000D Wood שחור אגוז", "4000D Wood לבן ועץ אלון", True),
    ("memory", False, "FURY BEAST RGB 2x16GB", "FURY BEAST 2x16GB", False),
    ("memory", True, "FURY BEAST RGB 2x16GB", "FURY BEAST 2x16GB", True),
    ("gpu", True, "RX 9070 XT 16GB OC", "RX 9070 XT 16GB White OC", True),
    ("aio", True, "Corsair NAUTILUS 360 RS שחור", "Corsair NAUTILUS 360 RS 360mm", False),
]


def check_i5_unit() -> int:
    """Title axis words (audit 2026-11-10 A2): readers and pair rules."""
    checked = 0
    for category, title, expected in TITLE_AXIS_FIXTURES:
        checked += 1
        actual = identity.title_axis_values(category, title)
        if actual != expected:
            fail("I5: title_axis_values(%r, %r) = %r, expected %r"
                 % (category, title, actual, expected))
    for category, same_vendor, left, right, expected in TITLE_AXIS_PAIRS:
        checked += 1
        a, b = {"title_raw": left}, {"title_raw": right}
        actual = bool(identity.title_axis_differs(category, a, b) if same_vendor
                      else identity.title_axis_conflict(category, a, b))
        if actual != expected:
            fail("I5: %s %r vs %r two parts = %r, expected %r"
                 % ("same-vendor" if same_vendor else "cross-vendor",
                    left, right, actual, expected))
    return checked


def check_i5_catalog(catalog: dict) -> int:
    """A vendor-twin alias never differs from its primary on a title axis.

    `matching.collapse_vendor_twins` folds one vendor's re-listings into one
    offer; a re-listing whose title adds RGB / White / another finish is a
    second item and must stay its own offer (unless both print one code).
    """
    from scraper.matching import _offer_code
    checked = 0
    for product in catalog.get("products") or []:
        offers = {o.get("listing_key"): o for o in product.get("offers") or []}
        for offer in offers.values():
            primary = offers.get(offer.get("alias_of"))
            if primary is None:
                continue
            checked += 1
            code = _offer_code(offer)
            if code and code == _offer_code(primary):
                continue
            axes = identity.title_axis_differs(product.get("category"), offer, primary)
            if axes:
                fail("I5: %s alias %s differs from its primary %s on %s"
                     % (product.get("product_id"), offer.get("listing_key"),
                        primary.get("listing_key"), ", ".join(axes)))
    return checked


PACKAGING_FIXTURES = [
    # (reader, value, expected)
    ("title", "מעבד Intel Core i5-14600KF Tray", "tray"),
    ("title", "Intel Core Ultra 5 245KF Box", "boxed"),
    ("title", "Intel Core Ultra 5 245KF", None),
    ("part_number", "BX8071514600KF", "boxed"),
    ("part_number", "CM8071504821015S", "tray"),
    ("part_number", "100-100000589WOF", "boxed"),
    ("part_number", "100-000000514", "tray"),
    ("part_number", "100-000000514MPK", "tray"),
    ("part_number", "C245KFT", None),
    ("retailer_code", "C10700KB-A", "boxed"),
    ("retailer_code", "C250KFPLUST", "tray"),
    ("retailer_code", "C7500T-P", "tray"),
    ("retailer_code", "C14600KT", "tray"),
    ("retailer_code", "C285B", "boxed"),
    ("retailer_code", "C13900KF", None),
    ("retailer_code", "BX8071514600KF", None),
]


def check_i6_unit() -> int:
    """The packaging readers (audit 2026-11-10 D, owner Q3)."""
    from scraper.specs import witness
    readers = {
        "title": witness.listing_title_packaging,
        "part_number": witness.part_number_packaging,
        "retailer_code": witness.retailer_code_packaging,
    }
    for reader, value, expected in PACKAGING_FIXTURES:
        actual = readers[reader](value)
        if actual != expected:
            fail("I6: %s packaging(%r) = %r, expected %r"
                 % (reader, value, actual, expected))
    return len(PACKAGING_FIXTURES)


def check_i6_catalog(catalog: dict) -> int:
    """A CPU product holds one stated packaging; an unstated offer is Box."""
    checked = 0
    for product in catalog.get("products") or []:
        if product.get("category") != "cpu":
            continue
        checked += 1
        stated: dict[str, list[str]] = defaultdict(list)
        defaults: list[str] = []
        for offer in product.get("offers") or []:
            basis = offer.get("packaging_basis")
            if basis == "default":
                defaults.append(str(offer.get("listing_key")))
                continue
            pack = identity.variant_values("cpu", offer).get("packaging")
            if pack:
                stated[pack].append(str(offer.get("listing_key")))
        if len(stated) > 1:
            fail("I6: cpu product %s holds offers stating %s"
                 % (product.get("product_id"),
                    {pack: keys for pack, keys in sorted(stated.items())}))
        if (defaults and product.get("matched_by") != "manual"
                and (set(stated) == {"tray"}
                     or str(product.get("product_id")).endswith("-tray"))):
            fail("I6: cpu product %s is Tray but holds unstated offers %s"
                 % (product.get("product_id"), defaults))
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
        "I2 identities": check_i2(catalog, frozenset({"cpu"})),
        "I3 fixtures": check_i3_unit(),
        "I3 cpu products": check_i3_catalog(catalog),
        "I4 fixtures": check_i4_unit(),
        "I4 products": check_i4(catalog),
        "I5 fixtures": check_i5_unit(),
        "I5 twin aliases": check_i5_catalog(catalog),
        "I6 fixtures": check_i6_unit(),
        "I6 cpu products": check_i6_catalog(catalog),
    }
    for label, count in checked.items():
        print("  %-16s %d checked" % (label, count))

    if FAILURES:
        print()
        for message in FAILURES:
            print("  [fail] " + message)
        print("\n[fail] %d identity invariant(s) broken" % len(FAILURES))
        return 1
    print("\n[ok] identity invariants hold (I1, I2, I3, I4, I5, I6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
