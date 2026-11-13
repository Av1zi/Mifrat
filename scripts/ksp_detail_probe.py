"""KSP detail-endpoint feasibility probe (docs/ksp-detail-plan.md, Phase 0 step 1).

ONE request, run by the owner, on the Nano (home IP), never in CI:

    python scripts/ksp_detail_probe.py [uin]

It sends exactly the request the listing spider already sends (same TLS
profile, user agent and client hints from scraper/spiders/ksp.py) to
/m_action/api/item/<uin> once, then prints the status, the Cloudflare
`cf-mitigated` header, the body size, and whether the JSON carries a
manufacturer part number. No retry, no second profile, no header variants:
a 403 or a challenge is the answer and goes into the plan's Outcome section.

The probe refuses to run twice on one day (a marker file) so it cannot turn
into probing by accident.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.spiders.ksp import HEADERS, IMPERSONATE  # noqa: E402

ITEM_URL = "https://ksp.co.il/m_action/api/item/{uin}"
DEFAULT_UIN = "280943"  # the plan's example item (Intel Core i5 14600K Box)
# Outside the repo (nano/run_ksp.sh keeps its markers here), so nothing the
# probe writes can be committed by a later push.
MARKER_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "pc-parts-il"
PART_NUMBER_KEYS = re.compile(r"mpn|manufacturer|part|makat|barcode|ean|sku|model", re.I)


def _marker() -> Path:
    return MARKER_DIR / f".ksp-detail-probe-{datetime.now(timezone.utc):%Y-%m-%d}"


def _keys(value, prefix: str = "", out: list[str] | None = None) -> list[str]:
    out = [] if out is None else out
    if isinstance(value, dict):
        for key, inner in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.append(path)
            _keys(inner, path, out)
    elif isinstance(value, list) and value:
        _keys(value[0], f"{prefix}[0]", out)
    return out


def main(argv: list[str]) -> int:
    uin = argv[1] if len(argv) > 1 else DEFAULT_UIN
    if not uin.isdigit():
        print("[probe] the uin is KSP's numeric item id, e.g. 280943", file=sys.stderr)
        return 2
    marker = _marker()
    if marker.exists():
        print(f"[probe] already ran today ({marker.name}); one request per day, by design.")
        return 2

    from curl_cffi import requests  # the spider's own HTTP stack

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(uin, encoding="utf-8")
    url = ITEM_URL.format(uin=uin)
    print(f"[probe] GET {url} (impersonate={IMPERSONATE})")
    try:
        response = requests.get(url, headers=HEADERS, impersonate=IMPERSONATE,
                                timeout=60, allow_redirects=False)
    except Exception as error:  # network failure is an answer too
        print(f"[probe] request failed: {error!r}")
        return 1

    body = response.content or b""
    print(f"[probe] status        {response.status_code}")
    print(f"[probe] cf-mitigated  {response.headers.get('cf-mitigated') or '-'}")
    print(f"[probe] content-type  {response.headers.get('content-type') or '-'}")
    print(f"[probe] body bytes    {len(body)}")

    if response.status_code != 200:
        print("[probe] VERDICT: blocked/unavailable. Record it in "
              "docs/ksp-detail-plan.md (Outcome) and do not try variants.")
        return 1
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        print("[probe] VERDICT: 200 but not JSON (likely a challenge page). "
              "Record it as blocked.")
        return 1

    keys = _keys(payload)
    hits = [k for k in keys if PART_NUMBER_KEYS.search(k.rsplit(".", 1)[-1])]
    print(f"[probe] JSON keys     {len(keys)}")
    print("[probe] part-number-like keys:")
    for key in hits[:40]:
        print(f"           {key}")
    sample = MARKER_DIR / f"ksp-detail-probe-{uin}.json"
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[probe] saved the response to {sample} for the parser work")
    print("[probe] VERDICT: open. Phase 2 of docs/ksp-detail-plan.md can start.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
