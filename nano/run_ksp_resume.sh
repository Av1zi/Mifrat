#!/usr/bin/env bash
# One owner-approved recovery attempt, never an immediate retry of a block.
set -euo pipefail
REPO_DIR="/home/avizi/pc-parts-il"
PYTHON="/home/avizi/miniforge3/envs/pc-parts-il/bin/python"
source "$REPO_DIR/nano/run_state.sh"
nano_lock
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
mkdir -p "$STATE_DIR"
cd "$REPO_DIR"
if ! "$PYTHON" scraper/ksp_schedule.py ready; then
    echo "[ksp-resume] not due; no requests"
    exit 1
fi
# No daytime catch-up or arbitrary systemctl start outside the night window.
HOUR="$(date -u +%H)"
HOUR=$((10#$HOUR))
if [ "$HOUR" -ge 4 ] && [ "$HOUR" -lt 21 ]; then
    echo "[ksp-resume] outside night window; no requests"
    exit 1
fi
exec 8>"$STATE_DIR/resume.lock"
flock -w 60 8
if [ -f "$STATE_DIR/ksp-resume.attempted" ]; then
    echo "[ksp-resume] recovery already attempted; no automatic unblock"
    exit 1
fi
# State first: a crash cannot lead to repeated unblocking.
touch "$STATE_DIR/ksp-resume.attempted"
rm -f "$STATE_DIR/ksp.paused"
STATUS=0
bash nano/run_ksp.sh || STATUS=$?
if [ "$STATUS" -ne 0 ]; then
    touch "$STATE_DIR/ksp.paused"
    echo "[ksp-resume] recovery failed; paused, daily timer stays disabled"
fi
exit "$STATUS"
