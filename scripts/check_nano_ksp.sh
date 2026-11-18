#!/usr/bin/env bash
# Offline KSP wrapper regression. All crawls, pushes and systemd calls are
# stubs; the actual wrappers, night calculation and marker checks run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PYTHON_BIN="$(command -v python3 || command -v python)"
REPO="$TMP/repo"
STATE="$TMP/state/pc-parts-il"
mkdir -p "$REPO/nano" "$REPO/scraper" "$REPO/scripts" "$TMP/bin" "$STATE"
cp "$ROOT/nano/run_state.sh" "$REPO/nano/"
cp "$ROOT/scraper/night.py" "$REPO/scraper/"
for file in run_ksp.sh run_ksp_detail.sh; do
    sed -e "s#/home/avizi/pc-parts-il#$REPO#g" \
        -e "s#/home/avizi/miniforge3/envs/pc-parts-il/bin/python#$TMP/bin/python#g" \
        "$ROOT/nano/$file" > "$REPO/nano/$file"
done
cat > "$TMP/bin/python" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    *scraper/night.py*) exec "$REAL_PYTHON" "$@" ;;
    *scraper/ksp_schedule.py*) exit 0 ;;
    *scraper/run_spider.py*)
        echo crawl >> "$CALLS"
        mkdir -p "data/raw/$MIFRAT_NIGHT"
        if [ "${CRAWL_BLOCK:-0}" = 1 ]; then exit 3; fi
        for _ in $(seq 1 900); do echo '{"x":1}'; done > "data/raw/$MIFRAT_NIGHT/ksp.jsonl"
        exit 0 ;;
    *scraper/run_ksp_detail.py*) echo detail >> "$CALLS"; exit 0 ;;
    *scraper.download_images*) echo covers >> "$CALLS"; exit "${FAKE_COVER_STATUS:-0}" ;;
    *-m*) exit 0 ;;
    *-c*) if [[ "$*" == *detail_pending* ]]; then echo "${DETAIL_COUNT:-0}"; exit 0; fi; if [ "${COVER_PHASE:-0}" = 1 ]; then exit 0; fi; exit 1 ;;
esac
EOF
cat > "$TMP/bin/git" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = status ] && [ "${DIRTY:-0}" = 1 ]; then echo '?? unrelated'; fi
if [ "$1" = push ]; then echo push >> "$CALLS"; fi
exit 0
EOF
cat > "$TMP/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat > "$TMP/bin/timedatectl" <<'EOF'
#!/usr/bin/env bash
echo 'synchronized: yes'
EOF
cat > "$TMP/bin/flock" <<'EOF'
#!/usr/bin/env bash
exit "${LOCK_FAIL:-0}"
EOF
cat > "$REPO/scripts/git_commit_push.sh" <<'EOF'
#!/usr/bin/env bash
echo publish >> "$CALLS"
exit "${PUSH_FAIL:-0}"
EOF
cat > "$REPO/nano/run_eilat.sh" <<'EOF'
#!/usr/bin/env bash
echo eilat >> "$CALLS"
exit "${FAKE_EILAT_STATUS:-0}"
EOF
cat > "$TMP/bin/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$REPO/nano/ops_notify.sh"
chmod +x "$TMP/bin/"* "$REPO/scripts/git_commit_push.sh"
export PATH="$TMP/bin:$PATH" REAL_PYTHON="$PYTHON_BIN" CALLS="$TMP/calls"
export XDG_STATE_HOME="$TMP/state" MIFRAT_NOW=2026-11-18T01:00:00Z
fail=0
run() {
    : > "$CALLS"
    CODE=0
    bash "$REPO/nano/$1" > "$TMP/log" 2>&1 || CODE=$?
}
check() {
    if eval "$2"; then echo "[nano-ksp] ok   $1"; else
        echo "[nano-ksp] FAIL $1 (exit $CODE)"; cat "$TMP/log"; fail=1
    fi
}
run run_ksp.sh
check 'regular publish omits rejected legacy Eilat endpoint' '[ "$(tr "\n" " " < "$CALLS")" = "crawl publish " ]'
check 'validated and pushed markers' '[ -f "$STATE/ksp-2026-11-18.validated" ] && [ -f "$STATE/ksp-2026-11-18.success" ]'
run run_ksp.sh
check 'second invocation does not crawl' '[ "$CODE" = 0 ] && [ ! -s "$CALLS" ]'
rm "$STATE/ksp-2026-11-18.success"
PUSH_FAIL=1 run run_ksp.sh
check 'push failure never recrawls validated output' '[ "$CODE" = 1 ] && ! grep -q crawl "$CALLS" && [ ! -f "$STATE/ksp-2026-11-18.success" ]'
run run_ksp.sh
check 'push recovery publishes existing snapshot' '[ "$CODE" = 0 ] && ! grep -q crawl "$CALLS" && [ -f "$STATE/ksp-2026-11-18.success" ]'
rm "$STATE/ksp-2026-11-18.success"
echo '{}' > "$REPO/data/catalog.json"
COVER_PHASE=1 FAKE_COVER_STATUS=3 run run_ksp.sh
check 'cover block keeps regular publication but blocks the night' '[ "$CODE" = 3 ] && [ -f "$STATE/ksp-2026-11-18.success" ] && [ -f "$STATE/ksp-2026-11-18.blocked" ]'
KSP_DETAIL_FORCE=1 run run_ksp_detail.sh
check 'force cannot bypass blocked-night detail guard' '[ "$CODE" = 3 ] && [ ! -s "$CALLS" ]'
run run_ksp.sh
check 'blocked marker beats listing-success marker' '[ "$CODE" = 3 ] && [ ! -s "$CALLS" ]'
rm "$STATE/ksp-2026-11-18."{success,validated,attempted,blocked} "$STATE/ksp.paused"
CRAWL_BLOCK=1 run run_ksp.sh
check 'listing block marks night and starts no later phase' '[ "$CODE" = 3 ] && [ "$(cat "$CALLS")" = crawl ] && [ -f "$STATE/ksp-2026-11-18.blocked" ]'
rm "$STATE/ksp-2026-11-18.blocked"
run run_ksp.sh
check 'global pause survives the night marker' '[ "$CODE" = 3 ] && [ ! -s "$CALLS" ]'
rm "$STATE/ksp.paused"
run run_ksp.sh
check 'a failed attempt is not recrawled' '[ "$CODE" = 1 ] && [ ! -s "$CALLS" ]'
rm "$STATE/ksp-2026-11-18.attempted"
DIRTY=1 run run_ksp.sh
check 'unrelated work prevents pull/crawl' '[ "$CODE" = 1 ] && [ ! -s "$CALLS" ]'
LOCK_FAIL=1 run run_ksp.sh
check 'busy checkout starts no crawl' '[ "$CODE" = 1 ] && [ ! -s "$CALLS" ]'
touch "$STATE/ksp-2026-11-18.success"
DETAIL_COUNT=1 PUSH_FAIL=1 run run_ksp_detail.sh
check 'detail push failure retains ready output' '[ "$CODE" = 1 ] && [ -f "$STATE/ksp-detail-2026-11-18.ready" ] && [ ! -f "$STATE/ksp-detail-2026-11-18.pushed" ]'
DETAIL_COUNT=1 run run_ksp_detail.sh
check 'detail publication retry makes no requests' '[ "$CODE" = 0 ] && ! grep -q detail "$CALLS" && [ -f "$STATE/ksp-detail-2026-11-18.pushed" ]'
# The actual git helper, not a success/failure stub: a previous attempt can
# already have committed the bytes while its push failed. Rejected publication
# must still fetch/rebase/retry without making any vendor request.
cp "$ROOT/scripts/git_commit_push.sh" "$REPO/scripts/git_commit_push.sh"
cat > "$TMP/bin/git" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$CALLS"
case "$*" in
    'diff --cached --quiet') exit 0 ;;
    push) if [ ! -f "$CALLS.rejected" ]; then touch "$CALLS.rejected"; exit 1; fi ;;
    *'@{u}'*) echo origin/main ;;
esac
exit 0
EOF
rm "$STATE/ksp-2026-11-18.success"
run run_ksp.sh
check 'already committed bytes still retry a rejected push' '[ "$CODE" = 0 ] && grep -q "fetch origin" "$CALLS" && [ -f "$STATE/ksp-2026-11-18.success" ]'
# Use a real competing process on Linux. Skipping this on Git Bash is
# explicit; the stubbed busy-lock test above is not proof of contention.
if command -v /usr/bin/flock >/dev/null; then
    (
        export PATH="${PATH#*:}" # remove the fixture's stub commands
        source "$ROOT/nano/run_state.sh"
        nano_lock
        if /usr/bin/flock -n "$STATE/checkout.lock" true; then exit 1; fi
        echo '[nano-ksp] ok   actual lock excludes a competing process'
    ) || fail=1
fi
exit "$fail"
