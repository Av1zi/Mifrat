"""Gate: the published data set must be ONE run describing ONE product set.

`scraper/normalize_and_match.py` writes the whole publish set in one process —
`data/catalog.json`, every `data/site/<category>.json`, `index.json`,
`meta.json` and `spec_report.json` — but they are separate files, committed
separately, and three different boxes push them (the normalize job, the Nano,
a local run). Nothing verified that what actually landed in git came from one
run and describes the same products: on 2026-11-01 `main` carried a catalog
with 4,697 products while `data/site/*.json` and `spec_report.json` described
4,678. The 19 strays (14 gpu, 5 motherboard) were in the catalog and in no
site file, so the deployed site silently lost 19 products and `site-checks`
failed on the stale-report count — a whole failed run for a mismatch that a
single id-set comparison finds in a second.

That class of bug is not specific to a count: any partial copy (an interrupted
write, a hand-edited category file, a site tree copied from an older run, a
catalog rebuilt on its own) ships a site whose data files disagree with the
catalog and with each other. So this gate compares the ACTUAL PRODUCT IDS, per
category, not totals:

  1. every catalog product appears in exactly one `data/site/<category>.json`,
     and every row in those files exists in the catalog (a category file is
     matched to the catalog through `site_data.SITE_CATEGORY`, the same map
     that built it — aio + cooler_air -> cpu_cooler);
  2. `data/site/index.json` has exactly one row per catalog product;
  3. `data/site/meta.json` counts match the files and its `generated_at` is the
     catalog's, i.e. the same run wrote both;
  4. `data/site/spec_report.json` describes the catalog's products, in total
     and per category (the coverage dashboard and `check_spec_coverage.py`'s
     stale-report guard read it);
  5. a bundle-only offer (price only with a whole PC) is never the best offer
     or the site min_price while a plain offer is priced, and it ships to the
     site still flagged (owner answer Q1, audit 2026-11-10 cluster H);
  6. one site offer per vendor per part: a vendor twin (`alias_of`) never sets
     the best offer or ships as an offer, a priced whole-PC twin reaches its
     offer as the deal chip, and a vendor shown twice is flagged in
     `duplicate_vendors` (audit 2026-11-10 cluster P).

Pure stdlib + the repo's own site_category map, no network. Exit 0 = the set
is coherent; exit 1 = a mismatch (every trip printed with sample product ids).

Run:
    python scripts/check_publish_set.py              # after a normalize run
    python scripts/check_publish_set.py --self-test  # the gate's own checks
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.site_data import SITE_CATEGORY  # noqa: E402

CATALOG = ROOT / "data" / "catalog.json"
SITE_DIR = ROOT / "data" / "site"
META = SITE_DIR / "meta.json"
INDEX = SITE_DIR / "index.json"
REPORT = SITE_DIR / "spec_report.json"

# data/site files that are not one-category product lists.
NON_CATEGORY_FILES = {"meta.json", "qa.json", "index.json", "spec_report.json"}

# Product ids printed per trip, so a failure is diagnosable without a rerun.
SAMPLE = 5


def site_category(category: str) -> str:
    """Catalog category -> data/site file name (the writer's own map)."""
    return SITE_CATEGORY.get(category, category)


def _sample(ids) -> str:
    ordered = sorted(str(item) for item in ids)
    shown = ", ".join(ordered[:SAMPLE])
    rest = len(ordered) - SAMPLE
    return shown + (f" (+{rest} more)" if rest > 0 else "")


def check(catalog: dict, files: dict[str, list[str]], index_ids: list[str],
          meta: dict | None, report: dict | None) -> list[str]:
    """Run every coherence check against already-loaded publish files.

    Pure (no file access) so `--self-test` can pin each failure mode.
    `files` maps a data/site category file stem to the product ids it carries.
    """
    problems: list[str] = []
    products = catalog.get("products") or []
    catalog_ids = [str(product.get("product_id")) for product in products]

    if len(set(catalog_ids)) != len(catalog_ids):
        dupes = len(catalog_ids) - len(set(catalog_ids))
        problems.append(
            f"data/catalog.json lists {dupes} product id(s) more than once — "
            "one product, one row, or every downstream count double-counts it")

    expected: dict[str, set[str]] = defaultdict(set)
    for product in products:
        category = str(product.get("category") or "")
        expected[site_category(category)].add(str(product.get("product_id")))

    # 1. Per-category id sets: the site must carry every catalog product and
    #    nothing the catalog does not know about.
    for category in sorted(set(expected) | set(files)):
        want = expected.get(category, set())
        if category not in files:
            problems.append(
                f"data/site/{category}.json is missing: {len(want)} catalog "
                f"product(s) have no site row (e.g. {_sample(want)})")
            continue
        got = set(files[category])
        missing = want - got
        extra = got - want
        if missing:
            problems.append(
                f"{category}: {len(missing)} catalog product(s) are in "
                f"data/catalog.json but not in data/site/{category}.json "
                f"(e.g. {_sample(missing)})")
        if extra:
            problems.append(
                f"{category}: {len(extra)} row(s) in data/site/{category}.json "
                f"are not in data/catalog.json (e.g. {_sample(extra)})")

    # 2. index.json is the global lookup the search and every product page
    #    resolve through, so it must cover the catalog exactly once.
    index_set = set(index_ids)
    catalog_set = set(catalog_ids)
    if len(index_ids) != len(index_set):
        problems.append(
            f"data/site/index.json has {len(index_ids) - len(index_set)} "
            "duplicate row(s)")
    if index_set != catalog_set:
        missing = catalog_set - index_set
        extra = index_set - catalog_set
        detail = []
        if missing:
            detail.append(f"{len(missing)} catalog product(s) absent "
                          f"(e.g. {_sample(missing)})")
        if extra:
            detail.append(f"{len(extra)} unknown id(s) (e.g. {_sample(extra)})")
        problems.append("data/site/index.json does not match the catalog: "
                        + "; ".join(detail))

    # 3. meta.json: same run (generated_at) and counts that match the files.
    if meta is None:
        problems.append("data/site/meta.json is missing — the site cannot "
                        "boot without it")
    else:
        if str(meta.get("generated_at")) != str(catalog.get("generated_at")):
            problems.append(
                "data/site/meta.json was written by another run "
                f"(generated_at {meta.get('generated_at')!r} != catalog "
                f"{catalog.get('generated_at')!r}) — the site files and the "
                "catalog are not the same normalize run")
        declared = {str(entry.get("id")): int(entry.get("count") or 0)
                    for entry in (meta.get("categories") or [])}
        for category in sorted(set(declared) | set(files)):
            if category not in declared:
                problems.append(
                    f"data/site/meta.json has no entry for {category!r}, but "
                    f"data/site/{category}.json exists")
            elif category not in files:
                problems.append(
                    f"data/site/meta.json lists {category!r} with "
                    f"{declared[category]} products, but "
                    f"data/site/{category}.json does not exist")
            elif declared[category] != len(files[category]):
                problems.append(
                    f"data/site/meta.json says {category} has "
                    f"{declared[category]} products, the file has "
                    f"{len(files[category])}")

    # 4. The coverage dashboard must describe this catalog, in total and per
    #    category, or its numbers (and the stale-report guard) are fiction.
    if report is None:
        problems.append("data/site/spec_report.json is missing — the coverage "
                        "dashboard and the stale-report guard read it")
    else:
        declared_total = report.get("products")
        if declared_total is not None and int(declared_total) != len(products):
            problems.append(
                f"data/site/spec_report.json describes {declared_total} "
                f"products, data/catalog.json has {len(products)} — "
                "different runs")
        counted: dict[str, int] = defaultdict(int)
        for product in products:
            counted[str(product.get("category") or "")] += 1
        reported = {str(name): int((bucket or {}).get("products") or 0)
                    for name, bucket in (report.get("categories") or {}).items()}
        for category in sorted(set(reported) | set(counted)):
            if reported.get(category, 0) != counted.get(category, 0):
                problems.append(
                    f"data/site/spec_report.json counts {reported.get(category, 0)} "
                    f"{category} product(s), the catalog has "
                    f"{counted.get(category, 0)}")

    return problems


def _priced(price) -> bool:
    return isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0


def check_conditional_offers(catalog: dict, site_rows: dict[str, dict]) -> list[str]:
    """Owner Q1 (audit 2026-11-10 H): a bundle-only price never outranks a
    plain one, and every bundle-only offer reaches the site still flagged.

    `site_rows` maps a product id to its data/site row. Pure, like `check`.
    """
    problems: list[str] = []
    best_wins: list[str] = []
    min_wins: list[str] = []
    lost_flag: list[str] = []
    for product in catalog.get("products") or []:
        pid = str(product.get("product_id"))
        offers = product.get("offers") or []
        has_plain = any(_priced(o.get("price_ils")) and not o.get("bundle_only")
                        for o in offers)
        best = product.get("best_offer") or {}
        if has_plain and best.get("bundle_only"):
            best_wins.append(pid)
        row = site_rows.get(pid)
        if row is None:
            continue
        site_offers = row.get("offers") or []
        flagged = {(o.get("vendor"), o.get("url")) for o in site_offers if o.get("bundle_only")}
        for offer in offers:
            # A vendor twin (alias_of) ships as its offer's chip instead:
            # check_vendor_twins covers it.
            if offer.get("alias_of"):
                continue
            if offer.get("bundle_only") and (offer.get("vendor_id"), offer.get("url")) not in flagged:
                lost_flag.append(f"{pid} [{offer.get('listing_key')}]")
        plain_prices = [o.get("price") for o in site_offers
                        if _priced(o.get("price")) and not o.get("bundle_only")]
        min_price = row.get("min_price")
        if plain_prices and _priced(min_price) and min_price < min(plain_prices):
            min_wins.append(pid)
    if best_wins:
        problems.append(
            f"{len(best_wins)} product(s) have a bundle-only best offer while a "
            f"plain offer is priced (e.g. {_sample(best_wins)}) — "
            "matching.choose_best_offer must rank plain offers first")
    if min_wins:
        problems.append(
            f"{len(min_wins)} site row(s) take min_price from a bundle-only offer "
            f"below every plain price (e.g. {_sample(min_wins)})")
    if lost_flag:
        problems.append(
            f"{len(lost_flag)} bundle-only offer(s) reach data/site without their "
            f"flag (e.g. {_sample(lost_flag)}) — site_data._trim_offer must keep it")
    return problems


def check_vendor_twins(catalog: dict, site_rows: dict[str, dict]) -> list[str]:
    """Audit 2026-11-10 P: one site offer per vendor per part.

    A listing marked `alias_of` (matching.collapse_vendor_twins) never sets
    the best offer and never ships as an offer of its own; a priced whole-PC
    twin reaches its offer as the new-PC deal chip. A vendor shown twice
    must be one the row still lists in `duplicate_vendors`.
    """
    problems: list[str] = []
    best_alias: list[str] = []
    shipped: list[str] = []
    lost_deal: list[str] = []
    twice: list[str] = []
    for product in catalog.get("products") or []:
        pid = str(product.get("product_id"))
        offers = product.get("offers") or []
        if (product.get("best_offer") or {}).get("alias_of"):
            best_alias.append(pid)
        row = site_rows.get(pid)
        if row is None:
            continue
        site_offers = row.get("offers") or []
        urls = {(o.get("vendor"), o.get("url")) for o in site_offers}
        by_key = {o.get("listing_key"): o for o in offers}
        for offer in offers:
            if not offer.get("alias_of"):
                continue
            primary = by_key.get(offer["alias_of"]) or {}
            if (offer.get("vendor_id"), offer.get("url")) in urls and offer.get("url") != primary.get("url"):
                shipped.append(f"{pid} [{offer.get('listing_key')}]")
            if offer.get("alias_kind") == "bundle" and _priced(offer.get("price_ils")):
                target = next((o for o in site_offers
                               if (o.get("vendor"), o.get("url")) == (primary.get("vendor_id"), primary.get("url"))), {})
                if not (target.get("bundle_only") or target.get("new_pc_deal")):
                    lost_deal.append(f"{pid} [{offer.get('listing_key')}]")
        seen: dict[str, int] = defaultdict(int)
        for o in site_offers:
            seen[o.get("vendor")] += 1
        allowed = set(row.get("duplicate_vendors") or [])
        for vendor, count in seen.items():
            if count > 1 and vendor not in allowed:
                twice.append(f"{pid} [{vendor}]")
    if best_alias:
        problems.append(f"{len(best_alias)} product(s) take their best offer from a vendor "
                        f"twin (e.g. {_sample(best_alias)}) — choose_best_offer must skip alias_of")
    if shipped:
        problems.append(f"{len(shipped)} vendor twin(s) ship as their own site offer "
                        f"(e.g. {_sample(shipped)}) — site_data._site_offers must drop them")
    if lost_deal:
        problems.append(f"{len(lost_deal)} whole-PC twin(s) lost their deal chip "
                        f"(e.g. {_sample(lost_deal)})")
    if twice:
        problems.append(f"{len(twice)} site row(s) show one vendor twice without a "
                        f"duplicate_vendors flag (e.g. {_sample(twice)})")
    return problems


def load_site_rows() -> dict[str, dict]:
    """Product id -> data/site row, across every category file."""
    rows_by_id: dict[str, dict] = {}
    for path in sorted(SITE_DIR.glob("*.json")):
        if path.name in NON_CATEGORY_FILES:
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                rows_by_id[str(row.get("id"))] = row
    return rows_by_id


def load() -> tuple[dict, dict[str, list[str]], list[str], dict | None, dict | None]:
    """Read the committed publish set off disk."""
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    files: dict[str, list[str]] = {}
    for path in sorted(SITE_DIR.glob("*.json")):
        if path.name in NON_CATEGORY_FILES:
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            continue
        files[path.stem] = [str(row.get("id")) for row in rows if isinstance(row, dict)]
    index_rows = (json.loads(INDEX.read_text(encoding="utf-8"))
                  if INDEX.is_file() else [])
    index_ids = [str(row[0]) for row in index_rows
                 if isinstance(row, (list, tuple)) and row]
    meta = json.loads(META.read_text(encoding="utf-8")) if META.is_file() else None
    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.is_file() else None
    return catalog, files, index_ids, meta, report


def _fixture(per_category: int = 3) -> tuple[dict, dict, list[str], dict, dict]:
    """A coherent synthetic publish set: 3 categories, aio merged into cpu_cooler."""
    products = []
    for category in ("gpu", "motherboard", "aio"):
        for number in range(per_category):
            products.append({"product_id": f"{category}:{number}",
                             "category": category})
    catalog = {"generated_at": "2026-11-01T00:00:00+00:00",
               "products": products}
    files: dict[str, list[str]] = defaultdict(list)
    for product in products:
        files[site_category(product["category"])].append(product["product_id"])
    index_ids = [product["product_id"] for product in products]
    meta = {
        "generated_at": catalog["generated_at"],
        "categories": [{"id": name, "count": len(ids)}
                       for name, ids in files.items()],
    }
    report = {
        "products": len(products),
        "categories": {category: {"products": per_category}
                       for category in ("gpu", "motherboard", "aio")},
    }
    return catalog, dict(files), index_ids, meta, report


def self_test() -> int:
    """Pin the failure modes, including the 2026-11-01 one. No data files."""
    problems: list[str] = []

    def check_case(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            problems.append(f"{name}{(': ' + detail) if detail else ''}")

    def trips(catalog, files, index_ids, meta, report) -> str:
        return " | ".join(check(catalog, files, index_ids, meta, report))

    clean = _fixture()
    check_case("coherent set passes", not check(*clean), trips(*clean))

    # The 2026-11-01 failure: products in the catalog (and index) but in no
    # category file. Totals alone would look plausible — the ids do not.
    catalog, files, index_ids, meta, report = _fixture(per_category=10)
    dropped = files["gpu"][:2]
    files["gpu"] = files["gpu"][2:]
    meta["categories"] = [{"id": name, "count": len(ids)}
                          for name, ids in files.items()]
    report["products"] = len(index_ids)
    report["categories"]["gpu"] = {"products": 8}
    detail = trips(catalog, files, index_ids, meta, report)
    check_case("missing category rows trip",
               "gpu: 2 catalog product(s)" in detail
               and all(product_id in detail for product_id in dropped), detail)

    # A category file copied from an older run: stale rows + lost rows.
    catalog, files, index_ids, meta, report = _fixture()
    files["gpu"] = files["gpu"][:-1] + ["gpu:stale"]
    meta["categories"] = [{"id": name, "count": len(ids)}
                          for name, ids in files.items()]
    detail = trips(catalog, files, index_ids, meta, report)
    check_case("stale rows trip", "not in data/catalog.json" in detail, detail)

    # index.json from another run.
    catalog, files, index_ids, meta, report = _fixture()
    detail = trips(catalog, files, index_ids[:-1], meta, report)
    check_case("index mismatch trips", "index.json does not match" in detail, detail)

    # meta.json from another run (same counts, different generated_at).
    catalog, files, index_ids, meta, report = _fixture()
    meta["generated_at"] = "2026-10-31T00:00:00+00:00"
    detail = trips(catalog, files, index_ids, meta, report)
    check_case("mixed runs trip", "written by another run" in detail, detail)

    # meta.json count that disagrees with the file it names.
    catalog, files, index_ids, meta, report = _fixture()
    meta["categories"][0]["count"] += 1
    detail = trips(catalog, files, index_ids, meta, report)
    check_case("meta count trips", "the file has" in detail, detail)

    # The report describes a different catalog.
    catalog, files, index_ids, meta, report = _fixture()
    report["products"] = int(report["products"]) - 1
    detail = trips(catalog, files, index_ids, meta, report)
    check_case("stale report total trips", "different runs" in detail, detail)

    catalog, files, index_ids, meta, report = _fixture()
    report["categories"]["gpu"]["products"] += 1
    detail = trips(catalog, files, index_ids, meta, report)
    check_case("stale report category trips",
               "spec_report.json counts" in detail, detail)

    # Missing files are failures, never silent passes.
    catalog, files, index_ids, meta, report = _fixture()
    detail = trips(catalog, files, index_ids, None, report)
    check_case("missing meta trips", "meta.json is missing" in detail, detail)
    detail = trips(catalog, files, index_ids, meta, None)
    check_case("missing report trips", "spec_report.json is missing" in detail, detail)

    # Owner Q1: a bundle-only price never outranks a plain one, and its flag
    # survives into the site files.
    plain = {"vendor_id": "ksp", "url": "k", "price_ils": 500, "listing_key": "ksp:1"}
    bundle = {"vendor_id": "tms", "url": "t", "price_ils": 400, "bundle_only": True,
              "listing_key": "tms:1"}
    conditional = {"products": [{"product_id": "gpu:0", "offers": [plain, bundle],
                                 "best_offer": plain}]}
    good_row = {"gpu:0": {"min_price": 500, "offers": [
        {"vendor": "ksp", "url": "k", "price": 500},
        {"vendor": "tms", "url": "t", "price": 400, "bundle_only": True}]}}
    detail = " | ".join(check_conditional_offers(conditional, good_row))
    check_case("plain-first set passes", not detail, detail)
    conditional["products"][0]["best_offer"] = bundle
    detail = " | ".join(check_conditional_offers(conditional, good_row))
    check_case("bundle best offer trips", "bundle-only best offer" in detail, detail)
    conditional["products"][0]["best_offer"] = plain
    bad_row = {"gpu:0": {"min_price": 400, "offers": [
        {"vendor": "ksp", "url": "k", "price": 500},
        {"vendor": "tms", "url": "t", "price": 400}]}}
    detail = " | ".join(check_conditional_offers(conditional, bad_row))
    check_case("dropped flag trips", "without their flag" in detail, detail)
    bad_row["gpu:0"]["offers"][1]["bundle_only"] = True
    detail = " | ".join(check_conditional_offers(conditional, bad_row))
    check_case("bundle min_price trips", "take min_price" in detail, detail)
    only_bundle = {"products": [{"product_id": "gpu:1", "offers": [bundle],
                                 "best_offer": bundle}]}
    only_row = {"gpu:1": {"min_price": 400, "offers": [
        {"vendor": "tms", "url": "t", "price": 400, "bundle_only": True}]}}
    detail = " | ".join(check_conditional_offers(only_bundle, only_row))
    check_case("bundle-only product passes", not detail, detail)

    # Audit 2026-11-10 P: a vendor twin ships as a chip, never as an offer.
    yahav = {"vendor_id": "yahav", "url": "y1", "price_ils": 620, "listing_key": "yahav:1"}
    twin = {"vendor_id": "yahav", "url": "y2", "price_ils": 590, "bundle_only": True,
            "listing_key": "yahav:2", "alias_of": "yahav:1", "alias_kind": "bundle"}
    twins = {"products": [{"product_id": "aio:0", "offers": [yahav, twin], "best_offer": yahav}]}
    good = {"aio:0": {"offers": [{"vendor": "yahav", "url": "y1", "price": 620,
                                  "new_pc_deal": True, "promo_price": 590}]}}
    detail = " | ".join(check_vendor_twins(twins, good))
    check_case("folded twin passes", not detail, detail)
    both = {"aio:0": {"offers": [{"vendor": "yahav", "url": "y1", "price": 620},
                                 {"vendor": "yahav", "url": "y2", "price": 590, "bundle_only": True}]}}
    detail = " | ".join(check_vendor_twins(twins, both))
    check_case("shipped twin trips", "ship as their own" in detail and "lost their deal" in detail
               and "one vendor twice" in detail, detail)
    twins["products"][0]["best_offer"] = twin
    detail = " | ".join(check_vendor_twins(twins, good))
    check_case("twin best offer trips", "best offer from a vendor twin" in detail, detail)

    total_checks = 18
    if problems:
        print(f"[publish-set] self-test FAILED — {len(problems)} of ~{total_checks} checks:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"[publish-set] self-test pass — {total_checks} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--self-test" in args:
        return self_test()
    if not CATALOG.is_file():
        print(f"[publish-set] catalog not found: {CATALOG} (run normalize first)")
        return 1
    if not SITE_DIR.is_dir():
        print(f"[publish-set] site data not found: {SITE_DIR} (run normalize first)")
        return 1

    catalog, files, index_ids, meta, report = load()
    problems = check(catalog, files, index_ids, meta, report)
    site_rows = load_site_rows()
    problems += check_conditional_offers(catalog, site_rows)
    problems += check_vendor_twins(catalog, site_rows)
    if problems:
        print(f"[publish-set] FAIL — {len(problems)} incoherence(s) in the published data set:")
        for problem in problems:
            print(f"  - {problem}")
        print("  the catalog, data/site/*.json and data/site/spec_report.json must "
              "come from ONE normalize run — rerun normalize, do not hand-edit")
        return 1
    products = len(catalog.get("products") or [])
    print(f"[publish-set] pass — catalog, {len(files)} category files, index, meta "
          f"and spec_report all describe the same {products} products")
    return 0


if __name__ == "__main__":
    sys.exit(main())
