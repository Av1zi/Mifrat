"""Read-only Nano scrape diagnostics; never prints raw journal or secrets.

Run on the Nano: python scripts/diagnose_nano_scrapes.py --since 2026-11-16
No crawling, git mutation, timer changes or credential-file reads.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UNITS = [f"pc-parts-il-{name}.{kind}" for name in ("ksp", "ksp-detail", "onepc", "tms")
         for kind in ("service", "timer")]


def read_command(*args: str) -> str:
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=lambda raw: datetime.strptime(raw, "%Y-%m-%d").date(),
                        default=date.today() - timedelta(days=3))
    parser.add_argument("--repo", type=Path, default=ROOT,
                        help="checkout to inspect (supports copying this script outside the repo)")
    args = parser.parse_args()
    root = args.repo.resolve()
    print("utc_now", datetime.now(timezone.utc).isoformat(), "since", str(args.since))
    for unit in UNITS:
        facts = {}
        for key in ("ActiveState", "SubState", "Result", "ExecMainStatus", "LastTriggerUSec", "NextElapseUSecRealtime"):
            value = read_command("systemctl", "show", unit, f"--property={key}", "--value").strip()
            # Fixed systemd vocabulary/timestamps, not unit Environment.
            facts[key] = value if re.fullmatch(r"[\w :+./-]{0,100}", value) else "unavailable"
        installed = Path("/etc/systemd/system") / unit
        source = root / "nano" / unit
        facts["matches_repo"] = installed.read_bytes() == source.read_bytes() if installed.is_file() and source.is_file() else None
        print(unit, json.dumps(facts))
        if not unit.endswith(".service"):
            continue
        log = read_command("journalctl", "-q", "-o", "cat", "-u", unit, "--since", str(args.since))
        # Summaries only: arbitrary log lines and response bodies never leave
        # the machine, even when they contain an auth/session value.
        signals = Counter()
        patterns = {"http_403": r"HTTP 403|response_status_count/403", "http_429": r"HTTP 429|response_status_count/429",
                    "blocked": r"blocked|BLOCKED", "partial": r"incomplete|floor|zero items",
                    "push_failed": r"push failed|push rejected", "crash": r"Traceback|ModuleNotFoundError",
                    "started": r"starting spider|fetching \d+ KSP", "pushed": r"snapshot pushed|\[ok\] pushed",
                    "timeout": r"timed out|timeout"}
        for label, pattern in patterns.items():
            signals[label] = len(re.findall(pattern, log))
        revisions = re.findall(r"code revision: ([0-9a-f]{7,40})\b", log)
        print("journal_signals", json.dumps(dict(signals)), "revisions", revisions)
        # Extract only fixed numeric KSP diagnostics, never an exception's
        # arbitrary string, request meta, response body or credential values.
        for label, pattern in {
            "category_total": r"\[ksp\] category (\d+): products_total (\d+) is below the minimum ([\d.]+) for the verified baseline (\d+)",
            "category_truncated": r"\[ksp\] category (\d+): fetched (\d+) unique uins of (\d+)",
            "price_coverage": r"\[ksp\] (\d+)/(\d+) rows had no usable price",
            "stock_coverage": r"\[ksp\] (\d+)/(\d+) rows had no stock signal",
            "http_block": r"\[ksp\] BLOCKED \((\d+)\): page (\d+): HTTP (403|429)",
            "listing_counts": r"\[run_ksp\] spider done[^\n]*?\b(\d+) items written",
            "exception_class": r"\b(ModuleNotFoundError|ImportError|TypeError|AttributeError|ValueError|TimeoutError|PermissionError):",
        }.items():
            matches = re.findall(pattern, log)
            if matches:
                print(label, json.dumps(matches[-20:]))
    print("checkout", read_command("git", "-C", str(root), "rev-parse", "HEAD").strip())
    dirty = read_command("git", "--no-optional-locks", "-C", str(root), "status", "--porcelain")
    print("uncommitted_paths", len(dirty.splitlines()))
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "pc-parts-il"
    print("markers", sorted(p.name for p in state.glob("ksp-*")
                             if re.fullmatch(r"ksp-(?:detail-)?\d{4}-\d{2}-\d{2}\.[a-z]+", p.name)))
    print("paused", (state / "ksp.paused").exists())
    python = Path.home() / "miniforge3/envs/pc-parts-il/bin/python"
    if python.is_file():
        print("crawler_dependencies", read_command(str(python), "-c",
              "import importlib.metadata as m; "
              "print({n:m.version(n) for n in ['Scrapy','scrapy-curl-cffi','curl-cffi']})").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
