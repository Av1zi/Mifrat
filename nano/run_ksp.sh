#!/usr/bin/env bash
# KSP listing scrape on the Nano. KSP's Cloudflare edge blocks datacenter IPs
# and plain TLS clients, so this runs from the home connection only, after the
# TMS/1PC windows. Listing-only: the item detail endpoint is WAF-blocked, so
# there is no detail/image phase here (see decisions.md, 2026-10-30).
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
TODAY="$(date +%F)"
OUT_FILE="$REPO_DIR/data/raw/$TODAY/ksp.jsonl"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
SUCCESS_MARKER="$STATE_DIR/ksp-$TODAY.success"
# 80% of the 2026-10-30 baseline (1,087). run_spider also warns below 800;
# the spider itself refuses a short run, so this is a second, post-hoc gate.
MIN_ITEMS=800

if ! timedatectl status | grep -q "synchronized: yes"; then
    echo "[warn] system clock not NTP-synchronized" >&2
fi

cd "$REPO_DIR"

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    echo "[warn] stale rebase state found — aborting it to recover" >&2
    git rebase --abort || true
fi
echo "[run_ksp] updating checkout..."
git pull --rebase --autostash
echo "[run_ksp] code revision: $(git rev-parse --short HEAD)"

echo "[run_ksp] starting spider at $(date -Iseconds)"
"$PYTHON" scraper/run_spider.py ksp

if [ ! -f "$OUT_FILE" ]; then
    echo "[error] no snapshot at $OUT_FILE — not committing" >&2
    exit 1
fi

ITEM_COUNT="$(wc -l < "$OUT_FILE")"
echo "[run_ksp] spider done — $ITEM_COUNT items written to $OUT_FILE"
if [ "$ITEM_COUNT" -lt "$MIN_ITEMS" ]; then
    echo "[error] only $ITEM_COUNT items (floor $MIN_ITEMS) — treating as a" \
         "partial run and not committing" >&2
    exit 1
fi

bash scripts/git_commit_push.sh \
    "ksp snapshot $TODAY ($ITEM_COUNT items)" \
    "data/raw/$TODAY/ksp.jsonl"

mkdir -p "$STATE_DIR"
touch "$SUCCESS_MARKER"
find "$STATE_DIR" -name 'ksp-*.success' -type f -mtime +14 -delete
echo "[run_ksp] done at $(date -Iseconds)"
