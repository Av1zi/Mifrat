#!/usr/bin/env bash
# Shared checkout lock and KSP's credential-free per-night state.
# Source after REPO_DIR/PYTHON are set; child Eilat runs inherit the lock.
nano_lock() {
    STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
    mkdir -p "$STATE_DIR"
    exec 9>"$STATE_DIR/checkout.lock"
    if ! flock -w 300 9; then
        echo "[error] another Nano job holds the checkout lock; no crawl started" >&2
        return 1
    fi
    export MIFRAT_CHECKOUT_LOCK=1
}

ksp_blocked() {
    [ -f "$STATE_DIR/ksp-$TODAY.blocked" ] || [ -f "$STATE_DIR/ksp.paused" ]
}

ksp_mark_blocked() {
    touch "$STATE_DIR/ksp-$TODAY.blocked"
    touch "$STATE_DIR/ksp.paused"
    echo "[error] ksp blocked; paused until the owner reviews/resumes it" >&2
}

ksp_pause_paths() {
    export MIFRAT_VENDOR_PAUSE="$STATE_DIR/ksp.paused"
    export MIFRAT_NIGHT_BLOCK="$STATE_DIR/ksp-$TODAY.blocked"
}
