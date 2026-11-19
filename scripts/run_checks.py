"""Run the pipeline's checks: one list, each check states whether it blocks.

Every check used to be its own workflow step, and every step blocked. Most of
them grade the night's live data against a fixed budget (a listing vanishes,
a ledger entry goes stale, a backtest rule dips to 97%), so about 30 of 120
normalize runs stopped the publish and froze every vendor's prices without
anything being broken. Here each check has a level:

  code       reads no nightly data (fixtures, self-tests, schema sync), so it
             cannot flap: a failure is a code bug and BLOCKS.
  integrity  would ship a broken site (a category collapsed, the publish set
             is incoherent, a payload over the limit, a site of placeholder
             covers): BLOCKS.
  quality    measures data that moves every night: WARNS. The run publishes;
             the warning goes to data/ops/checks.json with the night it
             started, the scrape console lists it, and the Worker raises it
             to urgent once it has been open for ESCALATE_NIGHTS nights.
             A warning never turns back into a block.

Golden fixtures warn on exit 1 (a value regressed) and exit 2 (identity
churn), owner decision 2026-11-15; their population guard is the separate
`population` integrity check.

    python scripts/run_checks.py --suite publish   # normalize-and-deploy.yml
    python scripts/run_checks.py --suite code      # site-checks.yml
    python scripts/run_checks.py --list
    python scripts/run_checks.py --self-test

Exit 0 = nothing blocks (warnings allowed); exit 1 = a code or integrity
check failed. `--suite publish` writes data/ops/checks.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.night import nights_between, scrape_night  # noqa: E402

OUT = ROOT / "data" / "ops" / "checks.json"
CATALOG = ROOT / "data" / "catalog.json"
SCHEMA_VERSION = 1
ESCALATE_NIGHTS = 3
DETAIL_LINES = 12
DETAIL_CHARS = 1200

CODE, INTEGRITY, QUALITY = "code", "integrity", "quality"
BLOCKING = {CODE, INTEGRITY}
PUBLISH, CODE_SUITE = "publish", "code"
BOTH = (PUBLISH, CODE_SUITE)


@dataclass
class Check:
    name: str
    level: str
    title: str
    # argv relative to ROOT; "{baseline}" is replaced by the committed catalog.
    argv: list[str] = field(default_factory=list)
    suites: tuple[str, ...] = (PUBLISH,)
    # exit code -> "pass" | "warn" | "fail"; unlisted: 0 pass, else fail.
    codes: dict[int, str] = field(default_factory=dict)
    # In-process check: () -> (exit code, output lines).
    func: Callable[[], tuple[int, list[str]]] | None = None


def py(script: str, *args: str) -> list[str]:
    return [sys.executable, script, *args]


GOLDEN_CODES = {0: "pass", 1: "warn", 2: "warn"}


def population() -> tuple[int, list[str]]:
    """Integrity: the fresh catalog is not empty and no category collapsed
    against the committed one (check_golden.population_problems: a category
    of 10+ products losing >15%, the catalog losing >10%)."""
    from scraper.specs.golden.check_golden import population_problems

    if not CATALOG.exists():
        return 1, [f"[population] FAIL {CATALOG} missing (run the normalizer)"]
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    problems = population_check(catalog, _baseline_catalog(), population_problems)
    if problems:
        return 1, [f"[population] FAIL {p}" for p in problems]
    return 0, [f"[population] pass - {len(catalog.get('products') or [])} products, "
               f"{len(catalog.get('listings') or [])} listings"]


def population_check(catalog: dict, baseline: dict | None, problems_fn) -> list[str]:
    problems: list[str] = []
    if not catalog.get("products"):
        problems.append("catalog has no products")
    if not catalog.get("listings"):
        problems.append("catalog has no listings")
    if baseline:
        problems.extend(problems_fn(catalog, baseline))
    return problems


def population_source_churn() -> tuple[int, list[str]]:
    """Keep source-caused category reductions visible without freezing prices."""
    from scraper.specs.golden.check_golden import population_source_losses, POPULATION_CATEGORY_DROP
    if not CATALOG.exists():
        return 1, ["[source-churn] catalog missing"]
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    baseline = _baseline_catalog()
    if not baseline:
        return 0, ["[source-churn] no baseline"]
    from collections import Counter
    before = Counter(p.get("category") for p in baseline.get("products") or [])
    after = Counter(p.get("category") for p in catalog.get("products") or [])
    lost = population_source_losses(catalog, baseline)
    lines = [f"[source-churn] {category}: {before[category]} -> {after[category]}, "
             f"{count} products absent from vendor input (not confirmed gone)"
             for category, count in sorted(lost.items())
             if after[category] < before[category] * (1 - POPULATION_CATEGORY_DROP)]
    return (1, lines) if lines else (0, ["[source-churn] no large source-caused category reduction"])


_BASELINE: dict = {}


def _baseline_path() -> str | None:
    """The committed data/catalog.json (the last publish), in a temp file."""
    if "path" not in _BASELINE:
        try:
            blob = subprocess.run(["git", "show", "HEAD:data/catalog.json"], cwd=ROOT,
                                  capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            _BASELINE["path"] = None
        else:
            handle = tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False)
            handle.write(blob)
            handle.close()
            _BASELINE["path"] = handle.name
    return _BASELINE["path"]


def _baseline_catalog() -> dict | None:
    path = _baseline_path()
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return None


# Order: the code checks first, so a code bug reads before its data symptoms.
CHECKS: list[Check] = [
    # --- code: no nightly data, a failure is a bug -------------------------
    Check("spec_sync", CODE, "Spec schema <-> frontend drift", py("scripts/check_spec_sync.py"), BOTH),
    Check("mfr_schema", CODE, "Manufacturer data at the schema version",
          py("scripts/migrate_mfr_schema.py", "--check"), BOTH),
    Check("golden_resolution", CODE, "Golden-fixture resolver self-test",
          py("scripts/check_golden_resolution.py"), BOTH),
    Check("tms_detail", CODE, "TMS detail-page parser (fixtures)", py("scripts/check_tms_detail.py"), BOTH),
    Check("spec_merge", CODE, "Spec merge-layer rules", py("scripts/check_spec_merge.py"), BOTH),
    Check("categories_fixtures", CODE, "Category assignment fixtures",
          py("scripts/check_categories.py", "--self-test"), BOTH),
    Check("identity_fixtures", CODE, "Identity reader fixtures",
          py("scripts/check_identity_merge.py", "--self-test"), BOTH),
    Check("identity_connectivity", CODE, "Identity evidence survives variant splits",
          py("scripts/check_identity_connectivity.py"), BOTH),
    Check("brands_selftest", CODE, "Brand rules self-test", py("scripts/check_brands.py", "--self-test"), BOTH),
    Check("snapshot_rows_selftest", CODE, "Repeated snapshot rows self-test",
          py("scripts/check_snapshot_rows.py", "--self-test"), BOTH),
    Check("text_hygiene_selftest", CODE, "Text hygiene self-test",
          py("scripts/check_text_hygiene.py", "--self-test"), BOTH),
    Check("ksp_tags", CODE, "KSP listing-tag mapper", py("scripts/check_ksp_tags.py"), BOTH),
    Check("ksp_detail", CODE, "KSP detail parser", py("scripts/check_ksp_detail.py"), BOTH),
    Check("ksp_stream", CODE, "KSP component stream protocol", py("scripts/check_ksp_stream.py"), BOTH),
    Check("ksp_stream_spider", CODE, "KSP stream transport offline integration",
          py("scripts/check_ksp_stream_spider.py"), BOTH),
    Check("ksp_schedule", CODE, "KSP delayed recovery and captured routes", py("scripts/check_ksp_schedule.py"), BOTH),
    Check("scrape_outcomes", CODE, "Scrape block stops and runner outcomes",
          py("scripts/check_scrape_outcomes.py"), BOTH),
    Check("population_selftest", CODE, "Population loss attribution",
          py("scripts/check_population.py"), BOTH),
    Check("nano_diagnostics", CODE, "Read-only Nano diagnostics survive unreadable units",
          py("scripts/check_nano_diagnostics.py"), BOTH),
    Check("eilat", CODE, "Eilat price parsers, attach and history rules", py("scripts/check_eilat.py"), BOTH),
    Check("xref_fixtures", CODE, "Saved-page parsers", py("scripts/check_xref_fixtures.py"), BOTH),
    Check("extract_selftest", CODE, "AI-extraction verifier and client",
          py("scripts/check_extract.py", "--self-test"), BOTH),
    Check("ledgers_selftest", CODE, "Ledger rules self-test", py("scripts/check_ledgers.py", "--self-test"), BOTH),
    Check("coverage_selftest", CODE, "Coverage gate arithmetic",
          py("scripts/check_spec_coverage.py", "--self-test"), BOTH),
    Check("spec_invariants_selftest", CODE, "Spec invariants self-test",
          py("scripts/check_spec_invariants.py", "--self-test"), BOTH),
    Check("image_pick", CODE, "Photo pipeline rules", py("scripts/check_image_pick.py"), BOTH),
    Check("ops_report_selftest", CODE, "Ops report rules", py("scripts/check_ops_report.py", "--self-test"), BOTH),
    Check("publish_set_selftest", CODE, "Publish set rules",
          py("scripts/check_publish_set.py", "--self-test"), BOTH),
    Check("run_checks_selftest", CODE, "Check levels and carry-over",
          py("scripts/run_checks.py", "--self-test"), BOTH),
    Check("night_selftest", CODE, "Scrape-night date and one-file-per-night rule",
          py("scraper/night.py", "--self-test"), BOTH),
    Check("image_fetch", CODE, "Image fetch limits (local server)",
          py("scripts/check_image_fetch.py"), (CODE_SUITE,)),
    Check("qa_tool", CODE, "QA tool refuses cross-site writes", py("scripts/check_qa_tool.py"), (CODE_SUITE,)),
    Check("ops_notify", CODE, "Nano run notifier", ["bash", "scripts/check_ops_notify.sh"], (CODE_SUITE,)),
    Check("nano_night", CODE, "Nano 1PC run: one folder per scrape night",
          ["bash", "scripts/check_nano_night.sh"], (CODE_SUITE,)),
    Check("nano_ksp", CODE, "Nano KSP phase state and push recovery",
          ["bash", "scripts/check_nano_ksp.sh"], BOTH),
    # --- integrity: the site would be broken -------------------------------
    Check("population", INTEGRITY, "Catalog not empty, no category collapsed", func=population),
    Check("text_hygiene", INTEGRITY, "Shipped text hygiene", py("scripts/check_text_hygiene.py")),
    Check("image_files", INTEGRITY, "Cover corpus (format, size, borders)",
          py("scripts/check_image_files.py"), BOTH),
    Check("site_images_ceiling", INTEGRITY, "Site is not a wall of placeholder covers",
          py("scripts/check_site_images.py", "--ceiling")),
    Check("site_size", INTEGRITY, "Site payload size", py("scraper/check_site_size.py")),
    Check("ops_report", INTEGRITY, "Ops report files", py("scripts/check_ops_report.py")),
    Check("publish_set", INTEGRITY, "Publish set coherence", py("scripts/check_publish_set.py"), BOTH),
    # --- quality: nightly data, warns --------------------------------------
    Check("source_churn", QUALITY, "Category reduction from source absences", func=population_source_churn),
    Check("golden", QUALITY, "Spec golden fixtures",
          [sys.executable, "-m", "scraper.specs.golden.check_golden", "--baseline", "{baseline}"],
          codes=GOLDEN_CODES),
    Check("identity", QUALITY, "Identity-merge invariants", py("scripts/check_identity_merge.py", "--data")),
    Check("categories", QUALITY, "One maker PN per category, is-a words",
          py("scripts/check_categories.py", "--data")),
    Check("brands", QUALITY, "One maker per product, every product branded", py("scripts/check_brands.py")),
    Check("snapshot_rows", QUALITY, "Repeated snapshot rows", py("scripts/check_snapshot_rows.py")),
    Check("extract_reach", QUALITY, "Extract store reach", py("scripts/check_extract.py", "--data")),
    Check("ledgers", QUALITY, "Ledgers point at live data", py("scripts/check_ledgers.py")),
    Check("backtest", QUALITY, "Inference-rule backtest", py("scripts/backtest_rules.py", "--check")),
    Check("coverage", QUALITY, "Spec coverage floors", py("scripts/check_spec_coverage.py")),
    Check("spec_invariants", QUALITY, "Spec invariants", py("scripts/check_spec_invariants.py")),
    Check("site_images", QUALITY, "Site image resolvability (2% budget)", py("scripts/check_site_images.py")),
]


@dataclass
class Outcome:
    check: Check
    status: str          # pass | warn | fail
    exit: int
    seconds: float
    tail: list[str]


def status_for(check: Check, code: int) -> str:
    """pass / warn / fail for an exit code; a quality failure is a warning."""
    status = check.codes.get(code, "pass" if code == 0 else "fail")
    if status == "fail" and check.level == QUALITY:
        return "warn"
    return status


def _run_command(argv: list[str], echo: bool = True) -> tuple[int, list[str]]:
    baseline = _baseline_path() if "{baseline}" in argv else None
    if "{baseline}" in argv:
        if baseline:
            argv = [baseline if a == "{baseline}" else a for a in argv]
        else:
            at = argv.index("{baseline}")
            argv = argv[:at - 1] + argv[at + 1:]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    tail: deque[str] = deque(maxlen=DETAIL_LINES)
    try:
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace")
    except OSError as exc:
        return 1, [f"could not start {argv[0]}: {exc}"]
    assert proc.stdout is not None
    for line in proc.stdout:
        if echo:
            sys.stdout.write(line)
        if line.strip():
            tail.append(line.rstrip())
    return proc.wait(), list(tail)


def run_one(check: Check) -> Outcome:
    started = time.monotonic()
    if check.func is not None:
        try:
            code, lines = check.func()
        except Exception as exc:  # a crashed check is a failed check
            code, lines = 1, [f"{type(exc).__name__}: {exc}"]
        for line in lines:
            print(line)
        tail = lines[-DETAIL_LINES:]
    else:
        code, tail = _run_command(check.argv)
    return Outcome(check, status_for(check, code), code, time.monotonic() - started, tail)


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def report(outcomes: list[Outcome], previous: dict | None, now: datetime, suite: str) -> dict:
    """data/ops/checks.json. A warning keeps the `since` of the previous run's
    open warning of the same name, so `nights` counts the streak."""
    before = {c.get("name"): c for c in (previous or {}).get("checks") or []}
    rows = []
    for o in outcomes:
        since = None
        if o.status != "pass":
            old = before.get(o.check.name) or {}
            since = old.get("since") if old.get("status") == o.status and old.get("since") else _iso(now)
        detail = "\n".join(o.tail)
        if len(detail) > DETAIL_CHARS:
            detail = "..." + detail[-(DETAIL_CHARS - 3):]
        rows.append({
            "name": o.check.name,
            "level": o.check.level,
            "title": o.check.title,
            "status": o.status,
            "exit": o.exit,
            "seconds": round(o.seconds, 1),
            "since": since,
            "nights": nights_between(datetime.fromisoformat(since), now) if since else 0,
            "detail": detail if o.status != "pass" else "",
        })
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "night": scrape_night(now).isoformat(),
        "suite": suite,
        "escalate_nights": ESCALATE_NIGHTS,
        "blocked": any(r["status"] == "fail" for r in rows),
        "checks": rows,
    }


def _read_previous(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if doc.get("schema") == SCHEMA_VERSION else None


def _summary(doc: dict) -> list[str]:
    lines = []
    for row in doc["checks"]:
        if row["status"] == "pass":
            continue
        streak = f", open {row['nights']} night(s)" if row["status"] == "warn" else ""
        lines.append(f"{row['status'].upper():4} {row['name']} ({row['level']}{streak}): {row['title']}")
    return lines


def _annotate(doc: dict) -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    for row in doc["checks"]:
        if row["status"] == "pass":
            continue
        kind = "error" if row["status"] == "fail" else "warning"
        last = (row["detail"].splitlines() or [""])[-1].replace("%", "%25").replace("\n", " ")
        print(f"::{kind} title={row['name']} ({row['level']})::{row['title']}: {last}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## Checks ({doc['suite']})\n\n| check | level | result | open nights |\n|---|---|---|---|\n")
            for row in doc["checks"]:
                if row["status"] != "pass":
                    f.write(f"| {row['name']} | {row['level']} | {row['status']} | {row['nights']} |\n")
            passed = sum(1 for r in doc["checks"] if r["status"] == "pass")
            f.write(f"\n{passed} of {len(doc['checks'])} passed.\n")


def run_suite(suite: str, only: set[str] | None, out: Path | None) -> int:
    checks = [c for c in CHECKS if suite in c.suites and (not only or c.name in only)]
    now = datetime.now(timezone.utc)
    outcomes = []
    gh = bool(os.environ.get("GITHUB_ACTIONS"))
    for check in checks:
        print(f"::group::[{check.level}] {check.name}: {check.title}" if gh
              else f"\n=== [{check.level}] {check.name}: {check.title}", flush=True)
        outcome = run_one(check)
        if gh:
            print("::endgroup::")
        print(f"--> {check.name}: {outcome.status} (exit {outcome.exit}, {outcome.seconds:.1f}s)", flush=True)
        outcomes.append(outcome)
    doc = report(outcomes, _read_previous(out) if out else None, now, suite)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _annotate(doc)
    print()
    for line in _summary(doc):
        print("  " + line)
    passed = sum(1 for o in outcomes if o.status == "pass")
    warned = sum(1 for o in outcomes if o.status == "warn")
    failed = sum(1 for o in outcomes if o.status == "fail")
    print(f"[run-checks] {suite}: {passed} pass, {warned} warn, {failed} block"
          + (f"; wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}" if out else ""))
    return 1 if failed else 0


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


def self_test() -> int:
    problems: list[str] = []

    def expect(label: str, got, want) -> None:
        if got != want:
            problems.append(f"{label}: got {got!r}, want {want!r}")

    # Levels.
    for level, code, want in ((CODE, 1, "fail"), (INTEGRITY, 1, "fail"), (QUALITY, 1, "warn"),
                              (QUALITY, 0, "pass"), (CODE, 0, "pass"), (QUALITY, 3, "warn")):
        expect(f"{level} exit {code}", status_for(Check("x", level, "x"), code), want)
    golden = next(c for c in CHECKS if c.name == "golden")
    for code, want in ((0, "pass"), (2, "warn"), (1, "warn")):
        expect(f"golden exit {code}", status_for(golden, code), want)

    # Every check is well formed and runnable.
    names = [c.name for c in CHECKS]
    expect("unique names", len(names), len(set(names)))
    for c in CHECKS:
        if c.level not in (CODE, INTEGRITY, QUALITY):
            problems.append(f"{c.name}: unknown level {c.level}")
        if bool(c.argv) == bool(c.func):
            problems.append(f"{c.name}: needs exactly one of argv / func")
        script = next((a for a in c.argv[1:] if a.endswith((".py", ".sh"))), None)
        if script and not (ROOT / script).exists():
            problems.append(f"{c.name}: {script} does not exist")
        if c.level == QUALITY and CODE_SUITE in c.suites:
            problems.append(f"{c.name}: a data check in the code suite would flap on PRs")

    # A quality-only run passes; any blocking failure fails the run.
    def outcome(name: str, level: str, code: int) -> Outcome:
        check = Check(name, level, name, ["x"])
        return Outcome(check, status_for(check, code), code, 0.0, ["line"])

    t0 = datetime(2026, 11, 13, 5, 30, tzinfo=timezone.utc)
    doc = report([outcome("a", QUALITY, 1), outcome("b", CODE, 0)], None, t0, PUBLISH)
    expect("warnings do not block", doc["blocked"], False)
    doc = report([outcome("a", QUALITY, 1), outcome("b", INTEGRITY, 1)], None, t0, PUBLISH)
    expect("integrity blocks", doc["blocked"], True)

    # Carry-over: a warning open on 11-13, 11-14 and 11-15 is 3 nights; one
    # that cleared and came back starts again; a pass has no `since`.
    first = report([outcome("a", QUALITY, 1), outcome("b", QUALITY, 1)], None, t0, PUBLISH)
    expect("new warning starts now", first["checks"][0]["since"], _iso(t0))
    expect("new warning is night 1", first["checks"][0]["nights"], 1)
    t1 = datetime(2026, 11, 14, 5, 30, tzinfo=timezone.utc)
    second = report([outcome("a", QUALITY, 1), outcome("b", QUALITY, 0)], first, t1, PUBLISH)
    expect("pass clears since", second["checks"][1]["since"], None)
    t2 = datetime(2026, 11, 15, 5, 30, tzinfo=timezone.utc)
    third = report([outcome("a", QUALITY, 1), outcome("b", QUALITY, 1)], second, t2, PUBLISH)
    expect("streak keeps its start", third["checks"][0]["since"], _iso(t0))
    expect("third night", third["checks"][0]["nights"], 3)
    expect("a returning warning starts again", third["checks"][1]["since"], _iso(t2))
    expect("schema", third["schema"], SCHEMA_VERSION)
    expect("night", third["night"], "2026-11-15")
    expect("pass has no detail", second["checks"][1]["detail"], "")

    # Two runs in one night (a re-run): still the same night.
    late = datetime(2026, 11, 15, 20, 59, tzinfo=timezone.utc)
    expect("same night re-run", nights_between(t2, late), 1)
    expect("21:00 UTC is the next night", nights_between(t2, datetime(2026, 11, 15, 21, 0, tzinfo=timezone.utc)), 2)

    # Population: empty catalog and collapse block; a normal night passes.
    def cat(**counts):
        products = [{"category": k} for k, n in counts.items() for _ in range(n)]
        return {"products": products, "listings": [{}] * len(products)}

    from scraper.specs.golden.check_golden import population_problems as pp
    expect("normal night", population_check(cat(gpu=100, cpu=100), cat(gpu=100, cpu=100), pp), [])
    expect("small drop", population_check(cat(gpu=90, cpu=100), cat(gpu=100, cpu=100), pp), [])
    expect("category collapse", len(population_check(cat(gpu=80, cpu=1000), cat(gpu=100, cpu=1000), pp)), 1)
    expect("category + total collapse",
           len(population_check(cat(gpu=50, cpu=100), cat(gpu=100, cpu=100), pp)), 2)
    expect("empty", len(population_check({"products": [], "listings": []}, None, pp)), 2)
    expect("no baseline", population_check(cat(gpu=5), None, pp), [])

    # The detail is capped.
    big = Outcome(Check("big", QUALITY, "big", ["x"]), "warn", 1, 0.0, ["x" * 5000])
    expect("detail cap", len(report([big], None, t0, PUBLISH)["checks"][0]["detail"]), DETAIL_CHARS)

    # A real subprocess: exit codes reach the verdict, output is kept.
    code, tail = _run_command([sys.executable, "-c", "print('hello'); raise SystemExit(2)"], echo=False)
    expect("subprocess exit", code, 2)
    expect("subprocess tail", tail, ["hello"])

    for p in problems:
        print(f"[run-checks] FAIL {p}")
    if problems:
        return 1
    print(f"[run-checks] self-test passed ({len(CHECKS)} checks declared)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--suite", choices=BOTH)
    parser.add_argument("--only", help="comma-separated check names (local debugging)")
    parser.add_argument("--out", type=Path, help=f"results file (default for --suite publish: {OUT.relative_to(ROOT)})")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.self_test:
        return self_test()
    if args.list:
        for c in CHECKS:
            print(f"{c.level:9} {c.name:26} {','.join(c.suites):13} {c.title}")
        return 0
    if not args.suite:
        parser.error("--suite is required")
    only = set(args.only.split(",")) if args.only else None
    # A partial run never replaces the results file: it would end the other
    # checks' streaks.
    out = args.out or (OUT if args.suite == PUBLISH and not only else None)
    return run_suite(args.suite, only, out)


if __name__ == "__main__":
    raise SystemExit(main())
