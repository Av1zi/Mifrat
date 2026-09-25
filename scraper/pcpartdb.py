"""
pcpartdb.py — download, parse, dedupe, index, and query the MIT-licensed
docyx/pc-part-dataset.

Usage:
    python -m scraper.pcpartdb download
    python -m scraper.pcpartdb build
    python -m scraper.pcpartdb lookup "ryzen 7 7800x3d" cpu
    python -m scraper.pcpartdb lookup "BIOSTAR Crypto Mining Card" gpu --threshold 75
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "pcpartdb" / "raw"
INDEX_PATH = DATA_DIR / "pcpartdb" / "index.json"

BASE_URL = "https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/json"

# PCPartPicker dataset slug -> our canonical category id.
PCPP_TO_OURS = {
    "cpu": "cpu",
    "cpu-cooler": "cooler",
    "motherboard": "motherboard",
    "memory": "memory",
    "internal-hard-drive": "storage",
    "video-card": "gpu",
    "case": "case",
    "power-supply": "psu",
    "case-fan": "case_fan",
}

# Reference spec mapping: dataset key -> (schema field, transform).
#
# Two facts about this dataset shape the whole mapping (verified against the
# raw files, Sep 2026):
#   1. It is SPARSE — 5-8 fields per category, nothing more. There are no part
#      numbers/MPNs at all, which is why identity matching in
#      specs/resolvers/reference.py is name-based with a hard anchor check
#      instead of MPN-exact.
#   2. Values arrive as bare numbers, [gen, mhz] / [count, size] pairs, bools
#      or marketing strings ("ATX Mid Tower"), so every entry needs a small
#      transform into the schema's unit-bearing field names.
#
# The mapping covers EVERY field the dataset actually carries, so Tier 0 is
# as wide as the data allows and nothing is silently dropped.

INDEX_SCHEMA_VERSION = 2

SPEC_MAP: dict[str, dict[str, object]] = {
    "cpu": {
        "core_count": "core_count",
        "core_clock": "base_clock_ghz",
        "boost_clock": "boost_clock_ghz",
        "microarchitecture": "microarchitecture",
        "tdp": "tdp_w",
        "graphics": "integrated_graphics",
    },
    "motherboard": {
        "socket": "socket",
        "form_factor": "form_factor",
        "max_memory": "memory_max_gb",
        "memory_slots": "memory_slots",
        "color": "color",
    },
    "memory": {
        "speed": "memory_speed_pair",
        "modules": "memory_modules_pair",
        "cas_latency": "cas_latency",
        "first_word_latency": "first_word_latency_ns",
        "color": "color",
    },
    "internal-hard-drive": {
        "capacity": "capacity_gb",
        "type": "type",
        "cache": "cache_mb",
        "form_factor": "form_factor",
        "interface": "interface",
    },
    "video-card": {
        "chipset": "chipset",
        "memory": "memory_gb",
        "core_clock": "core_clock_mhz",
        "boost_clock": "boost_clock_mhz",
        "length": "length_mm",
        "color": "color",
    },
    "case": {
        "type": "type",
        "color": "color",
        "psu": "psu_included",
        "side_panel": "side_panel",
        "external_volume": "volume_l",
        "internal_35_bays": "drive_bays_35",
    },
    "power-supply": {
        "type": "type",
        "efficiency": "efficiency",
        "wattage": "wattage_w",
        "modular": "modular",
        "color": "color",
    },
    "case-fan": {
        "size": "size_mm",
        "color": "color",
        "rpm": "fan_rpm_pair",
        "airflow": "range_max:airflow_cfm",
        "noise_level": "range_max:noise_db",
        "pwm": "pwm",
    },
    "cpu-cooler": {
        "rpm": "cooler_rpm_pair",
        "noise_level": "range_max:noise_db",
        "color": "color",
        "size": "cooler_size",
    },
}

# These should never become build parts.
JUNK_NAME_RE = re.compile(
    r"\b("
    r"risers?|"
    r"pci-?e?\s?(riser|extender|extension|splitter)|"
    r"ver00\d{1,2}[a-z]?|"
    r"mining\s?(card|adapter|frame|rig|bundle)|"
    r"crypto|"
    r"bitcoin|"
    r"btc|"
    r"ethereum|"
    r"eth"
    r")\b",
    re.I,
)

_MODEL_TOKEN_RE = re.compile(r"^(?=.*\d)[a-z0-9+-]{3,}$")

_INDEX_CACHE: dict | None = None


def _norm_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _fetch(url: str, dest: Path) -> None:
    print(f"[pcpartdb] fetching {url}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "pc-parts-il/0.1 (dataset mirror)",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = resp.read()
    dest.write_bytes(payload)
    print(f"[pcpartdb]   -> {dest} ({len(payload):,} bytes)")


def cmd_download() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for slug in PCPP_TO_OURS:
        url = f"{BASE_URL}/{slug}.json"
        dest = RAW_DIR / f"{slug}.json"
        _fetch(url, dest)

    print("[pcpartdb] download complete")
    print("[pcpartdb] next: python -m scraper.pcpartdb build")


def cmd_refresh() -> None:
    """
    download + build in one call.

    This is what CI and local dev should actually run — the dataset is
    treated as regenerable, not committed (see .gitignore / DECISIONS.md,
    Aug 2026): re-fetching ~7MB from GitHub's raw CDN on every normalize
    run is cheap and always current, versus committing a 16MB static
    mirror that grows the repo every time someone rebuilds it.
    """
    cmd_download()
    cmd_build()



def _range_max(value):
    """Dataset ranges arrive as [min, max] (case fans) or a bare number."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return max(float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None
    return value


def _doc_to_specs(slug: str, row: dict) -> dict:
    """Map one dataset row onto schema-named, schema-typed spec values.

    Transform names are the small DSL in SPEC_MAP; anything unrecognized is
    skipped rather than guessed. Values are still schema-checked later by
    specs/values.coerce(), so a malformed dataset value can never reach a
    product.
    """
    mapping = SPEC_MAP.get(slug) or {}
    out: dict = {}

    for key, transform in mapping.items():
        raw = row.get(key)
        if raw in (None, "", [], {}):
            continue

        if transform == "memory_speed_pair":
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                generation, mhz = raw[0], raw[1]
                out["memory_type"] = f"DDR{int(generation)}"
                out["speed_mhz"] = int(mhz)
                out["speed"] = f"DDR{int(generation)}-{int(mhz)}"
        elif transform == "memory_modules_pair":
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                count, size = int(raw[0]), int(raw[1])
                out["module_count"] = count
                out["module_size_gb"] = size
                out["total_gb"] = count * size
        elif transform == "fan_rpm_pair":
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                out["rpm_min"] = int(raw[0])
                out["rpm_max"] = int(raw[1])
            else:
                out["rpm_max"] = raw
        elif transform == "cooler_rpm_pair":
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                out["fan_rpm_min"] = int(raw[0])
                out["fan_rpm_max"] = int(raw[1])
            else:
                out["fan_rpm_max"] = raw
        elif transform == "cooler_size":
            # The dataset's cooler "size" is a radiator size for AIOs and
            # null for air coolers.
            try:
                size = int(raw)
            except (TypeError, ValueError):
                continue
            if size >= 120:
                out["radiator_size_mm"] = size
                out["water_cooled"] = True
            else:
                out["fan_size_mm"] = size
        elif isinstance(transform, str) and transform.startswith("range_max:"):
            field = transform.split(":", 1)[1]
            value = _range_max(raw)
            if value not in (None, ""):
                out[field] = value
        else:
            out[str(transform)] = True if raw is True else raw

    if slug == "power-supply" and "modular" in out:
        # False means a non-modular unit; True means fully modular.
        out["modular"] = "full" if out["modular"] is True else "no"
    if slug == "internal-hard-drive":
        interface = str(out.get("interface") or "")
        if "NVME" in interface.upper() or "PCIE" in interface.upper():
            out["nvme"] = True
    return out


def _clean_specs(slug: str, row: dict) -> dict:
    return _doc_to_specs(slug, row)


def cmd_build() -> None:
    if not RAW_DIR.exists():
        sys.exit("[pcpartdb] raw dir missing — run download first")

    parts: list[dict] = []
    seen: set[tuple] = set()
    counts: dict[str, dict] = {}

    for slug, ours in PCPP_TO_OURS.items():
        path = RAW_DIR / f"{slug}.json"
        if not path.exists():
            print(f"[pcpartdb] missing {path}, skipping")
            continue

        rows = json.loads(path.read_text(encoding="utf-8"))

        kept = 0
        duplicates = 0
        junk = 0

        for row in rows:
            name = str(row.get("name") or "").strip()
            if not name:
                continue

            if JUNK_NAME_RE.search(name):
                junk += 1
                continue

            specs = _clean_specs(slug, row)
            if not specs:
                # Nothing usable (e.g. a row with only a price): the index
                # exists to serve specs, so skip it instead of carrying it.
                continue

            dedupe_key = (
                ours,
                _norm_name(name),
                json.dumps(specs, sort_keys=True, ensure_ascii=False),
            )

            if dedupe_key in seen:
                duplicates += 1
                continue

            seen.add(dedupe_key)

            parts.append(
                {
                    "name": name,
                    "search_name": _norm_name(name),
                    "cat": ours,
                    "pcpp": slug,
                    "specs": specs,
                }
            )

            kept += 1

        counts[slug] = {
            "kept": kept,
            "duplicates": duplicates,
            "junk": junk,
        }

        print(
            f"[pcpartdb] {slug}: kept={kept:,}, "
            f"duplicates={duplicates:,}, junk={junk:,}"
        )

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    index = {
        "source": "docyx/pc-part-dataset",
        "license": "MIT",
        "schema": INDEX_SCHEMA_VERSION,
        "counts": counts,
        "parts": parts,
    }

    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(
        f"[pcpartdb] wrote {INDEX_PATH} "
        f"({INDEX_PATH.stat().st_size:,} bytes, {len(parts):,} parts)"
    )


def load_index() -> dict:
    global _INDEX_CACHE

    # Narrow through a local rather than the global directly — a type
    # checker can't reliably carry the "is None" narrowing on a `global`
    # all the way to the `return` below, so it still sees `dict | None`
    # there even after the assignment. A local has no such issue.
    cache = _INDEX_CACHE
    if cache is None:
        if not INDEX_PATH.exists():
            raise FileNotFoundError(
                f"{INDEX_PATH} missing — run download and build first"
            )

        cache = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        _INDEX_CACHE = cache

    return cache


def _tokens(value: str) -> set[str]:
    return set(value.split())


def _score(query_norm: str, part: dict) -> float:
    name_norm = part.get("search_name") or _norm_name(part.get("name"))

    if not query_norm or not name_norm:
        return 0.0

    if query_norm == name_norm:
        return 100.0

    query_tokens = _tokens(query_norm)
    name_tokens = _tokens(name_norm)

    # Query tokens fully contained in the target name.
    # Example: "ryzen 7 7800x3d" inside "amd ryzen 7 7800x3d".
    if len(query_tokens) >= 2 and query_tokens <= name_tokens:
        return 98.0

    # Strong model-token match.
    # Example: "7800x3d", "rtx4070", "b550".
    model_tokens = {
        token
        for token in query_tokens
        if _MODEL_TOKEN_RE.match(token)
    }

    if model_tokens and model_tokens <= name_tokens:
        return 95.0

    if fuzz is None:
        return 0.0

    score = max(
        fuzz.token_set_ratio(query_norm, name_norm),
        fuzz.token_sort_ratio(query_norm, name_norm),
    )

    # Partial ratio can help with longer cleaned titles, but can also
    # overmatch short junk, so only use it for longer queries.
    if len(query_norm) >= 12:
        score = max(score, fuzz.partial_ratio(query_norm, name_norm))

    return float(score)


def find_matches(
    query: str,
    category: str | None = None,
    threshold: float = 75.0,
    limit: int = 8,
) -> list[tuple[float, dict]]:
    if fuzz is None:
        return []

    query_norm = _norm_name(query)
    if not query_norm:
        return []

    index = load_index()
    pool = index["parts"]

    if category:
        pool = [part for part in pool if part["cat"] == category]

    scored: list[tuple[float, dict]] = []
    seen: set[tuple] = set()

    for part in pool:
        score = _score(query_norm, part)
        if score < threshold:
            continue

        dedupe_key = (
            part["cat"],
            part.get("search_name") or _norm_name(part.get("name")),
            json.dumps(part.get("specs", {}), sort_keys=True, ensure_ascii=False),
        )

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        scored.append((score, part))

    scored.sort(key=lambda item: (-item[0], item[1]["name"]))
    return scored[:limit]


def cmd_lookup(query: str, category: str | None, threshold: float, limit: int) -> None:
    results = find_matches(
        query,
        category=category,
        threshold=threshold,
        limit=limit,
    )

    if not results:
        print(f"No matches at threshold {threshold:.1f}")
        return

    for score, part in results:
        specs = ", ".join(
            f"{key}={value}"
            for key, value in list(part.get("specs", {}).items())[:6]
        )

        print(f"{score:5.1f}  [{part['cat']}]  {part['name']}  ({specs})")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.pcpartdb",
        description="Download, index, and query the pc-part-dataset.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("download", help="Download dataset JSON files")
    subparsers.add_parser("build", help="Build deduped local index")
    subparsers.add_parser(
        "refresh", help="download + build in one step (what CI/normalize should call)"
    )

    lookup_parser = subparsers.add_parser("lookup", help="Query the local index")
    lookup_parser.add_argument("query")
    lookup_parser.add_argument("category", nargs="?", default=None)
    lookup_parser.add_argument("--threshold", type=float, default=75.0)
    lookup_parser.add_argument("--limit", type=int, default=8)

    args = parser.parse_args()

    if args.command == "download":
        cmd_download()
    elif args.command == "build":
        cmd_build()
    elif args.command == "refresh":
        cmd_refresh()
    elif args.command == "lookup":
        cmd_lookup(
            args.query,
            args.category,
            args.threshold,
            args.limit,
        )


if __name__ == "__main__":
    main()