"""Offline regression checks: quarantined candidates are visible, not active rules."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    failures = []
    # Diagnostic visibility alone is not enough: real inference must never
    # fill a per-SKU memory ceiling from socket/generation, including unknown
    # SKUs that happen to match an old platform table entry.
    from scraper.specs import derive

    platforms = [
        ("Intel", "Intel Core Ultra 5 225", "LGA1851"),
        ("Intel", "Intel Core i7 14700K", "LGA1700"),
        ("Intel", "Intel Core i7 10700", "LGA1200"),
        ("Intel", "Intel Core i7 6700", "LGA1151"),
        ("Intel", "Intel Core i7 9700", "LGA1151"),
        ("Intel", "Intel Core i7 9800X", "LGA2066"),
        ("AMD", "AMD Ryzen 7 5800X", "AM4"),
        ("AMD", "AMD Ryzen 7 9700X", "AM5"),
    ]
    with patch.object(derive, "cpu_memory_platform_candidate") as candidate:
        for brand, model, socket in platforms:
            specs = {"brand": brand, "model": model, "socket": socket}
            sources = {}
            derive.infer_specs("cpu", specs, sources)
            if specs.get("max_memory_gb") is not None or "max_memory_gb" in sources:
                failures.append(f"platform guess re-enabled for {model}")
        if candidate.called:
            failures.append("real inference called the quarantined platform candidate")
    specs = {"brand": "Intel", "model": "Intel Core Ultra 5 225",
             "socket": "LGA1851", "max_memory_gb": 256}
    sources = {"max_memory_gb": "vendor"}
    derive.infer_specs("cpu", specs, sources)
    if specs["max_memory_gb"] != 256 or sources["max_memory_gb"] != "vendor":
        failures.append("quarantine changed a sourced CPU memory limit")
    cases = [
        ("quarantined CPU candidate", "cpu", {
            "brand": "Intel", "model": "Intel Core Ultra 5 225",
            "socket": "LGA1851", "max_memory_gb": 256,
        }, {"max_memory_gb": "vendor"}, 0, "[quarantined]"),
        ("active RAM arithmetic", "memory", {
            "module_count": 2, "module_size_gb": 16, "total_gb": 64,
        }, {"total_gb": "vendor"}, 1, "FAIL derived:memory.module_arithmetic"),
    ]
    with tempfile.TemporaryDirectory(prefix="mifrat-backtest-") as tmp:
        path = Path(tmp) / "catalog.json"
        for name, category, specs, sources, expected, signal in cases:
            path.write_text(json.dumps({"products": [
                {"product_id": f"fixture:{category}:{i}", "category": category,
                 "canonical_name": name, "specs": specs, "spec_sources": sources}
                for i in range(8)
            ], "listings": []}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "scripts/backtest_rules.py"),
                 "--catalog", str(path), "--check", "--no-title"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            if result.returncode != expected or signal not in result.stdout:
                failures.append(f"{name}: exit {result.returncode}, expected {expected}\n"
                                + result.stdout + result.stderr)
            if expected == 0 and "INFO quarantined" not in result.stdout:
                failures.append(f"{name}: rejected candidate disappeared from diagnostics")
    # If the rejected rule is ever re-enabled, its output is an ACTIVE
    # prediction again. Labels alone must not grant a quarantine exemption.
    from scripts import backtest_rules as backtest

    def reenabled(category, specs, sources, **kwargs):
        specs["max_memory_gb"] = backtest.cpu_memory_platform_candidate(specs)
        sources["max_memory_gb"] = "derived:cpu.socket_memory_platform"

    tally = backtest.Tally()
    products = [{"product_id": f"cpu:{i}", "category": "cpu",
                 "specs": cases[0][2], "spec_sources": cases[0][3]} for i in range(8)]
    with patch.object(backtest, "infer_specs", side_effect=reenabled):
        backtest.backtest_derived(products, {}, tally)
    key = "derived:cpu.socket_memory_platform -> cpu.max_memory_gb"
    slot = tally.pairs.get(key)
    if not slot or slot["quarantined"] or not backtest.is_regression(slot, key, None):
        failures.append("re-enabled CPU candidate was not treated as an active regression")
    for failure in failures:
        print(f"[backtest-rules] FAIL {failure}")
    if failures:
        return 1
    print("[backtest-rules] offline CLI regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
