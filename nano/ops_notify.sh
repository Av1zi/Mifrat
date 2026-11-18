#!/usr/bin/env bash
# Report a Nano scrape run to the Mifrat Worker (POST /api/ops/event), which
# stores it and pushes an alert to the owner's phone (ntfy) when it failed.
#
#   nano/ops_notify.sh <unit>            # OnFailure= (pc-parts-il-notify@.service)
#   nano/ops_notify.sh <unit> success    # ExecStartPost= of the scrape unit
#
# systemd 237 (Jetson Nano, Ubuntu 18.04) has no OnSuccess=, so a successful
# run reports from ExecStartPost (it only runs when ExecStart exited 0) and a
# failed one from OnFailure=. For a failure the script reads
# the unit's last run from the journal, classifies it, and sends ONE event:
#   blocked  the spider stopped on HTTP 403/429 or a challenge page
#            (Scraping rules: a block is a stop signal; the owner decides)
#   partial  the run refused a short crawl (floor / incomplete category)
#   failed   anything else (push failure, crash, timeout)
#   ok       success
#
# Config (never in git): ~/.config/pc-parts-il/notify.env, chmod 600:
#   OPS_EVENT_URL=https://mifrat.avizi.workers.dev/api/ops/event
#   OPS_INGEST_TOKEN=<same value as the Worker secret>
#   NTFY_TOPIC_URL=https://ntfy.sh/<topic>   # fallback when the Worker is down
#   NTFY_TOKEN=tk_...                         # optional
# The file is read as KEY=VALUE text, never run as shell code: only the four
# keys above are taken, one pair of surrounding quotes is stripped, and
# nothing in a value ($(...), backticks, ;) is ever evaluated.
# Missing config = log and exit 0: notifications must never break a scrape.
set -uo pipefail

UNIT="${1:-}"
MODE="${2:-}"
PHASE_RESULT="${4:-}"
PHASE="${3:-listing}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/pc-parts-il/notify.env"
if [ -z "$UNIT" ]; then
    echo "usage: ops_notify.sh <systemd unit>" >&2
    exit 0
fi
if [ ! -r "$CONF" ]; then
    echo "[ops_notify] no $CONF - skipping" >&2
    exit 0
fi
OPS_EVENT_URL=""
OPS_INGEST_TOKEN=""
NTFY_TOPIC_URL=""
NTFY_TOKEN=""
while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in ''|'#'*) continue ;; esac
    line="${line#export }"
    key="${line%%=*}"
    [ "$key" = "$line" ] && continue
    value="${line#*=}"
    value="${value%"${value##*[![:space:]]}"}"
    if [ "${#value}" -ge 2 ]; then
        first="${value:0:1}"; last="${value: -1}"
        if { [ "$first" = "'" ] || [ "$first" = '"' ]; } && [ "$first" = "$last" ]; then
            value="${value:1:${#value}-2}"
        fi
    fi
    case "$key" in
        OPS_EVENT_URL) OPS_EVENT_URL="$value" ;;
        OPS_INGEST_TOKEN) OPS_INGEST_TOKEN="$value" ;;
        NTFY_TOPIC_URL) NTFY_TOPIC_URL="$value" ;;
        NTFY_TOKEN) NTFY_TOKEN="$value" ;;
    esac
done < "$CONF"

# pc-parts-il-tms-fallback.service -> tms
VENDOR="$(echo "$UNIT" | sed -E 's/^pc-parts-il-//; s/(-fallback)?\.service$//')"
if [ "$VENDOR" = "ksp-detail" ]; then VENDOR=ksp; PHASE=detail; fi
if [ "$VENDOR" = "ksp-resume" ]; then VENDOR=ksp; fi
case "$VENDOR" in
    tms|onepc|ksp) ;;
    *) echo "[ops_notify] $UNIT is not a scrape unit - skipping" >&2; exit 0 ;;
esac
case "$PHASE" in listing|eilat|detail|covers) ;; *) exit 0 ;; esac
BASE_VENDOR="$VENDOR"
if [ "$PHASE" != listing ]; then VENDOR="${VENDOR}_$PHASE"; fi

if [ "$MODE" = "success" ]; then
    RESULT="success"
else
    RESULT="$(systemctl show -p Result --value "$UNIT" 2>/dev/null || echo unknown)"
    [ "$RESULT" = "success" ] && RESULT="failed"   # OnFailure= fired: it failed
fi
if [ -n "$PHASE_RESULT" ]; then RESULT="$PHASE_RESULT"; fi

# The last invocation's log only (journalctl _SYSTEMD_INVOCATION_ID).
INVOCATION="$(systemctl show -p InvocationID --value "$UNIT" 2>/dev/null || true)"
if [ -n "$INVOCATION" ]; then
    LOG="$(journalctl -q -o cat _SYSTEMD_INVOCATION_ID="$INVOCATION" 2>/dev/null | tail -n 400)"
else
    LOG="$(journalctl -q -o cat -u "$UNIT" --since '-2h' 2>/dev/null | tail -n 400)"
fi

# Item count the run scripts print ("... 2291 items written ...").
ITEMS="$(echo "$LOG" | grep -oE '[0-9]+ items' | tail -n 1 | grep -oE '[0-9]+' || true)"

if [ "$RESULT" = "success" ]; then
    OUTCOME="ok"
    DETAIL=""
elif echo "$LOG" | grep -qiE 'blocked_[0-9]+x|ksp.*blocked|cf-mitigated|captcha|ddos protection'; then
    OUTCOME="blocked"
    DETAIL="$(echo "$LOG" | grep -iE 'blocked|403|429|captcha|challenge' | tail -n 1)"
elif echo "$LOG" | grep -qiE 'incomplete|floor|partial run|zero items'; then
    OUTCOME="partial"
    DETAIL="$(echo "$LOG" | grep -iE 'incomplete|floor|partial|zero items' | tail -n 1)"
else
    OUTCOME="failed"
    DETAIL="$RESULT: $(echo "$LOG" | grep -E '\[error\]|Error|Traceback' | tail -n 1)"
fi
# Prefer the current phase's structured, credential-free crawler result.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pc-parts-il"
NIGHT_PY="${OPS_NIGHT_PYTHON:-/home/avizi/miniforge3/envs/pc-parts-il/bin/python}"
NIGHT_SCRIPT="${OPS_NIGHT_SCRIPT:-/home/avizi/pc-parts-il/scraper/night.py}"
TODAY="${MIFRAT_NIGHT:-$("$NIGHT_PY" "$NIGHT_SCRIPT" 2>/dev/null || date -u +%F)}"
RESULT_FILE="$STATE_DIR/$BASE_VENDOR-$TODAY.$PHASE.json"
if [ "$PHASE" = listing ] && { [ -f "$STATE_DIR/$BASE_VENDOR-$TODAY.success" ] || [ -f "$STATE_DIR/$BASE_VENDOR-$TODAY.snapshot" ]; }; then
    OUTCOME=ok
    DETAIL="regular snapshot published"
elif [ "$PHASE" = listing ] && [ "$BASE_VENDOR" = ksp ] && [ -f "$STATE_DIR/ksp.paused" ]; then
    OUTCOME=blocked
    DETAIL="KSP remains paused after a block; owner review required"
elif [ -r "$RESULT_FILE" ]; then
    STRUCTURED="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); o=d.get("outcome"); n=d.get("items"); print(o, n if isinstance(n,int) and n>=0 else "null") if o in ("ok","blocked","failed","partial") else None' "$RESULT_FILE" 2>/dev/null || true)"
    if [ -n "$STRUCTURED" ]; then
        read -r OUTCOME ITEMS <<< "$STRUCTURED"
        DETAIL="$PHASE crawl: $OUTCOME"
        if [ "$RESULT" != success ] && [ "$OUTCOME" = ok ]; then
            OUTCOME=failed
            DETAIL="$PHASE crawled but publication/service failed ($RESULT)"
        fi
    fi
elif [ "$PHASE" != listing ] && echo "$LOG" | grep -qE '\[run_ksp_detail\] (already ran|no KSP listing|nothing pending|KSP listing run still active|detail disabled)'; then
    echo "[ops_notify] $VENDOR skipped; no successful crawl to report"
    exit 0
fi
# Journal text may include an exception's request headers. Never forward a
# line containing credential-shaped text, even to the private phone topic.
if echo "$DETAIL" | grep -qiE 'authorization|password|api[_-]?key|token[=: ]|secret|BEGIN.*PRIVATE KEY'; then
    DETAIL="$PHASE $OUTCOME ($RESULT); inspect the redacted Nano diagnostics"
fi
# One line, no secrets: drop anything URL-with-credentials shaped, cap length.
DETAIL="$(echo "$DETAIL" | tr -d '\r' | sed -E 's#https?://[^ @]*@#https://***@#g' | cut -c1-300)"

json_escape() {
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'
}
BODY="{\"vendor\":\"$VENDOR\",\"outcome\":\"$OUTCOME\",\"items\":${ITEMS:-null},\"detail\":$(printf '%s' "$DETAIL" | json_escape)}"

if [ -n "${OPS_EVENT_URL:-}" ] && [ -n "${OPS_INGEST_TOKEN:-}" ] && \
   curl -fsS --max-time 20 -X POST "$OPS_EVENT_URL" \
        -H "Authorization: Bearer $OPS_INGEST_TOKEN" \
        -H "Content-Type: application/json" \
        --data "$BODY" > /dev/null; then
    echo "[ops_notify] $VENDOR: $OUTCOME reported"
    exit 0
fi

# Worker unreachable: push straight to ntfy so a failure is never silent.
if [ "$OUTCOME" != "ok" ] && [ -n "${NTFY_TOPIC_URL:-}" ]; then
    PRIORITY=4
    [ "$OUTCOME" = "blocked" ] && PRIORITY=5
    AUTH=()
    [ -n "${NTFY_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $NTFY_TOKEN")
    curl -fsS --max-time 20 "${AUTH[@]}" \
        -H "Title: Nano: $VENDOR $OUTCOME" \
        -H "Priority: $PRIORITY" \
        -H "Tags: warning" \
        --data "${DETAIL:-$UNIT failed} (Worker unreachable, sent directly)" \
        "$NTFY_TOPIC_URL" > /dev/null \
        && echo "[ops_notify] $VENDOR: $OUTCOME pushed directly to ntfy"
fi
exit 0
