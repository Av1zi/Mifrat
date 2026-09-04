#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
SCRAPY="/home/avizi/miniforge3/envs/pc-parts-il/bin/scrapy"
TODAY="$(date +%F)"
OUT_DIR="$REPO_DIR/data/raw/$TODAY"
OUT_FILE="$OUT_DIR/tms.jsonl"

if ! timedatectl status | grep -q "synchronized: yes"; then
    echo "[warn] system clock not NTP-synchronized" >&2
fi

cd "$REPO_DIR"

# Recover from a previously interrupted run (leftover rebase state blocks
# `git pull --rebase` forever — every subsequent run would die here and the
# Nano would go silently stale, as happened late Aug 2026).
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    echo "[warn] stale rebase state found — aborting it to recover" >&2
    git rebase --abort || true
fi

git pull --rebase --autostash
mkdir -p "$OUT_DIR"

echo "[run_tms] starting spider at $(date -Iseconds)"
"$SCRAPY" crawl tms \
    -s "FEEDS={\"$OUT_FILE\":{\"format\":\"jsonl\",\"encoding\":\"utf-8\"}}"

ITEM_COUNT="$(wc -l < "$OUT_FILE")"
echo "[run_tms] spider done — $ITEM_COUNT items written to $OUT_FILE"

if [ "$ITEM_COUNT" -eq 0 ]; then
    echo "[error] zero items scraped — not committing empty file" >&2
    exit 1
fi

git add "data/raw/$TODAY/tms.jsonl"
git diff --cached --quiet || git commit -m "tms snapshot $TODAY ($ITEM_COUNT items)"

# Push the snapshot FIRST, before the detail steps below. Rationale (Sep
# 2026): the detail chain needs Pillow/requests, which the Nano venv may
# not have — with `set -e`, a detail crash used to skip the push and orphan
# the snapshot commit, making the Nano look dead for days. The snapshot is
# the critical artifact; detail is a best-effort bonus.
PUSHED_SNAPSHOT=0
for attempt in 1 2 3; do
    if git push; then
        echo "[run_tms] snapshot pushed successfully"
        PUSHED_SNAPSHOT=1
        break
    fi
    echo "[warn] snapshot push failed (attempt $attempt), retrying..." >&2
    sleep $((RANDOM % 15 + 5))
    git pull --rebase || true
done
if [ "$PUSHED_SNAPSHOT" -eq 0 ]; then
    echo "[warn] snapshot push failed after 3 attempts — continuing to detail steps anyway; final push below will retry" >&2
fi

# --- Detail page scraping (specs + cover images) ---
# At ~5 new items/day, limit the initial backfill chunk to avoid
# hammering TMS from the home IP (§7). Once the ledger catches up
# with the existing catalog, this limit can be removed.
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
DETAIL_DIR="$REPO_DIR/data/raw/detail"
DETAIL_FILE="$DETAIL_DIR/tms.jsonl"

echo "[run_tms] building detail pending list..."
cd "$REPO_DIR"
"$PYTHON" -m scraper.make_detail_pending make tms --limit 50

# The detail chain needs Pillow + requests, which this lean ARM64 venv may
# not have (they were added for the cloud detail job later). A missing dep
# must SKIP detail — never fail the run (the snapshot is already pushed).
if ! "$PYTHON" -c "import PIL, requests" 2>/dev/null; then
    echo "[warn] Pillow/requests missing in Nano venv — skipping detail steps (snapshot already pushed). Run: $PYTHON -m pip install 'Pillow>=10.0' 'requests>=2.31'" >&2
    PENDING_COUNT=0
else
    PENDING_COUNT=$("$PYTHON" -c "import json; print(len(json.load(open('data/detail_pending/tms.json'))))" 2>/dev/null || echo 0)
fi
DETAIL_OK=1
if [ "$PENDING_COUNT" -gt 0 ]; then
    # Detail is best-effort: any failure here must still fall through to
    # the final push below (the snapshot is already safe upstream).
    {
    echo "[run_tms] running tms_detail spider ($PENDING_COUNT pending items)..."
    mkdir -p "$DETAIL_DIR"
    "$SCRAPY" crawl tms_detail -O "$DETAIL_FILE:jsonlines"

    echo "[run_tms] downloading cover images..."
    "$PYTHON" -m scraper.download_images "$DETAIL_FILE" tms

    echo "[run_tms] marking detail-scraped items..."
    "$PYTHON" -m scraper.make_detail_pending mark tms

    # TMS-only paths: never `git add` a shared directory here — same
    # stale-checkout deletion hazard as the cloud matrix jobs (Sep 2026).
    # Only stage paths that exist (first-ever run has no ledger/images yet).
    TMS_PATHS=()
    for p in data/detail_pending/tms.json data/raw/detail/tms.jsonl \
             data/detail_scraped/tms.json data/images/tms/; do
        if [ -e "$p" ]; then
            TMS_PATHS+=("$p")
        fi
    done
    if [ "${#TMS_PATHS[@]}" -gt 0 ]; then
        git add "${TMS_PATHS[@]}"
        git diff --cached --quiet || git commit -m "tms detail $TODAY"
    fi
    } || {
        echo "[warn] detail steps failed — snapshot already pushed, continuing to final push" >&2
        DETAIL_OK=0
    }
else
    echo "[run_tms] no pending detail items"
fi

PUSHED=0
for attempt in 1 2 3; do
    if git push; then
        echo "[run_tms] pushed successfully"
        PUSHED=1
        break
    fi
    echo "[warn] push failed (attempt $attempt), retrying..." >&2
    sleep $((RANDOM % 15 + 5))
    git pull --rebase || true
done

if [ "$PUSHED" -eq 0 ]; then
    # A silent push failure looks exactly like "the Nano stopped working"
    # (late Aug 2026). Fail loudly so the timer unit reports failed and the
    # journal shows it — and leave the commits in place for the next run.
    echo "[error] push failed after 3 attempts — commits retained locally, will retry tomorrow" >&2
    git log --oneline -3 >&2
    git status --short >&2 || true
    exit 1
fi

if [ "$DETAIL_OK" -eq 0 ]; then
    # Everything is pushed — but detail needs attention, so stay red.
    echo "[error] run finished with detail-step failures (snapshot is safe upstream)" >&2
    exit 1
fi
