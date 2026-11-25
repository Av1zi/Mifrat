"""Sanitize a captured price stream from stdin, offline and without file writes.

Never fetches KSP or reads browser/session state. Supply only a response from
the one permitted native-browser observation; do not save a raw HAR/body.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.ksp_stream import (MAX_STREAM_BYTES, StreamBlocked, StreamError,
                               price_stream_shape)  # noqa: E402


def main() -> int:
    if sys.argv[1:] != ["--stdin"]:
        print("Usage: python scripts/ksp_price_shape.py --stdin (offline response input)")
        return 1
    body = sys.stdin.buffer.read(MAX_STREAM_BYTES + 1)
    try:
        result = price_stream_shape(body)
    except StreamBlocked:
        print('[ksp-price-shape] blocked; keep KSP paused; no further requests')
        return 3
    except StreamError:
        print('[ksp-price-shape] invalid stream; no raw response retained')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
