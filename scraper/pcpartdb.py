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

# Keep only the specs we actually care about.
SPEC_KEYS = {
    "cpu": [
        "core_count",
        "core_clock",
        "boost_clock",
        "microarchitecture",
        "tdp",
        "graphics",
        "smt",
    ],
    "cpu-cooler": [
        "rpm",
        "noise_level",
        "color",
        "size",
    ],
    "motherboard": [
        "socket",
        "form_factor",
        "max_memory",
        "memory_slots",
        "color",
    ],
    "memory": [
        "speed",
        "modules",
        "price_per_gb",
        "color",
        "first_word_latency",
        "cas_latency",
    ],
    "internal-hard-drive": [
        "capacity",
        "price_per_gb",
        "type",
        "cache",
        "form_factor",
        "interface",
    ],
    "video-card": [
        "chipset",
        "memory",
        "core_clock",
        "boost_clock",
        "color",
        "length",
    ],
    "case": [
        "type",
        "color",
        "psu",
        "side_panel",
        "external_volume",
        "internal_35_bays",
    ],
    "power-supply": [
        "type",
        "efficiency",
        "wattage",
        "modular",
        "color",
    ],
    "case-fan": [
        "size",
        "color",
        "rpm",
        "airflow",
        "noise_level",
        "pwm",
    ],
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


def _clean_specs(slug: str, row: dict) -> dict:
    out = {}
    for key in SPEC_KEYS.get(slug, []):
        value = row.get(key)
        if value in (None, "", [], {}):
            continue
        out[key] = value
    return out


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

    if _INDEX_CACHE is None:
        if not INDEX_PATH.exists():
            raise FileNotFoundError(
                f"{INDEX_PATH} missing — run download and build first"
            )

        _INDEX_CACHE = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    return _INDEX_CACHE


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
    elif args.command == "lookup":
        cmd_lookup(
            args.query,
            args.category,
            args.threshold,
            args.limit,
        )


if __name__ == "__main__":
    main()