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

PENDING_COUNT=$("$PYTHON" -c "import json; print(len(json.load(open('data/detail_pending/tms.json'))))" 2>/dev/null || echo 0)
if [ "$PENDING_COUNT" -gt 0 ]; then
    echo "[run_tms] running tms_detail spider ($PENDING_COUNT pending items)..."
    mkdir -p "$DETAIL_DIR"
    "$SCRAPY" crawl tms_detail -O "$DETAIL_FILE:jsonlines"

    echo "[run_tms] downloading cover images..."
    "$PYTHON" -m scraper.download_images "$DETAIL_FILE" tms

    echo "[run_tms] marking detail-scraped items..."
    "$PYTHON" -m scraper.make_detail_pending mark tms

    git add data/detail_pending/ data/raw/detail/ data/images/ data/detail_scraped/
    git diff --cached --quiet || git commit -m "tms detail $TODAY"
else
    echo "[run_tms] no pending detail items"
fi

for attempt in 1 2 3; do
    if git push; then
        echo "[run_tms] pushed successfully"
        break
    fi
    echo "[warn] push failed (attempt $attempt), retrying..." >&2
    sleep $((RANDOM % 15 + 5))
    git pull --rebase
done
