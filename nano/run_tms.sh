#!/usr/bin/env bash
# Entrypoint the systemd timer (pc-parts-il-tms.timer) fires daily.
# Scrapes TMS via the same scraper/run_spider.py every environment uses,
# then commits+pushes today's raw file with the shared retry logic
# (§4/§5/§9/§10 of pc-parts-il-plan.md). See nano/README.md for one-time
# setup (Miniforge env, SSH deploy key).
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, regardless of where this is invoked from

# --- Sanity check: NTP sync (§4 — wrong clocks poison daily-history data) ---
if command -v timedatectl >/dev/null 2>&1; then
  if ! timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
    echo "[warn] system clock does not report NTP-synchronized — daily " \
         "date stamps may be wrong. Not blocking the run, but fix this." >&2
  fi
fi

# --- Pinned Python env (§4 — do NOT use the stock Jetson system Python) ---
# Adjust this path/env-name if your Miniforge install differs from the
# nano/README.md setup steps.
# shellcheck source=/dev/null
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate pc-parts-il

# --- Scrape (writes data/raw/<today>/tms.jsonl; exits non-zero on 0 items,
# including the §7-rule-6 hard-stop-on-block case) ---
python scraper/run_spider.py tms

# --- Commit + push (shared retry logic — §10, two writers can race) ---
git config user.email "bot@users.noreply.github.com"
git config user.name "pc-parts-il-nano"
TODAY="$(date -u +%F)"
bash scripts/git_commit_push.sh "scrape(tms): ${TODAY} [nano]" "data/raw/${TODAY}/tms.jsonl"
