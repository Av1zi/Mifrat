#!/usr/bin/env bash
# 1PC listing scrape on the Nano (home IP). Moved here from the cloud matrix
# 2026-10-24 after 1PC started answering datacenter runs with a CAPTCHA page.
# Same rules as TMS: 1 run/day, sequential, throttled, hard stop on blocks
# (spiders/onepc.py), never retry against a block. Detail pages stay in the
# cloud detail-scrape job.
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
SCRAPY="/home/avizi/miniforge3/envs/pc-parts-il/bin/scrapy"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
source "$REPO_DIR/nano/run_state.sh"
nano_lock
# The scrape night (scraper/night.py), not the UTC date: the 23:20 UTC (+1 h)
# timer used to name the folder by whichever UTC day the run started on, so
# 23:51 on 11-14 and 00:17 on 11-14 were two nights in one folder and the
# second overwrote the first (1PC lost 11-11, 11-13, 11-15).
TODAY="$("$PYTHON" "$REPO_DIR/scraper/night.py")"
export MIFRAT_NIGHT="$TODAY"
OUT_DIR="$REPO_DIR/data/raw/$TODAY"
OUT_FILE="$OUT_DIR/onepc.jsonl"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
SUCCESS_MARKER="$STATE_DIR/onepc-$TODAY.success"

cd "$REPO_DIR"

# The night run straddles the UTC date change, so "today's marker" can be dated
# the day before the fallback fires. Any marker younger than 18h counts.
if [ "${RUN_ONEPC_FALLBACK:-0}" = "1" ] && \
   [ -n "$(find "$STATE_DIR" -maxdepth 1 -name 'onepc-*.success' -type f -mmin -1080 2>/dev/null)" ]; then
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
# Crawl into a .part; the night's file is replaced only by a crawl at least
# as complete (a thinner fallback run never wipes a good night).
PART_FILE="$OUT_FILE.part"
rm -f "$PART_FILE"
"$SCRAPY" crawl onepc \
    -s "FEEDS={\"$PART_FILE\":{\"format\":\"jsonl\",\"encoding\":\"utf-8\",\"overwrite\":true}}"

PART_COUNT="$( [ -f "$PART_FILE" ] && wc -l < "$PART_FILE" || echo 0 )"
echo "[run_onepc] $PART_COUNT items written to $PART_FILE"
if [ "$PART_COUNT" -eq 0 ]; then
    echo "[error] zero items scraped - not committing empty file" >&2
    rm -f "$PART_FILE"
    exit 1
fi
if [ "$PART_COUNT" -lt 1600 ]; then
    echo "[warn] only $PART_COUNT items (floor 1600) - possible partial block" >&2
fi
"$PYTHON" scraper/night.py install "$PART_FILE" "$OUT_FILE"
ITEM_COUNT="$(wc -l < "$OUT_FILE")"

# Narrow path only: never a shared directory (Sep 2026 wipeout).
bash scripts/git_commit_push.sh "scrape(onepc): $TODAY ($ITEM_COUNT items)" "data/raw/$TODAY/onepc.jsonl"

mkdir -p "$STATE_DIR"
touch "$SUCCESS_MARKER"
find "$STATE_DIR" -name 'onepc-*.success' -type f -mtime +14 -delete
