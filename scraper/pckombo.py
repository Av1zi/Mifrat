"""Exact MPN lookups for the PC Kombo scraped specifications dataset."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT / "data" / "pckombo" / "dataset.csv"
MPN_COLUMN = "Model Info | MPN"
URL_COLUMN = "URL"

_INDEX: dict[str, dict] | None = None


def normalize_mpn(value: str | None) -> str:
    """Normalize an MPN without fuzzy matching or changing its identity."""
    value = unquote(str(value or "")).strip()
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _row_specs(row: dict[str, str]) -> dict[str, str]:
    return {
        key: value.strip()
        for key, value in row.items()
        if key not in {URL_COLUMN, MPN_COLUMN} and value and value.strip()
    }


def load_index(path: Path | str = DATASET_PATH) -> dict[str, dict]:
    """Load the CSV once and index rows by their exact normalized MPN."""
    global _INDEX
    path = Path(path)
    if path == DATASET_PATH and _INDEX is not None:
        return _INDEX
    if not path.exists():
        raise FileNotFoundError(f"PC Kombo dataset not found: {path}")

    index: dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if MPN_COLUMN not in (reader.fieldnames or []):
            raise ValueError(f"PC Kombo dataset is missing {MPN_COLUMN!r}")
        for row in reader:
            mpn = normalize_mpn(row.get(MPN_COLUMN))
            if not mpn:
                continue
            candidate = {
                "mpn": row.get(MPN_COLUMN, "").strip(),
                "url": row.get(URL_COLUMN, "").strip(),
                "specs": _row_specs(row),
            }
            current = index.get(mpn)
            if current is None or len(candidate["specs"]) > len(current["specs"]):
                index[mpn] = candidate

    if path == DATASET_PATH:
        _INDEX = index
    return index


def find_by_mpn(mpn: str | None, path: Path | str = DATASET_PATH) -> dict | None:
    """Return the exact dataset row for an MPN, if present."""
    normalized = normalize_mpn(mpn)
    return load_index(path).get(normalized) if normalized else None
