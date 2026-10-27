#!/usr/bin/env bash
# 1PC listing scrape on the Nano (home IP). Moved here from the cloud matrix
# 2026-10-24 after 1PC started answering datacenter runs with a CAPTCHA page.
# Same rules as TMS: 1 run/day, sequential, throttled, hard stop on blocks
# (spiders/onepc.py), never retry against a block. Detail pages stay in the
# cloud detail-scrape job.
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
SCRAPY="/home/avizi/miniforge3/envs/pc-parts-il/bin/scrapy"
TODAY="$(date -u +%F)"
OUT_DIR="$REPO_DIR/data/raw/$TODAY"
OUT_FILE="$OUT_DIR/onepc.jsonl"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
SUCCESS_MARKER="$STATE_DIR/onepc-$TODAY.success"

cd "$REPO_DIR"

if [ "${RUN_ONEPC_FALLBACK:-0}" = "1" ] && [ -f "$SUCCESS_MARKER" ]; then
    echo "[run_onepc] overnight scrape already completed; fallback is not needed"
    exit 0
fi

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    echo "[warn] stale rebase state found - aborting it to recover" >&2
    git rebase --abort || true
fi
git pull --rebase --autostash
echo "[run_onepc] code revision: $(git rev-parse --short HEAD)"

mkdir -p "$OUT_DIR"
rm -f "$OUT_FILE"
"$SCRAPY" crawl onepc \
    -s "FEEDS={\"$OUT_FILE\":{\"format\":\"jsonl\",\"encoding\":\"utf-8\"}}"

ITEM_COUNT="$( [ -f "$OUT_FILE" ] && wc -l < "$OUT_FILE" || echo 0 )"
echo "[run_onepc] $ITEM_COUNT items written to $OUT_FILE"
if [ "$ITEM_COUNT" -eq 0 ]; then
    echo "[error] zero items scraped - not committing empty file" >&2
    exit 1
fi
if [ "$ITEM_COUNT" -lt 1600 ]; then
    echo "[warn] only $ITEM_COUNT items (floor 1600) - possible partial block" >&2
fi

# Narrow path only: never a shared directory (Sep 2026 wipeout).
bash scripts/git_commit_push.sh "scrape(onepc): $TODAY ($ITEM_COUNT items)" "data/raw/$TODAY/onepc.jsonl"

mkdir -p "$STATE_DIR"
touch "$SUCCESS_MARKER"
find "$STATE_DIR" -name 'onepc-*.success' -type f -mtime +14 -delete
