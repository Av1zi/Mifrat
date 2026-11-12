"""Gate: every shipped spec sheet obeys the physical invariants (audit 2026-11-10 F/G).

A value that breaks one of these is wrong whatever source printed it, so
the gate is hard (13 hits, 13 real, before the fix):

  1. a CPU runs at least one thread per core: `thread_count >= core_count`
     (5 reference rows, 5 vendor rows had 8 threads on 16 cores etc.);
  2. a GPU's `memory_type` is a real GPU memory standard
     (`witness.GPU_MEMORY_TYPES`): no GDDR4 (a "4GD4" card is DDR4), no DDR6;
  3. a board's socket is the socket of its chipset (`CHIPSET_INFO`), which
     `validate.cross_check` already enforces: this pins it;
  4. every `spec_sources` label is ranked by `cross_check` (`_TIER_ORDER` or
     `derived:<rule>`), so a new label never fights at rank 99 again;
  5. every board chipset is a `CHIPSET_INFO` key or on `CHIPSET_UNKNOWN`
     (audit 2026-11-10 M: "INTELHM770" and "CHIPSET" shipped as chipsets).

And one report check (audit 2026-11-10 M): every vendor value an enum
refused this run (`data/site/spec_report.json` `schema_misses`) is on
`schema.SCHEMA_UNKNOWN_VALUES`, and no board chipset was refused. Anything
else is a canon gap or a missing enum value that was silently dropped.

The fixes live in scraper/specs/validate.py (validate_fact, cross_check),
scraper/specs/witness.py, scraper/specs/canon.py and scraper/specs/schema.py;
this reads only data/catalog.json and data/site/spec_report.json.

    python scripts/check_spec_invariants.py --self-test
    python scripts/check_spec_invariants.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper.specs import schema  # noqa: E402
from scraper.specs.validate import _TIER_ORDER  # noqa: E402
from scraper.specs.witness import GPU_MEMORY_TYPES, socket_key  # noqa: E402

CATALOG = ROOT / "data" / "catalog.json"
SPEC_REPORT = ROOT / "data" / "site" / "spec_report.json"
_KNOWN_CHIPSETS = {key.upper() for key in schema.CHIPSET_INFO} | {
    key.upper() for key in schema.CHIPSET_UNKNOWN}


def _sample(items: list[str], limit: int = 5) -> str:
    head = ", ".join(items[:limit])
    return head + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def check(products: list[dict]) -> list[str]:
    """Pure: the invariant breaches in `products`, one line per invariant."""
    threads: list[str] = []
    gpu_memory: list[str] = []
    sockets: list[str] = []
    chipsets: list[str] = []
    labels: dict[str, list[str]] = {}
    for product in products:
        pid = str(product.get("product_id"))
        category = product.get("category")
        specs = product.get("specs") or {}
        cores, thread_count = specs.get("core_count"), specs.get("thread_count")
        if (category == "cpu" and isinstance(cores, int) and isinstance(thread_count, int)
                and thread_count < cores):
            threads.append(f"{pid} ({thread_count}T/{cores}C)")
        memory = specs.get("memory_type")
        if category == "gpu" and memory is not None and str(memory).upper() not in GPU_MEMORY_TYPES:
            gpu_memory.append(f"{pid} ({memory})")
        if category == "motherboard":
            info = schema.CHIPSET_INFO.get(str(specs.get("chipset") or "").upper())
            socket = specs.get("socket")
            if info and info[0] and socket and socket_key(socket) != socket_key(info[0]):
                sockets.append(f"{pid} ({specs.get('chipset')} on {socket})")
            chipset = specs.get("chipset")
            if chipset is not None and str(chipset).upper() not in _KNOWN_CHIPSETS:
                chipsets.append(f"{pid} ({chipset})")
        for field, label in (product.get("spec_sources") or {}).items():
            label = str(label)
            if not label.startswith("derived:") and label not in _TIER_ORDER:
                labels.setdefault(label, []).append(f"{pid}.{field}")

    problems: list[str] = []
    if threads:
        problems.append(f"{len(threads)} CPU(s) with fewer threads than cores: {_sample(threads)}")
    if gpu_memory:
        problems.append(f"{len(gpu_memory)} GPU(s) with a memory type that is not a GPU "
                        f"memory standard: {_sample(gpu_memory)}")
    if sockets:
        problems.append(f"{len(sockets)} board(s) whose socket is not their chipset's: "
                        f"{_sample(sockets)}")
    if chipsets:
        problems.append(f"{len(chipsets)} board(s) whose chipset is not in schema.CHIPSET_INFO "
                        f"or CHIPSET_UNKNOWN: {_sample(chipsets)}")
    for label, where in sorted(labels.items()):
        problems.append(f"spec source label {label!r} is not ranked in validate._TIER_ORDER "
                        f"({len(where)} value(s), e.g. {_sample(where, 3)})")
    return problems


def check_report(report: dict) -> list[str]:
    """Pure: schema misses in a spec report that no SCHEMA_UNKNOWN_VALUES entry explains."""
    if "schema_misses" not in report:
        return ["spec_report.json has no schema_misses: re-run scraper/normalize_and_match.py"]
    total = (report.get("counts") or {}).get("schema_misses")
    if isinstance(total, int) and total > len(report.get("schema_misses") or []):
        return [f"spec_report.json lists {len(report['schema_misses'])} of {total} schema misses "
                "(site_data.SCHEMA_MISS_CAP cut the list): the unlisted ones are unchecked - "
                "fix the top misses or raise the cap"]
    unexplained: list[str] = []
    for miss in report.get("schema_misses") or []:
        category, field, value = miss.get("category"), miss.get("field"), miss.get("value")
        if field == "chipset" and category == "motherboard":
            unexplained.append(f"motherboard.chipset={value!r} refused x{miss.get('count')} "
                               f"({_sample([str(p) for p in miss.get('products') or []], 3)})")
        elif not schema.schema_unknown(str(category), str(field), value):
            unexplained.append(f"{category}.{field}={value!r} x{miss.get('count')}")
    if not unexplained:
        return []
    return [f"{len(unexplained)} vendor value(s) refused by the schema and not on "
            f"schema.SCHEMA_UNKNOWN_VALUES (add a canon spelling or an enum value): "
            f"{_sample(unexplained, 8)}"]


def self_test() -> int:
    failures: list[str] = []

    def case(name: str, products: list[dict], expect: str | None) -> None:
        detail = " | ".join(check(products))
        ok = not detail if expect is None else expect in detail
        if not ok:
            failures.append(f"{name}: {detail or 'no problem reported'}")

    def p(category: str, specs: dict, sources: dict | None = None) -> dict:
        return {"product_id": f"{category}:x", "category": category, "specs": specs,
                "spec_sources": sources or {}}

    case("clean set passes", [
        p("cpu", {"core_count": 8, "thread_count": 16}, {"core_count": "vendor"}),
        p("gpu", {"memory_type": "GDDR6"}),
        p("motherboard", {"chipset": "B650E", "socket": "AM5"}, {"chipset": "witness"}),
        p("cpu", {"core_count": 6}, {"core_count": "derived:cpu.model_table"}),
    ], None)
    case("equal threads pass", [p("cpu", {"core_count": 14, "thread_count": 14})], None)
    case("threads below cores trip", [p("cpu", {"core_count": 16, "thread_count": 8})],
         "fewer threads than cores")
    case("GDDR4 trips", [p("gpu", {"memory_type": "GDDR4"})], "not a GPU memory standard")
    case("DDR6 trips", [p("gpu", {"memory_type": "DDR6"})], "not a GPU memory standard")
    case("DDR4 card passes", [p("gpu", {"memory_type": "DDR4"})], None)
    case("chipset/socket mismatch trips",
         [p("motherboard", {"chipset": "Z890", "socket": "AM5"})], "not their chipset's")
    # Xeon 6 workstation boards (ASRock Rack W890D8: vendor page "Intel W890",
    # socket "4710"); W880 is the Arrow Lake workstation PCH on LGA1851.
    case("W890 on LGA4710 passes",
         [p("motherboard", {"chipset": "W890", "socket": "LGA4710"})], None)
    case("W880 on LGA1851 passes",
         [p("motherboard", {"chipset": "W880", "socket": "LGA1851"})], None)
    case("unranked label trips", [p("gpu", {"memory_type": "GDDR6"}, {"memory_type": "guess"})],
         "not ranked")
    case("SoC and mobile PCH boards pass",
         [p("motherboard", {"chipset": "SoC"}), p("motherboard", {"chipset": "HM770"})], None)
    case("glued chipset trips", [p("motherboard", {"chipset": "INTELHM770"})],
         "not in schema.CHIPSET_INFO")
    case("label word as chipset trips", [p("motherboard", {"chipset": "CHIPSET"})],
         "not in schema.CHIPSET_INFO")

    def report_case(name: str, report: dict, expect: str | None) -> None:
        detail = " | ".join(check_report(report))
        ok = not detail if expect is None else expect in detail
        if not ok:
            failures.append(f"{name}: {detail or 'no problem reported'}")

    def miss(category: str, field: str, value: str, **extra) -> dict:
        return {"category": category, "field": field, "value": value, "count": 1, **extra}

    report_case("explained misses pass", {"schema_misses": [
        miss("psu", "efficiency", "Cybenetics Platinum"),
        miss("memory", "memory_type", "16GB"),
        miss("storage", "type", "M.2 2280"),
    ]}, None)
    report_case("empty misses pass", {"schema_misses": []}, None)
    report_case("unexplained enum miss trips",
                {"schema_misses": [miss("psu", "efficiency", "80 PLUS Bronze+")]},
                "not on schema.SCHEMA_UNKNOWN_VALUES")
    report_case("refused chipset trips", {"schema_misses": [
        miss("motherboard", "chipset", "Intel B85", products=["motherboard:x"])]},
                "motherboard.chipset='Intel B85'")
    report_case("report without schema_misses trips", {"products": 1},
                "has no schema_misses")
    report_case("a cut schema_misses list trips",
                {"schema_misses": [miss("psu", "efficiency", "Cybenetics Platinum")],
                 "counts": {"schema_misses": 301}}, "cut the list")
    report_case("an uncut list passes",
                {"schema_misses": [miss("psu", "efficiency", "Cybenetics Platinum")],
                 "counts": {"schema_misses": 1}}, None)

    total = 18
    if failures:
        print(f"[spec-invariants] self-test FAIL - {len(failures)} of {total}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[spec-invariants] self-test pass - {total} checks")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    products = json.loads(CATALOG.read_text(encoding="utf-8")).get("products") or []
    problems = check(products)
    if SPEC_REPORT.exists():
        problems += check_report(json.loads(SPEC_REPORT.read_text(encoding="utf-8")))
    else:
        problems.append(f"{SPEC_REPORT.relative_to(ROOT)} is missing")
    if problems:
        print(f"[spec-invariants] FAIL - {len(problems)} invariant breach(es):")
        for problem in problems:
            print(f"  - {problem}")
        print("  fix the source rule in scraper/specs/validate.py, witness.py or canon.py, "
              "the enum in schema.py, or the override in data/specs/overrides.json — "
              "never this gate")
        return 1
    print(f"[spec-invariants] pass - {len(products)} products obey the spec invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
