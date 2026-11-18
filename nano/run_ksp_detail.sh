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
source "$REPO_DIR/nano/run_state.sh"
nano_lock
# The scrape night, the date run_ksp.sh keys its success marker by.
TODAY="$("$PYTHON" "$REPO_DIR/scraper/night.py")"
export MIFRAT_NIGHT="$TODAY"
ksp_pause_paths
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
DONE_MARKER="$STATE_DIR/ksp-detail-$TODAY.done"
READY_MARKER="$STATE_DIR/ksp-detail-$TODAY.ready"
PUSH_MARKER="$STATE_DIR/ksp-detail-$TODAY.pushed"
# Written by run_ksp.sh once tonight's listing snapshot is pushed.
LISTING_MARKER="$STATE_DIR/ksp-$TODAY.success"
DETAIL_FILE="data/raw/detail/ksp.jsonl"
# 150 uins at ~6s is ~15 minutes; the whole KSP catalog (~900) takes a week.
KSP_DETAIL_LIMIT="${KSP_DETAIL_LIMIT:-150}"

cd "$REPO_DIR"
mkdir -p "$STATE_DIR"

if ksp_blocked; then
    if [ -f "$READY_MARKER" ] && [ ! -f "$PUSH_MARKER" ]; then
        REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh "ksp detail $TODAY" \
            data/detail_pending/ksp.json data/detail_scraped/ksp.json "$DETAIL_FILE"
        touch "$PUSH_MARKER"
    fi
    echo "[error] ksp blocked earlier tonight; detail must not run" >&2
    exit 3
fi
if [ -f "$DONE_MARKER" ]; then
    if [ -f "$READY_MARKER" ] && [ ! -f "$PUSH_MARKER" ]; then
        REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh "ksp detail $TODAY" \
            data/detail_pending/ksp.json data/detail_scraped/ksp.json "$DETAIL_FILE"
        touch "$PUSH_MARKER"
        echo "[run_ksp_detail] retained detail rows pushed; no crawl"
    fi
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
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || \
   [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    echo "[error] Nano checkout is not clean; refusing detail pull/crawl" >&2
    exit 1
fi
git pull --ff-only
echo "[run_ksp_detail] code revision: $(git rev-parse --short HEAD)"

"$PYTHON" -m scraper.make_detail_pending make ksp --limit "$KSP_DETAIL_LIMIT"
PENDING_COUNT=$("$PYTHON" -c "import json; print(len(json.load(open('data/detail_pending/ksp.json'))))" 2>/dev/null || echo 0)
if [ "$PENDING_COUNT" -eq 0 ]; then
    # The pending builder may have changed its ledger even when no requests
    # are needed. Publish that narrow output, never leave it to be discarded.
    REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh "ksp detail queue $TODAY" data/detail_pending/ksp.json
    echo "[run_ksp_detail] nothing pending"
    exit 0
fi

# Mark only when a crawl actually starts, not when pull/queue setup fails.
# A crash or block after this point must not lead to another crawl tonight.
touch "$DONE_MARKER"
echo "[run_ksp_detail] fetching $PENDING_COUNT KSP item pages at $(date -Iseconds)"
mkdir -p "$(dirname "$DETAIL_FILE")"
# Runner APPENDS: the committed file is the accumulated corpus.
CRAWL_STATUS=0
export MIFRAT_CRAWL_RESULT="$STATE_DIR/ksp-$TODAY.detail.json"
"$PYTHON" scraper/run_ksp_detail.py || CRAWL_STATUS=$?
if [ "$CRAWL_STATUS" -eq 3 ]; then ksp_mark_blocked; fi

# Whatever arrived before a block is kept: mark it and publish it.
"$PYTHON" -m scraper.make_detail_pending mark ksp
touch "$READY_MARKER"
REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh "ksp detail $TODAY" \
    data/detail_pending/ksp.json data/detail_scraped/ksp.json "$DETAIL_FILE"
touch "$PUSH_MARKER"

find "$STATE_DIR" -name 'ksp-detail-*.done' -type f -mtime +14 -delete
if [ "$CRAWL_STATUS" -ne 0 ]; then
    echo "[error] ksp_detail stopped early (block or crash) - rows so far are pushed;" \
         "check the journal before tomorrow's run" >&2
    exit "$CRAWL_STATUS"
fi
echo "[run_ksp_detail] done at $(date -Iseconds)"
