"""A variant removed from a group cannot remain its identity bridge."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.matching import match_listings
from check_identity_merge import FAILURES, check_i1


def main() -> int:
    def row(vendor, sku, model, color, pn):
        return {"vendor_id": vendor, "vendor_sku": sku,
                "listing_key": f"{vendor}:{sku}", "category_normalized": "gpu",
                "brand": "ASUS", "mpn": pn, "title_raw": model,
                "attributes": {"model": model, "color": color,
                               "memory_gb": 16, "memory_type": "GDDR7"}}

    black = row("ivory", "black", "Dual GeForce RTX 5060 Ti OC", "Black", "90YV0MH0-M0NA00")
    white_long = row("onepc", "white", "Dual GeForce RTX 5060 Ti OC", "White", "90YV0MH6-M0NA00")
    white_short = row("tms", "white", "Dual RTX 5060 Ti OC", "White", "90YV0MH6-M0NA00")
    ksp = row("ksp", "390282", "Dual RTX 5060 Ti OC", "Black", None)
    with TemporaryDirectory() as tmp:
        manual = Path(tmp) / "manual.json"
        manual.write_text('{"products": [], "blocked_pairs": []}', encoding="utf-8")
        result = match_listings([black, white_long, white_short, ksp], manual_path=manual)
    FAILURES.clear()
    check_i1({"products": result["products"]})
    failures = list(FAILURES)
    assigned = result["assignments"]
    if assigned[black["listing_key"]] == assigned[ksp["listing_key"]]:
        failures.append("black and KSP joined only through white variant's removed bridge")
    if assigned[white_long["listing_key"]] != assigned[white_short["listing_key"]]:
        failures.append("white offers sharing a part number must remain together")
    if len(result["products"]) != 3:
        failures.append(f"expected three directly-connected products, got {len(result['products'])}")
    for failure in failures:
        print(f"[identity-connectivity] FAIL {failure}")
    if failures:
        return 1
    print("[identity-connectivity] pass - removed variant cannot connect surviving offers")
    # A directly shared code or maker PN is still valid evidence. The fix
    # must not turn conservative disconnection into unconditional splitting.
    same = row("ksp", "same", black["attributes"]["model"], "Black", None)
    pn_twin = copy.deepcopy(ksp)
    pn_twin["mpn"] = black["mpn"]
    for label, twin in (("same model", same), ("same part number", pn_twin)):
        with TemporaryDirectory() as tmp:
            manual = Path(tmp) / "manual.json"
            manual.write_text('{"products": [], "blocked_pairs": []}', encoding="utf-8")
            result = match_listings([copy.deepcopy(black), twin], manual_path=manual)
        if len(result["products"]) != 1:
            print(f"[identity-connectivity] FAIL {label} must still connect")
            return 1
    print("[identity-connectivity] pass - surviving model/part-number bridges still join")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
