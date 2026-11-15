#!/usr/bin/env bash
# Offline test of nano/run_onepc.sh's scrape-night folder and one-file-per-
# night rule (scraper/night.py). Stubs scrapy and git_commit_push.sh; the real
# python runs scraper/night.py.
#   bash scripts/check_nano_night.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PYTHON_BIN="$(command -v python3 || command -v python)"

REPO="$TMP/repo"
mkdir -p "$REPO/scraper" "$REPO/scripts" "$TMP/bin" "$TMP/state"
cp "$ROOT/scraper/night.py" "$REPO/scraper/night.py"
cat > "$REPO/scripts/git_commit_push.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PUSH_LOG"
EOF
# scrapy stub: writes FAKE_ROWS rows to the FEEDS path given with -s.
cat > "$TMP/bin/scrapy" <<'EOF'
#!/usr/bin/env bash
feeds="${@: -1}"
path="$(printf '%s' "$feeds" | sed -E 's/^FEEDS=\{"([^"]+)".*/\1/')"
: > "$path"
for _ in $(seq 1 "$FAKE_ROWS"); do echo '{"x": 1}' >> "$path"; done
EOF
cat > "$TMP/bin/git" <<'EOF'
#!/usr/bin/env bash
case "$1" in rev-parse) echo deadbeef ;; esac
exit 0
EOF
chmod +x "$TMP/bin/"* "$REPO/scripts/git_commit_push.sh"

# The script hard-codes the Nano's paths; point them at the sandbox.
sed -e "s#/home/avizi/pc-parts-il#$REPO#" \
    -e "s#/home/avizi/miniforge3/envs/pc-parts-il/bin/scrapy#$TMP/bin/scrapy#" \
    -e "s#/home/avizi/miniforge3/envs/pc-parts-il/bin/python#$PYTHON_BIN#" \
    "$ROOT/nano/run_onepc.sh" > "$TMP/run_onepc.sh"

fail=0
run() {  # name, MIFRAT_NOW, rows
  : > "$TMP/push.log"
  PATH="$TMP/bin:$PATH" XDG_STATE_HOME="$TMP/state" PUSH_LOG="$TMP/push.log" \
    MIFRAT_NOW="$2" FAKE_ROWS="$3" bash "$TMP/run_onepc.sh" > "$TMP/out.log" 2>&1 || true
}
want() {  # name, condition
  if eval "$2"; then echo "[nano-night] ok   $1"; else
    echo "[nano-night] FAIL $1"; sed 's/^/    /' "$TMP/out.log"; fail=1; fi
}
rows() { [ -f "$1" ] && wc -l < "$1" | tr -d ' ' || echo 0; }

# 2026-11-14: the 00:17 UTC run and the 23:51 UTC run are two nights.
run "early" "2026-11-14T00:17:00Z" 2000
want "00:17 UTC 11-14 -> 2026-11-14 folder" '[ "$(rows "$REPO/data/raw/2026-11-14/onepc.jsonl")" = 2000 ]'
want "pushes that night's file" 'grep -q "data/raw/2026-11-14/onepc.jsonl" "$TMP/push.log"'
run "late" "2026-11-14T23:51:00Z" 2100
want "23:51 UTC 11-14 -> 2026-11-15 folder" '[ "$(rows "$REPO/data/raw/2026-11-15/onepc.jsonl")" = 2100 ]'
want "the 11-14 night is not overwritten" '[ "$(rows "$REPO/data/raw/2026-11-14/onepc.jsonl")" = 2000 ]'

# A thinner run the same night (fallback after a partial block) keeps the night.
run "thin" "2026-11-15T03:20:00Z" 900
want "thin re-run keeps tonight's 2100 rows" '[ "$(rows "$REPO/data/raw/2026-11-15/onepc.jsonl")" = 2100 ]'
want "thin re-run warns below the floor" 'grep -q "only 900 items" "$TMP/out.log"'
want "no .part left behind" '[ ! -e "$REPO/data/raw/2026-11-15/onepc.jsonl.part" ]'
want "items line still parses for ops_notify" 'grep -qE "[0-9]+ items" "$TMP/out.log"'

# Zero items: nothing is touched, the run fails.
run "zero" "2026-11-15T03:30:00Z" 0
want "zero-item run leaves tonight's file" '[ "$(rows "$REPO/data/raw/2026-11-15/onepc.jsonl")" = 2100 ]'
want "zero-item run does not push" '[ ! -s "$TMP/push.log" ]'
exit "$fail"
