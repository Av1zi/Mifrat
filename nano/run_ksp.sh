#!/usr/bin/env bash
# KSP listing scrape on the Nano. KSP's Cloudflare edge blocks datacenter IPs
# and plain TLS clients, so this runs from the home connection only, after the
# TMS/1PC windows. Regular prices publish first; Eilat/covers are optional.
# The separate detail timer shares the same blocked-night state.
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
source "$REPO_DIR/nano/run_state.sh"
nano_lock
# The scrape night (scraper/night.py), pinned for run_spider.py below so the
# file it writes is the one committed here.
TODAY="$("$PYTHON" "$REPO_DIR/scraper/night.py")"
export MIFRAT_NIGHT="$TODAY"
ksp_pause_paths
OUT_FILE="$REPO_DIR/data/raw/$TODAY/ksp.jsonl"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
SUCCESS_MARKER="$STATE_DIR/ksp-$TODAY.success"
ATTEMPT_MARKER="$STATE_DIR/ksp-$TODAY.attempted"
VALID_MARKER="$STATE_DIR/ksp-$TODAY.validated"
# 80% of the 2026-10-30 baseline (1,087). run_spider also warns below 800;
# the spider itself refuses a short run, so this is a second, post-hoc gate.
MIN_ITEMS=800

if ! timedatectl status | grep -q "synchronized: yes"; then
    echo "[warn] system clock not NTP-synchronized" >&2
fi

cd "$REPO_DIR"
if ! "$PYTHON" scraper/ksp_schedule.py ready; then
    echo "[run_ksp] recovery date has not arrived; no requests tonight"
    exit 0
fi

if ksp_blocked; then
    echo "[error] ksp blocked earlier tonight; leaving it alone" >&2
    exit 3
fi
if [ -f "$SUCCESS_MARKER" ]; then
    echo "[run_ksp] regular snapshot already pushed tonight; no second crawl"
    exit 0
fi
if [ -f "$ATTEMPT_MARKER" ] && [ ! -f "$VALID_MARKER" ]; then
    echo "[error] KSP already attempted tonight without a validated snapshot; no retry" >&2
    exit 1
fi
if [ ! -f "$VALID_MARKER" ]; then
    # Never autostash/drop unrelated work or abort an unfamiliar rebase.
    if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || \
       [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
        echo "[error] Nano checkout is not clean; refusing pull/crawl" >&2
        exit 1
    fi
    echo "[run_ksp] updating checkout..."
    git pull --ff-only
    echo "[run_ksp] code revision: $(git rev-parse --short HEAD)"
    touch "$ATTEMPT_MARKER"
    export MIFRAT_CRAWL_RESULT="$STATE_DIR/ksp-$TODAY.listing.json"
    CRAWL_STATUS=0
    "$PYTHON" scraper/run_spider.py ksp || CRAWL_STATUS=$?
    if [ "$CRAWL_STATUS" -eq 3 ]; then ksp_mark_blocked; exit 3; fi
    [ "$CRAWL_STATUS" -eq 0 ] || exit 1
else
    echo "[run_ksp] retrying publication of the validated snapshot, not crawling"
fi

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
touch "$VALID_MARKER"

REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh \
    "ksp snapshot $TODAY ($ITEM_COUNT items)" \
    "data/raw/$TODAY/ksp.jsonl"

mkdir -p "$STATE_DIR"
touch "$SUCCESS_MARKER"

# Eilat prices (scraper/eilat.py): KSP's live-price call for tonight's uins.
# Best-effort, like the covers below: the regular snapshot is already pushed,
# and a missed Eilat night only stale-forwards the Eilat prices. A block
# still stops here (no covers either), as the home-IP rules require.
# New listing transport already captures current Eilat prices. Do not call
# the rejected legacy Eilat endpoint during recovery.
echo "[run_ksp] legacy Eilat phase disabled during stream recovery"

# Cover backfill (best-effort; the snapshot is already pushed and the success
# marker written). KSP's image host shares the Cloudflare edge with the API:
# home IP only, 6s between downloads, first 403/429 stops all phases. It reads the catalog CI
# built from the PREVIOUS snapshot, so a new product gets its cover a day late.
if ! "$PYTHON" -c "import PIL, requests" 2>/dev/null; then
    echo "[warn] Pillow/requests missing in Nano venv — skipping KSP covers. Run: $PYTHON -m pip install -r $REPO_DIR/requirements.txt" >&2
elif [ ! -f data/catalog.json ]; then
    echo "[warn] no data/catalog.json — skipping KSP covers" >&2
else
    echo "[run_ksp] downloading KSP covers..."
    export MIFRAT_CRAWL_RESULT="$STATE_DIR/ksp-$TODAY.covers.json"
    COVER_STATUS=0
    "$PYTHON" -m scraper.download_images --from-catalog --vendor ksp \
        --limit 300 --sleep 6 || COVER_STATUS=$?
    if [ "$COVER_STATUS" -eq 3 ]; then ksp_mark_blocked; fi
    if [ -d data/images/ksp ]; then
        REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh "ksp covers $TODAY" "data/images/ksp/" || COVER_STATUS=1
    fi
    if ksp_blocked; then
        bash nano/ops_notify.sh pc-parts-il-ksp.service "" covers failed || true
        exit 3
    elif [ "$COVER_STATUS" -ne 0 ]; then
        bash nano/ops_notify.sh pc-parts-il-ksp.service "" covers failed || true
        echo "[warn] KSP cover step failed — snapshot already pushed" >&2
    else
        bash nano/ops_notify.sh pc-parts-il-ksp.service success covers || true
    fi
fi
find "$STATE_DIR" -name 'ksp-*.success' -type f -mtime +14 -delete
echo "[run_ksp] done at $(date -Iseconds)"
