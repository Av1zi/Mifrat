#!/usr/bin/env bash
# Install delayed KSP recovery; no crawler execution, no credential reads.
# Run as the normal Nano user from the updated checkout, not with sudo bash.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$HOME/miniforge3/envs/pc-parts-il/bin/python"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
if [ "$ROOT" != /home/avizi/pc-parts-il ]; then
    echo '[error] Units target /home/avizi/pc-parts-il; refusing a different checkout' >&2
    exit 1
fi
mkdir -p "$STATE"
exec 9>"$STATE/checkout.lock"
flock -w 300 9
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo '[error] Checkout has uncommitted work; update safely before installing' >&2
    exit 1
fi
if [ -f "$STATE/ksp-resume.attempted" ]; then
    echo '[error] Recovery has already been attempted; owner review needed before rescheduling' >&2
    exit 1
fi
"$PYTHON" "$ROOT/scripts/check_ksp_stream.py"
"$PYTHON" "$ROOT/scripts/check_ksp_stream_spider.py"
touch "$STATE/ksp.paused"
sudo systemctl disable --now pc-parts-il-ksp.timer pc-parts-il-ksp-detail.timer
# Install only the KSP units requested here; unrelated/custom units untouched.
for name in pc-parts-il-ksp.service pc-parts-il-ksp.timer \
            pc-parts-il-ksp-resume.service pc-parts-il-ksp-resume.timer; do
    sudo install -m 644 "$ROOT/nano/$name" "/etc/systemd/system/$name"
done
sudo systemctl daemon-reload
sudo systemctl enable --now pc-parts-il-ksp-resume.timer
systemctl list-timers --all pc-parts-il-ksp-resume.timer
echo '[ksp-recovery] Armed future attempt only; no crawler was started. Detail stays disabled.'
