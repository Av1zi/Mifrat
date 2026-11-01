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
     stale-report guard read it).

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

    total_checks = 10
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
