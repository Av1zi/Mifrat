#!/usr/bin/env bash
# Runs the TMS spider once, writes output to data/raw/YYYY-MM-DD/tms.jsonl,
# then commits and pushes to GitHub.
# Called by pc-parts-il-tms.service — do not run as root.

set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
CONDA_SH="/home/avizi/miniforge3/etc/profile.d/conda.sh"
ENV_NAME="pc-parts-il"
TODAY="$(date +%F)"
OUT_DIR="$REPO_DIR/data/raw/$TODAY"
OUT_FILE="$OUT_DIR/tms.jsonl"

# Warn if NTP is not synced — wrong dates poison the daily history.
if ! timedatectl status | grep -q "synchronized: yes"; then
    echo "[warn] system clock not NTP-synchronized — date on output may be wrong" >&2
fi

# Activate the conda environment.
# shellcheck source=/dev/null
source "$CONDA_SH"
conda activate "$ENV_NAME"

cd "$REPO_DIR"

# Make sure we're up to date before writing anything.
git pull --rebase --autostash

mkdir -p "$OUT_DIR"

echo "[run_tms] starting spider at $(date -Iseconds)"
scrapy crawl tms -o "$OUT_FILE" -t jsonl

ITEM_COUNT="$(wc -l < "$OUT_FILE")"
echo "[run_tms] spider done — $ITEM_COUNT items written to $OUT_FILE"

# Fail loudly if we got nothing — catches a broken spider silently returning
# zero results (§10).
if [ "$ITEM_COUNT" -eq 0 ]; then
    echo "[error] zero items scraped — not committing empty file" >&2
    exit 1
fi

# Commit and push.
git add "data/raw/$TODAY/tms.jsonl"
git diff --cached --quiet || git commit -m "tms snapshot $TODAY ($ITEM_COUNT items)"

# Rebase-and-retry with jitter in case the Actions job pushed at the same
# time (§10 — git push conflicts between the two writers).
for attempt in 1 2 3; do
    if git push; then
        echo "[run_tms] pushed successfully"
        break
    fi
    echo "[warn] push failed (attempt $attempt), pulling and retrying..." >&2
    sleep $((RANDOM % 15 + 5))
    git pull --rebase
done
