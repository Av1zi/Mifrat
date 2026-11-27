"""Population guard: source losses are not matching collapses."""
from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper.specs.golden.check_golden import population_problems
from scraper.ops.registry import VENDORS


def catalog(count=20, lost=0, collapsed=0, vendor="onepc", category="storage"):
    total = VENDORS[vendor].min_rows + 100
    listings = [{"listing_key": f"{vendor}:{i}", "vendor_id": vendor} for i in range(total) if i not in range(count-lost, count)]
    products = [{"product_id": f"{vendor}:p{i}", "category": category,
                 "offers": [{"listing_key": f"{vendor}:{i}", "vendor_id": vendor}]}
                for i in range(count-lost-collapsed)]
    # The remaining listings/products are in a different category.
    products += [{"product_id": f"{vendor}:p{i}", "category": "cpu",
                  "offers": [{"listing_key": f"{vendor}:{i}", "vendor_id": vendor}]}
                 for i in range(count, total)]
    return {"products": products, "listings": listings,
            "source_listing_keys": [r["listing_key"] for r in listings]}


def check_pause_expiry() -> list[str]:
    fresh = catalog()
    paused = catalog(vendor="ksp")
    for row in paused["listings"]:
        row["last_seen"] = "2026-11-16"
    baseline = {key: rows + paused[key] for key, rows in fresh.items()}
    fresh.update(generated_at="2026-11-30T21:00:00+00:00", skipped_vendors=["ksp"])
    # These IDs now have other sellers; their expired KSP offers cannot excuse
    # the loss of other products, even if the total count held steady.
    replacements = [{**current, "product_id": old["product_id"]}
                    for current, old in zip(fresh["products"][-300:], paused["products"][-300:])]
    cases = [
        ("paused snapshot expired at the start of the next scrape night", fresh, False),
        ("snapshot still in the lookback", {**fresh, "generated_at": "2026-11-30T20:59:59+00:00"}, True),
        ("vendor not skipped by the loader", {**fresh, "skipped_vendors": []}, True),
        ("paused vendor still in raw data", {
            **fresh, "source_listing_keys": [*fresh["source_listing_keys"], "ksp:0"],
        }, True),
        ("paused vendor still in normalized listings", {
            **fresh, "listings": [*fresh["listings"], paused["listings"][0]],
        }, True),
        ("other source collapsed at the same time", {**fresh, "products": fresh["products"][:-300]}, True),
        ("products with surviving ids cannot cover unrelated losses", {
            **fresh, "products": fresh["products"][:-300] + replacements,
        }, True),
        ("category emptied at the same time", {**fresh, "products": fresh["products"][20:]}, True),
    ]
    failures = []
    with patch.dict(VENDORS, {"ksp": replace(VENDORS["ksp"], paused="Reviewed pause")}):
        for name, current, blocked in cases:
            if bool(population_problems(current, baseline)) != blocked:
                failures.append(f"{name}: expected blocked={blocked}")
    with patch.dict(VENDORS, {"ksp": replace(VENDORS["ksp"], paused=None)}):
        if not population_problems(fresh, baseline):
            failures.append("unreviewed vendor outage incorrectly excused")
    return failures


def main():
    failures = check_pause_expiry()
    cases = [
        ("source loss with healthy vendor", catalog(lost=8), catalog(), False),
        ("surviving keys collapsed", catalog(collapsed=8), catalog(), True),
        ("mixed source loss and collapse", catalog(lost=4, collapsed=8), catalog(), True),
        ("category emptied", catalog(lost=20), catalog(), True),
        ("small source loss", catalog(lost=1), catalog(), False),
        ("different vendor and category", catalog(lost=8, vendor="yahav", category="gpu"), catalog(vendor="yahav", category="gpu"), False),
    ]
    for name, fresh, baseline, blocked in cases:
        got = bool(population_problems(fresh, baseline))
        if got != blocked: failures.append(f"{name}: blocked={got}, expected {blocked}")
    # Missing/insufficient source evidence preserves the old strict guard.
    thin = catalog(lost=8)
    thin["listings"] = thin["listings"][:30]
    thin["source_listing_keys"] = thin["source_listing_keys"][:30]
    if not population_problems(thin, catalog()): failures.append("thin vendor incorrectly excused")
    unavailable = catalog(lost=8)
    unavailable.pop("source_listing_keys")
    if not population_problems(unavailable, catalog()): failures.append("missing evidence incorrectly excused")
    parser_loss = catalog(lost=8)
    parser_loss["source_listing_keys"] = catalog()["source_listing_keys"]
    if not population_problems(parser_loss, catalog()): failures.append("normalizer-dropped keys incorrectly excused")
    unknown = catalog(lost=8)
    unknown["source_listing_keys"] = [k.replace("onepc:", "unknown:") for k in unknown["source_listing_keys"]]
    if not population_problems(unknown, catalog()): failures.append("unknown source incorrectly excused")
    # Every seller of a product must have lost its row: a surviving second
    # seller is evidence of a normalization/matching loss, never source churn.
    multiple_before = catalog()
    multiple_after = catalog(lost=8)
    for doc in (multiple_before, multiple_after):
        for i in range(800):
            doc["source_listing_keys"].append(f"ivory:{i}")
            doc["listings"].append({"listing_key": f"ivory:{i}", "vendor_id": "ivory"})
    for i in range(12, 20):
        multiple_before["products"][i]["offers"].append({"listing_key": f"ivory:{i}", "vendor_id": "ivory"})
    if not population_problems(multiple_after, multiple_before): failures.append("surviving second seller incorrectly excused")
    duplicate = catalog(lost=8)
    duplicate["products"] += [{**duplicate["products"][0], "product_id": f"d{i}"} for i in range(8)]
    if population_problems(duplicate, catalog()): failures.append("new product set falsely called a collapse")
    empty = {"products": [], "listings": [], "source_listing_keys": []}
    if not population_problems(empty, catalog()): failures.append("empty catalog incorrectly excused")
    if failures:
        for failure in failures: print("[population] FAIL", failure)
        return 1
    print("[population] pass - source/merge/parser losses, paused snapshot expiry, empty catalog/category, thin vendor, missing evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
