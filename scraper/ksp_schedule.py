"""Public KSP recovery schedule; no access tokens or live requests."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

CONFIG = Path(__file__).with_name("ksp_schedule.json")


def resume_after():
    return datetime.fromisoformat(json.loads(CONFIG.read_text())["resume_after"])


def ready(now=None):
    clock = os.environ.get("MIFRAT_NOW")
    at = now or (datetime.fromisoformat(clock.replace("Z", "+00:00")) if clock else datetime.now(timezone.utc))
    return at >= resume_after()


def snapshot_times(rows):
    """Newest vendor crawl stamps; never infer freshness from build time."""
    result = {}
    for row in rows:
        vendor, stamp = row.get("vendor_id"), row.get("scraped_at")
        if vendor and stamp and stamp > result.get(vendor, ""):
            result[vendor] = stamp
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["ready"]:
        raise SystemExit(0 if ready() else 1)
    print(resume_after().isoformat())
