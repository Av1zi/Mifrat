"""Gate: the CI build / publish split stays split.

Every workflow that pushes main is two jobs (Nov 2026 security audit, C-1):
a build job that installs packages, runs scrapers, Chromium, the normalizer,
image decoders or AI calls with a READ-ONLY token, and a publish job that
holds `contents: write` and runs none of that - it downloads the build job's
bundle (scripts/ci_bundle.sh), applies it and pushes with
scripts/git_commit_push.sh. A compromised dependency or a parser bug in the
build job then has no token that can rewrite main, which is both the database
and the deploy trigger.

The split is easy to undo by accident (one `pip install` added to a publish
job, one checkout without `persist-credentials: false`), so this pins it:

  1. every job states `timeout-minutes`;
  2. every `uses:` is pinned to a 40-hex commit SHA (local `./` actions aside);
  3. no workflow-level `contents: write` / `write-all`, and every job has
     permissions, its own or the workflow's;
  4. a job holding `contents: write` uses only checkout, setup-python and
     download-artifact, and none of its lines (comments aside) installs or
     runs third-party code or reads a secret;
  5. every other job's checkout sets `persist-credentials: false`;
  6. no `pull_request_target` trigger.

Line-based on purpose: PyYAML is not a pinned dependency, and the workflows
keep a plain two-space layout. Exit 0 = all workflows pass; exit 1 = a trip
(each printed as file:line).

Run:
    python scripts/check_workflows.py
    python scripts/check_workflows.py --self-test
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

WRITE_JOB_ACTIONS = {"actions/checkout", "actions/setup-python", "actions/download-artifact"}
WRITE_JOB_FORBIDDEN = (
    "pip install",
    "pip3 install",
    "playwright",
    "scrapy",
    "scraper",
    "run_spider",
    "npm",
    "npx",
    "node ",
    "secrets.",
    "curl ",
    "wget ",
)
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(['\"]?)([^\s'\"#]+)\1")
TRAILING_COMMENT = re.compile(r"\s+#.*$")


def _code(line: str) -> str:
    """The line without YAML/shell comments."""
    if line.lstrip().startswith("#"):
        return ""
    return TRAILING_COMMENT.sub("", line)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _jobs(lines: list[str]) -> list[tuple[str, int, list[tuple[int, str]]]]:
    """(job id, 1-based line, [(line no, text), ...]) for each job."""
    jobs: list[tuple[str, int, list[tuple[int, str]]]] = []
    in_jobs = False
    for no, raw in enumerate(lines, 1):
        line = _code(raw).rstrip()
        if not line.strip():
            if jobs and in_jobs:
                jobs[-1][2].append((no, raw))
            continue
        ind = _indent(line)
        if ind == 0:
            in_jobs = line.startswith("jobs:")
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if ind == 2 and m:
            jobs.append((m.group(1), no, []))
            continue
        if jobs:
            jobs[-1][2].append((no, raw))
    return jobs


def _top_level_block(lines: list[str], key: str) -> list[str]:
    out: list[str] = []
    inside = False
    for raw in lines:
        line = _code(raw).rstrip()
        if not line.strip():
            continue
        if _indent(line) == 0:
            inside = line.startswith(f"{key}:")
            if inside:
                out.append(line)
            continue
        if inside:
            out.append(line)
    return out


def _grants_write(block: list[str]) -> bool:
    text = "\n".join(block)
    return bool(re.search(r"\bcontents:\s*write\b", text) or "write-all" in text)


def _job_permissions(body: list[tuple[int, str]]) -> list[str] | None:
    out: list[str] = []
    inside = False
    for _, raw in body:
        line = _code(raw).rstrip()
        if not line.strip():
            continue
        ind = _indent(line)
        if ind == 4:
            inside = line.strip().startswith("permissions:")
            if inside:
                out.append(line)
            continue
        if inside and ind > 4:
            out.append(line)
    return out or None


def _steps(body: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    steps: list[list[tuple[int, str]]] = []
    step_indent = None
    in_steps = False
    for no, raw in body:
        line = _code(raw).rstrip()
        if not line.strip():
            continue
        ind = _indent(line)
        if ind == 4:
            in_steps = line.strip() == "steps:"
            step_indent = None
            continue
        if not in_steps:
            continue
        if line.lstrip().startswith("- ") and (step_indent is None or ind == step_indent):
            step_indent = ind
            steps.append([(no, raw)])
        elif steps:
            steps[-1].append((no, raw))
    return steps


def check_workflow(path: Path, text: str) -> list[str]:
    trips: list[str] = []
    lines = text.splitlines()
    name = path.name

    for no, raw in enumerate(lines, 1):
        code = _code(raw)
        if re.match(r"^\s*pull_request_target\s*:", code):
            trips.append(f"{name}:{no}: pull_request_target trigger")
        m = USES.match(code)
        if m:
            ref = m.group(2)
            if ref.startswith("./"):
                continue
            if not PINNED.match(ref):
                trips.append(f"{name}:{no}: `uses: {ref}` is not pinned to a commit SHA")

    top_perms = _top_level_block(lines, "permissions")
    if top_perms and _grants_write(top_perms):
        trips.append(f"{name}: workflow-level permissions grant write; grant it per publish job")

    jobs = _jobs(lines)
    if not jobs:
        trips.append(f"{name}: no jobs found (layout changed? this gate reads two-space YAML)")
    for job, job_line, body in jobs:
        where = f"{name}:{job_line} job `{job}`"
        job_keys = [_code(raw).strip() for _, raw in body if _indent(_code(raw).rstrip() or " ") == 4]
        if not any(k.startswith("timeout-minutes:") for k in job_keys):
            trips.append(f"{where}: no timeout-minutes")
        perms = _job_permissions(body)
        if perms is None and not top_perms:
            trips.append(f"{where}: no permissions (would get the repo default token)")
        writes = _grants_write(perms) if perms is not None else _grants_write(top_perms)

        for step in _steps(body):
            step_code = [(no, _code(raw)) for no, raw in step]
            uses = [(no, USES.match(c)) for no, c in step_code]
            uses = [(no, m.group(2)) for no, m in uses if m]
            for no, ref in uses:
                action = ref.split("@", 1)[0]
                if writes and action not in WRITE_JOB_ACTIONS:
                    trips.append(f"{name}:{no}: write job `{job}` uses {action}")
                if not writes and action == "actions/checkout":
                    if not any(re.match(r"^\s*persist-credentials:\s*false\s*$", c) for _, c in step_code):
                        trips.append(f"{name}:{no}: job `{job}` checks out without persist-credentials: false")

        if writes:
            for no, raw in body:
                code = _code(raw).lower()
                for token in WRITE_JOB_FORBIDDEN:
                    if token in code:
                        trips.append(f"{name}:{no}: write job `{job}` contains `{token.strip()}`")
    return trips


def run(paths: list[Path]) -> int:
    trips: list[str] = []
    for path in paths:
        trips.extend(check_workflow(path, path.read_text(encoding="utf-8")))
    if trips:
        for t in trips:
            print(f"[workflows] FAIL {t}")
        print(f"[workflows] {len(trips)} trip(s) in {len(paths)} workflow(s)")
        return 1
    print(f"[workflows] pass - {len(paths)} workflows: write jobs isolated, actions pinned, timeouts set")
    return 0


SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"

GOOD = f"""name: t
on:
  push: {{}}
jobs:
  build:
    permissions:
      contents: read
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@{SHA}  # v5
        with:
          persist-credentials: false
      - run: pip install -r requirements.txt  # build jobs may install
  publish:
    # no scraper here; comments are ignored
    permissions:
      contents: write
    needs: build
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@{SHA}  # v5
      - uses: actions/download-artifact@{SHA}
        with:
          name: b
      - run: |
          files=()
          [ "${{#files[@]}}" -eq 0 ] && exit 0
          bash scripts/git_commit_push.sh "m" data/x.json
"""


def _self_test() -> int:
    cases = [
        ("good workflow passes", GOOD, None),
        ("install in a write job", GOOD.replace("bash scripts/git_commit_push.sh", "pip install x; bash scripts/git_commit_push.sh"), "contains `pip install`"),
        ("scraper in a write job", GOOD.replace('"m" data/x.json', '"m" data/x.json; python -m scraper.extract'), "contains `scraper`"),
        ("secret in a write job", GOOD.replace("          name: b", "          name: ${{ secrets.X }}"), "contains `secrets.`"),
        ("other action in a write job", GOOD.replace("actions/download-artifact", "actions/setup-node"), "uses actions/setup-node"),
        ("credentials persisted in a read job", GOOD.replace("        with:\n          persist-credentials: false\n", "", 1), "without persist-credentials"),
        ("no timeout", GOOD.replace("    timeout-minutes: 10\n", ""), "no timeout-minutes"),
        ("tag-pinned action", GOOD.replace(f"actions/checkout@{SHA}  # v5\n        with", "actions/checkout@v5\n        with", 1), "not pinned"),
        ("workflow-level write", GOOD.replace("jobs:\n", "permissions:\n  contents: write\njobs:\n", 1), "workflow-level permissions"),
        ("no permissions at all", GOOD.replace("    permissions:\n      contents: read\n", ""), "no permissions"),
        ("pull_request_target", GOOD.replace("  push: {}", "  pull_request_target: {}"), "pull_request_target"),
    ]
    failed = 0
    for label, text, expect in cases:
        trips = check_workflow(Path("t.yml"), text)
        ok = not trips if expect is None else any(expect in t for t in trips)
        if not ok:
            failed += 1
            print(f"[workflows] self-test FAIL {label}: {trips}")
    if failed:
        return 1
    print(f"[workflows] self-test pass - {len(cases)} checks")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not paths:
        print(f"[workflows] FAIL no workflows under {WORKFLOWS}")
        return 1
    return run(paths)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
