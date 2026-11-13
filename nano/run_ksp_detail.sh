#!/usr/bin/env bash
# KSP detail scrape on the Nano (home IP only; docs/ksp-detail-plan.md Phase 2).
# Reads the maker part number from KSP's item JSON for a bounded chunk of
# uins a night, KSP-only products first. Runs after the night's KSP listing
# run (03:00 UTC timer) and only when that run succeeded, so the prices are
# already pushed and a block here never costs them.
# Rules: one request at a time, 3-9s apart (spiders/ksp_detail.py), stop on
# the first 403/429, never retry against a block, no second run the same day.
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
SCRAPY="/home/avizi/miniforge3/envs/pc-parts-il/bin/scrapy"
TODAY="$(date -u +%F)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
DONE_MARKER="$STATE_DIR/ksp-detail-$TODAY.done"
# Written by run_ksp.sh once tonight's listing snapshot is pushed.
LISTING_MARKER="$STATE_DIR/ksp-$TODAY.success"
DETAIL_FILE="data/raw/detail/ksp.jsonl"
# 150 uins at ~6s is ~15 minutes; the whole KSP catalog (~900) takes a week.
KSP_DETAIL_LIMIT="${KSP_DETAIL_LIMIT:-150}"

cd "$REPO_DIR"
mkdir -p "$STATE_DIR"

if [ -f "$DONE_MARKER" ]; then
    echo "[run_ksp_detail] already ran today ($DONE_MARKER) - one run per day"
    exit 0
fi
# Never on top of the listing run, and never after a night KSP refused it:
# no success marker means blocked, failed, or still running.
if systemctl is-active --quiet pc-parts-il-ksp.service; then
    echo "[run_ksp_detail] KSP listing run still active - skipping tonight"
    exit 0
fi
if [ ! -f "$LISTING_MARKER" ] && [ "${KSP_DETAIL_FORCE:-0}" != "1" ]; then
    echo "[run_ksp_detail] no KSP listing success tonight ($LISTING_MARKER) -" \
         "skipping, so a block is not followed by more requests"
    exit 0
fi
# Mark BEFORE the crawl: a crash or a block must not lead to a retry today.
touch "$DONE_MARKER"

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    echo "[warn] stale rebase state found - aborting it to recover" >&2
    git rebase --abort || true
fi
git pull --rebase --autostash
echo "[run_ksp_detail] code revision: $(git rev-parse --short HEAD)"

"$PYTHON" -m scraper.make_detail_pending make ksp --limit "$KSP_DETAIL_LIMIT"
PENDING_COUNT=$("$PYTHON" -c "import json; print(len(json.load(open('data/detail_pending/ksp.json'))))" 2>/dev/null || echo 0)
if [ "$PENDING_COUNT" -eq 0 ]; then
    echo "[run_ksp_detail] nothing pending"
    exit 0
fi

echo "[run_ksp_detail] fetching $PENDING_COUNT KSP item pages at $(date -Iseconds)"
mkdir -p "$(dirname "$DETAIL_FILE")"
# `-o` APPENDS (never -O): the committed file is the accumulated corpus.
CRAWL_OK=1
"$SCRAPY" crawl ksp_detail -o "$DETAIL_FILE:jsonlines" || CRAWL_OK=0

# Whatever arrived before a block is kept: mark it and publish it.
"$PYTHON" -m scraper.make_detail_pending mark ksp
bash scripts/git_commit_push.sh "ksp detail $TODAY" \
    data/detail_pending/ksp.json data/detail_scraped/ksp.json "$DETAIL_FILE"

find "$STATE_DIR" -name 'ksp-detail-*.done' -type f -mtime +14 -delete
if [ "$CRAWL_OK" -eq 0 ]; then
    echo "[error] ksp_detail stopped early (block or crash) - rows so far are pushed;" \
         "check the journal before tomorrow's run" >&2
    exit 1
fi
echo "[run_ksp_detail] done at $(date -Iseconds)"
