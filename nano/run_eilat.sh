#!/usr/bin/env bash
# Eilat-price crawl for one home vendor (scraper/eilat.py): tms or ksp.
#
#   nano/run_eilat.sh tms    # TMS category pages in Eilat mode
#   nano/run_eilat.sh ksp    # KSP live prices for tonight's KSP snapshot
#
# A second, separate crawl of the vendor, written to
# data/raw/<night>/<vendor>_eilat.jsonl. Called by run_tms.sh / run_ksp.sh
# right after the vendor's regular snapshot is pushed, so it runs inside that
# vendor's own night slot and unit (same timer, timeout and phone alert) and
# under the same rules (one request at a time, a 403/429 ends the run). A
# failure here never touches the regular snapshot: normalize stale-forwards
# the last Eilat file and marks those prices stale.
set -euo pipefail

VENDOR="${1:-}"
case "$VENDOR" in
    tms|ksp) ;;
    *) echo "usage: run_eilat.sh tms|ksp" >&2; exit 2 ;;
esac
SPIDER="${VENDOR}_eilat"

REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
TODAY="${MIFRAT_NIGHT:-$("$PYTHON" "$REPO_DIR/scraper/night.py")}"
export MIFRAT_NIGHT="$TODAY"
OUT_FILE="$REPO_DIR/data/raw/$TODAY/$SPIDER.jsonl"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
SUCCESS_MARKER="$STATE_DIR/$SPIDER-$TODAY.success"
VALID_MARKER="$STATE_DIR/$SPIDER-$TODAY.validated"

cd "$REPO_DIR"
source "$REPO_DIR/nano/run_state.sh"
if [ "${MIFRAT_CHECKOUT_LOCK:-0}" != 1 ]; then nano_lock; fi
if [ "$VENDOR" = ksp ]; then ksp_pause_paths; fi
mkdir -p "$STATE_DIR"
if [ "$VENDOR" = "ksp" ] && ksp_blocked; then exit 3; fi
ATTEMPT_MARKER="$STATE_DIR/$SPIDER-$TODAY.attempted"

# One Eilat crawl per night (same rule as the regular crawls).
if [ -f "$SUCCESS_MARKER" ] && [ "${RUN_EILAT_FORCE:-0}" != "1" ]; then
    echo "[run_eilat] $SPIDER already pushed tonight ($SUCCESS_MARKER)"
    exit 0
fi
if [ -f "$ATTEMPT_MARKER" ]; then
    if [ -f "$VALID_MARKER" ] && [ -s "$OUT_FILE" ]; then
        REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh "$SPIDER publication retry $TODAY" "data/raw/$TODAY/$SPIDER.jsonl"
        touch "$SUCCESS_MARKER"
        bash nano/ops_notify.sh "pc-parts-il-$VENDOR.service" success eilat || true
        exit 0
    fi
    echo "[error] $SPIDER already attempted tonight; no second crawl" >&2
    exit 1
fi

# No `git pull` here: the caller (run_tms.sh / run_ksp.sh) has just updated
# the checkout, and its own commits may still be waiting to be pushed.
echo "[run_eilat] code revision: $(git rev-parse --short HEAD)"

if [ "$VENDOR" = "ksp" ] && [ ! -s "data/raw/$TODAY/ksp.jsonl" ]; then
    # The KSP Eilat crawl asks for tonight's KSP uins; without them there is
    # nothing to ask (normalize keeps the last Eilat file, marked stale).
    echo "[run_eilat] no data/raw/$TODAY/ksp.jsonl yet — skipping $SPIDER" >&2
    exit 1
fi

echo "[run_eilat] starting $SPIDER at $(date -Iseconds)"
touch "$ATTEMPT_MARKER"
export MIFRAT_CRAWL_RESULT="$STATE_DIR/$VENDOR-$TODAY.eilat.json"
SPIDER_STATUS=0
# run_spider prints "wrote N items"; rename it so the unit's last "N items"
# line (ops_notify.sh) stays the regular crawl's.
"$PYTHON" scraper/run_spider.py "$SPIDER" 2>&1 \
    | sed -E 's/([0-9]+) items/\1 Eilat rows/g' || SPIDER_STATUS=$?
# Exit 3 tells the caller the vendor blocked us (Scraping rules, rule 6):
# the caller stops all further requests to that vendor tonight.
if [ "$SPIDER_STATUS" -eq 3 ]; then
    if [ "$VENDOR" = "ksp" ]; then ksp_mark_blocked; fi
    bash nano/ops_notify.sh "pc-parts-il-$VENDOR.service" "" eilat failed || true
    echo "[error] $VENDOR blocked the $SPIDER crawl — stopping" >&2
    exit 3
fi
if [ "$SPIDER_STATUS" -ne 0 ] || [ ! -f "$OUT_FILE" ]; then
    bash nano/ops_notify.sh "pc-parts-il-$VENDOR.service" "" eilat failed || true
    echo "[error] no snapshot at $OUT_FILE — not committing" >&2
    exit 1
fi
ROW_COUNT="$(wc -l < "$OUT_FILE")"
# Never "N items" in this log: ops_notify.sh reports the unit's last
# "N items" line, which must stay the regular crawl's count.
echo "[run_eilat] spider done — $ROW_COUNT Eilat rows in $OUT_FILE"
touch "$VALID_MARKER"

REQUIRE_CLEAN_TREE=1 bash scripts/git_commit_push.sh \
    "$SPIDER snapshot $TODAY ($ROW_COUNT Eilat rows)" \
    "data/raw/$TODAY/$SPIDER.jsonl" || {
        bash nano/ops_notify.sh "pc-parts-il-$VENDOR.service" "" eilat failed || true
        exit 1
    }

mkdir -p "$STATE_DIR"
touch "$SUCCESS_MARKER"
bash nano/ops_notify.sh "pc-parts-il-$VENDOR.service" success eilat || true
find "$STATE_DIR" -name "$SPIDER-*.success" -type f -mtime +14 -delete
echo "[run_eilat] done at $(date -Iseconds)"
