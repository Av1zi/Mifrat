#!/usr/bin/env bash
# Fetch the spec sources that answer an honestly identified client from the
# Nano's home IP but not from the cloud: LDLC (xref). Polite (1 req/s, cached), identified as MifratSpecBot; a 403/429
# stops that source and nothing retries. Commits only the files it wrote.
#
#   bash nano/run_xref.sh
set -euo pipefail

REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
WHAT="${1:-all}"

cd "$REPO_DIR"
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    git rebase --abort || true
fi
git pull --rebase --autostash
echo "[run_xref] code revision: $(git rev-parse --short HEAD)"

paths=()
if [ "$WHAT" = "all" ] || [ "$WHAT" = "ldlc" ]; then
    "$PYTHON" -m scraper.xref ldlc || echo "[run_xref] ldlc stopped (exit $?)" >&2
    for f in data/xref/ldlc/*.json; do [ -e "$f" ] && paths+=("$f"); done
fi
existing=()
for path in "${paths[@]}"; do [ -e "$path" ] && existing+=("$path"); done
if [ "${#existing[@]}" -eq 0 ]; then
    echo "[run_xref] nothing written"
    exit 0
fi
bash scripts/git_commit_push.sh "xref: LDLC from the Nano for $(date +%F)" "${existing[@]}"
