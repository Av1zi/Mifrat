"""Offline regression: real specs must not masquerade as challenge pages."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scraper import make_detail_pending as detail


def main():
    good = [
        {"model": "AMD Radeon RX 9060 XT Challenger 16GB OC"},
        {"dimensions": "W=483 H=133 D=429mm"},
        {"dimensions": "403 mm x 120 mm x 27 mm"},
        {"barcode": "4711377429627"},
        {"length_mm": "403"},
    ]
    bad = [{}, {"error": "403"}, {"error": "HTTP 429 Too Many Requests"},
           {"error": "Cloudflare challenge"}, {"error": "Verify you are human"}]
    assert all(detail._usable_specs(specs) for specs in good), "legitimate specs rejected as a block"
    assert all(not detail._usable_specs(specs) for specs in bad), "challenge accepted as specs"
    with tempfile.TemporaryDirectory() as tmp:
        old = Path.cwd()
        os.chdir(tmp)
        try:
            for vendor in ("ivory", "onepc", "tms", "yahav", "ksp"):
                listing = Path(f"data/raw/2026-11-21/{vendor}.jsonl")
                rows = [{"vendor_sku": str(i), "url": f"https://example.test/{i}"}
                        for i in range(1, len(good) + 1)]
                listing.parent.mkdir(parents=True, exist_ok=True)
                listing.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
                output = detail._detail(vendor)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("\n".join(json.dumps({**row, "specs": specs})
                                          for row, specs in zip(rows, good)), encoding="utf-8")
                with patch.object(detail, "_core_gap_priorities", return_value={}), \
                     patch.object(detail, "_ksp_alone_priorities", return_value={}):
                    detail.make([vendor], 200)
                    detail.mark([vendor])
                    assert json.loads(detail._pending(vendor).read_text()) == [], f"{vendor}: accepted specs remain pending"
                    detail.make([vendor], 200)
                    assert json.loads(detail._pending(vendor).read_text()) == [], f"{vendor}: same specs queued again"
        finally:
            os.chdir(old)
    print("[detail-pending] pass - spec acceptance, make/mark and no repeated completed requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
