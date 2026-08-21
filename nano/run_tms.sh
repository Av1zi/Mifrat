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

for attempt in 1 2 3; do
    if git push; then
        echo "[run_tms] pushed successfully"
        break
    fi
    echo "[warn] push failed (attempt $attempt), retrying..." >&2
    sleep $((RANDOM % 15 + 5))
    git pull --rebase
done
