#!/usr/bin/env bash
# Verified AI extraction (scraper/extract) on the Nano: reads GOOGLE_KEY from the
# gitignored .env at the repo root. Answers are cached on the Nano
# (data/extract/.cache), so a daily run only pays for listings whose text
# changed; a free-tier 429/503 stops the run and the next one continues.
#
#   bash nano/run_extract.sh             # fill (daily)
#   AUDIT=300 bash nano/run_extract.sh   # first: measure accuracy on 300 products
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"

cd "$REPO_DIR"
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    git rebase --abort || true
fi
git pull --rebase --autostash
echo "[run_extract] code revision: $(git rev-parse --short HEAD)"

[ -f .env ] || { echo "[run_extract] no .env in $REPO_DIR (see nano/NANO_README.md)" >&2; exit 1; }

daily_spent=0
if [ -n "${AUDIT:-}" ]; then
    code=0; "$PYTHON" -m scraper.extract --audit "$AUDIT" || code=$?
    [ "$code" -eq 3 ] && daily_spent=1
    [ "$code" -ne 0 ] && echo "[run_extract] audit stopped early (exit $code)" >&2
fi
if [ "$daily_spent" -eq 0 ]; then
    code=0; "$PYTHON" -m scraper.extract || code=$?
    [ "$code" -ne 0 ] && echo "[run_extract] fill stopped early (exit $code)" >&2
else
    echo "[run_extract] per-day quota spent; skipping the fill until tomorrow" >&2
fi

files=()
for f in data/extract/products.json data/extract/trust.json; do [ -f "$f" ] && files+=("$f"); done
if [ "${#files[@]}" -eq 0 ]; then
    echo "[run_extract] nothing written"
    exit 0
fi
bash scripts/git_commit_push.sh "extract: verified spec facts from the Nano for $(date +%F)" "${files[@]}"
