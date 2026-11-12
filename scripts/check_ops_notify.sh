#!/usr/bin/env bash
# Offline test of nano/ops_notify.sh: stubs systemctl/journalctl/curl on PATH
# and checks the event it would send for each kind of run log.
#   bash scripts/check_ops_notify.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/home/.config/pc-parts-il"
cat > "$TMP/home/.config/pc-parts-il/notify.env" <<'EOF'
OPS_EVENT_URL=https://worker.example/api/ops/event
OPS_INGEST_TOKEN=test-token
NTFY_TOPIC_URL=https://ntfy.sh/test-topic
EOF

cat > "$TMP/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *Result*) echo "${FAKE_RESULT:-exit-code}" ;;
  *InvocationID*) echo "abc123" ;;
esac
EOF
cat > "$TMP/bin/journalctl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$FAKE_LOG"
EOF
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
# Record the call; fail the Worker URL when FAKE_WORKER_DOWN=1.
url="${@: -1}"
printf '%s\n' "$*" >> "$CURL_LOG"
if [ "${FAKE_WORKER_DOWN:-0}" = "1" ] && [[ "$url" == *worker.example* || "$*" == *worker.example* ]]; then exit 22; fi
exit 0
EOF
chmod +x "$TMP/bin/"*

fail=0
run() {
  local name="$1" unit="$2" mode="$3" log="$4" result="$5" want="$6"
  : > "$TMP/curl.log"
  HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/home/.config" PATH="$TMP/bin:$PATH" \
    CURL_LOG="$TMP/curl.log" FAKE_LOG="$log" FAKE_RESULT="$result" \
    FAKE_WORKER_DOWN="${WORKER_DOWN:-0}" \
    bash "$ROOT/nano/ops_notify.sh" "$unit" $mode > /dev/null 2>&1 || true
  if grep -q -- "$want" "$TMP/curl.log"; then
    echo "[ops-notify] ok   $name"
  else
    echo "[ops-notify] FAIL $name: wanted '$want' in:"; sed 's/^/    /' "$TMP/curl.log"
    fail=1
  fi
}

run "success" pc-parts-il-onepc.service success \
  "[run_onepc] 2291 items written to /x" success '"vendor":"onepc","outcome":"ok","items":2291'
run "fallback unit maps to vendor" pc-parts-il-tms-fallback.service success \
  "spider done — 2216 items written" success '"vendor":"tms","outcome":"ok"'
run "tms block" pc-parts-il-tms.service "" \
  "[tms] HTTP 403 on page 3
CloseSpider: blocked_2x" exit-code '"outcome":"blocked"'
run "ksp block" pc-parts-il-ksp.service "" \
  "[ksp] HTTP 403 cf-mitigated: challenge
ksp blocked - no snapshot written" exit-code '"outcome":"blocked"'
run "partial" pc-parts-il-ksp.service "" \
  "[ksp] category 2: 43 of 53
ksp incomplete - item floor" exit-code '"outcome":"partial"'
run "crash" pc-parts-il-onepc.service "" \
  "[error] push failed after 3 attempts" exit-code '"outcome":"failed"'
run "timeout" pc-parts-il-tms.service "" "" timeout '"outcome":"failed","items":null,"detail":"timeout'
run "bearer token sent" pc-parts-il-onepc.service success "1 items" success 'Authorization: Bearer test-token'
run "credentials scrubbed" pc-parts-il-onepc.service "" \
  "[error] fatal: https://user:ghp_secret@github.com/x" exit-code 'https://\*\*\*@github.com'
WORKER_DOWN=1 run "worker down -> ntfy direct" pc-parts-il-ksp.service "" \
  "ksp blocked - no snapshot written" exit-code 'Priority: 5'

# Never leak the secret detail when scrubbing failed.
if grep -q ghp_secret "$TMP/curl.log"; then echo "[ops-notify] FAIL secret leaked"; fail=1; fi
exit "$fail"
