#!/usr/bin/env bash
# Gate for scripts/ci_bundle.sh, the hand-over between a CI build job and its
# publish job (the only job that can push main). Runs the real script in
# throwaway repos under mktemp: a normal round trip, the downsample shape
# (dirs already `git rm`-ed), the REQUIRE_CLEAN_TREE leftover rule, and the
# refusals a forged bundle must hit (paths outside the publish list,
# traversal, symlink and hard-link entries, extra tar members). No network,
# touches nothing in this repo.
#
# Run: bash scripts/check_ci_bundle.sh
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/ci_bundle.sh"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
fail=0
passed=0

check() {
  if eval "$2"; then
    passed=$((passed + 1))
  else
    echo "[ci-bundle] FAIL $1"
    fail=1
  fi
}

mk() {
  rm -rf "${ROOT:?}/$1"
  mkdir -p "$ROOT/$1"
  cd "$ROOT/$1" || exit 1
  git init -q
  git config user.email t@t
  git config user.name t
  git config core.autocrlf false
  mkdir -p data/site data/raw/2026-01-01 data/raw/2026-01-02 scripts
  echo old > data/catalog.json
  echo a > data/site/a.json
  echo b > data/site/b.json
  echo r1 > data/raw/2026-01-01/x.jsonl
  echo r2 > data/raw/2026-01-02/x.jsonl
  echo 'echo trusted' > scripts/git_commit_push.sh
  git add -A
  git commit -qm init
}

# A bundle written by hand, the way a compromised build job could.
forge() {
  local dir="$1" list="$2"
  shift 2
  mkdir -p "$dir"
  printf '%s\0' "$@" > "$dir/$list"
  [ -f "$dir/changed.list" ] || : > "$dir/changed.list"
  [ -f "$dir/deleted.list" ] || : > "$dir/deleted.list"
}

# 1. round trip: modify, add, delete
mk build
echo new > data/catalog.json
echo c > data/site/c.json
rm data/site/b.json
REQUIRE_CLEAN_TREE=1 bash "$SCRIPT" pack "$ROOT/b1" data/catalog.json data/site >/dev/null
check "pack exits 0" "[ $? -eq 0 ]"
mk pub
bash "$SCRIPT" unpack "$ROOT/b1" data/catalog.json data/site >/dev/null
check "unpack exits 0" "[ $? -eq 0 ]"
check "modified file applied" "[ \"\$(cat data/catalog.json)\" = new ]"
check "new file applied" "[ -f data/site/c.json ]"
check "deleted file applied" "[ ! -e data/site/b.json ]"

# 2. REQUIRE_CLEAN_TREE: a leftover is a hard error at pack time
mk build
echo new > data/catalog.json
echo stray > stray.txt
REQUIRE_CLEAN_TREE=1 bash "$SCRIPT" pack "$ROOT/b2" data/catalog.json >/dev/null 2>&1
check "leftover fails pack" "[ $? -ne 0 ]"
bash "$SCRIPT" pack "$ROOT/b2b" data/catalog.json >/dev/null 2>&1
check "leftover only warns without the flag" "[ $? -eq 0 ]"

# 3. a changed file outside the publish list is refused
mk build
echo evil > scripts/git_commit_push.sh
bash "$SCRIPT" pack "$ROOT/b3" scripts data/catalog.json >/dev/null 2>&1
mk pub
bash "$SCRIPT" unpack "$ROOT/b3" data/catalog.json data/site >/dev/null 2>&1
check "outside path refused" "[ $? -ne 0 ]"
check "trusted script untouched" "[ \"\$(cat scripts/git_commit_push.sh)\" = 'echo trusted' ]"

# 4. a deletion outside the publish list is refused
mk pub
forge "$ROOT/b4" deleted.list scripts/git_commit_push.sh
tar -cf "$ROOT/b4/files.tar" --files-from /dev/null
bash "$SCRIPT" unpack "$ROOT/b4" data/site >/dev/null 2>&1
check "outside deletion refused" "[ $? -ne 0 ] && [ -f scripts/git_commit_push.sh ]"

# 5. traversal and .git names are refused
for name in 'data/site/../../x' 'data/site/./a.json' 'data/site//a.json' 'data/site/.git/config'; do
  mk pub
  forge "$ROOT/b5" changed.list "$name"
  tar -cf "$ROOT/b5/files.tar" --files-from /dev/null
  bash "$SCRIPT" unpack "$ROOT/b5" data/site >/dev/null 2>&1
  check "name $name refused" "[ $? -ne 0 ]"
  rm -rf "$ROOT/b5"
done

# 6. symlink and hard-link tar entries are refused
mk pub
mkdir -p "$ROOT/links/data/site"
echo x > "$ROOT/links/data/site/real.json"
if ln -s /etc/passwd "$ROOT/links/data/site/link.json" 2>/dev/null && [ -L "$ROOT/links/data/site/link.json" ]; then
  forge "$ROOT/b6" changed.list data/site/link.json
  tar -cf "$ROOT/b6/files.tar" -C "$ROOT/links" data/site/link.json
  bash "$SCRIPT" unpack "$ROOT/b6" data/site >/dev/null 2>&1
  check "symlink entry refused" "[ $? -ne 0 ] && [ ! -e data/site/link.json ]"
else
  echo "[ci-bundle] skip symlink case (no symlink support here)"
fi
if ln "$ROOT/links/data/site/real.json" "$ROOT/links/data/site/hard.json" 2>/dev/null; then
  forge "$ROOT/b6h" changed.list data/site/real.json data/site/hard.json
  tar -cf "$ROOT/b6h/files.tar" -C "$ROOT/links" data/site/real.json data/site/hard.json
  if tar -tvf "$ROOT/b6h/files.tar" | cut -c1 | grep -q h; then
    bash "$SCRIPT" unpack "$ROOT/b6h" data/site >/dev/null 2>&1
    check "hard-link entry refused" "[ $? -ne 0 ]"
  else
    echo "[ci-bundle] skip hard-link case (tar stored no link entry)"
  fi
fi

# 7. tar members the lists do not name are never applied
mk pub
mkdir -p "$ROOT/extra/data/site" "$ROOT/extra/scripts"
echo ok > "$ROOT/extra/data/site/a.json"
echo evil > "$ROOT/extra/scripts/git_commit_push.sh"
forge "$ROOT/b7" changed.list data/site/a.json
tar -cf "$ROOT/b7/files.tar" -C "$ROOT/extra" data/site/a.json scripts/git_commit_push.sh
bash "$SCRIPT" unpack "$ROOT/b7" data/site >/dev/null 2>&1
check "listed member applied" "[ $? -eq 0 ] && [ \"\$(cat data/site/a.json)\" = ok ]"
check "unlisted member ignored" "[ \"\$(cat scripts/git_commit_push.sh)\" = 'echo trusted' ]"

# 8. a listed file missing from the tar is an error
mk pub
forge "$ROOT/b8" changed.list data/site/a.json
tar -cf "$ROOT/b8/files.tar" --files-from /dev/null
bash "$SCRIPT" unpack "$ROOT/b8" data/site >/dev/null 2>&1
check "missing member refused" "[ $? -ne 0 ]"

# 9. downsample shape: dirs already `git rm`-ed, trailing-slash paths
mk build
git rm -r -q data/raw/2026-01-01
bash "$SCRIPT" pack "$ROOT/b9" data/raw/2026-01-01/ >/dev/null
check "pack after git rm" "[ $? -eq 0 ]"
mk pub
bash "$SCRIPT" unpack "$ROOT/b9" data/raw/2026-01-01/ >/dev/null
check "deletion applied" "[ $? -eq 0 ] && [ ! -e data/raw/2026-01-01/x.jsonl ]"
git add -- data/raw/2026-01-01/ 2>/dev/null
check "git add stages the deletion" "git diff --cached --name-status | grep -q '^D'"
check "other day untouched" "[ -f data/raw/2026-01-02/x.jsonl ]"

# 10. nothing changed: packed=false, unpack is a no-op
mk build
GITHUB_OUTPUT="$ROOT/out10" bash "$SCRIPT" pack "$ROOT/b10" data/catalog.json >/dev/null
check "empty pack says packed=false" "grep -q 'packed=false' '$ROOT/out10'"
mk pub
bash "$SCRIPT" unpack "$ROOT/b10" data/catalog.json >/dev/null
check "empty unpack is a no-op" "[ $? -eq 0 ] && [ -z \"\$(git status --porcelain)\" ]"

cd / || exit 1
if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "[ci-bundle] pass - $passed checks"
