#!/usr/bin/env bash
# Hands a CI job's data outputs from its read-only build job to its publish
# job. Only the publish job holds `contents: write`, and it runs no installs,
# scrapers, decoders or AI calls: third-party packages and vendor content
# never share a runner with a token that can push main (decisions.md, Tools).
#
# Usage:
#   ci_bundle.sh pack <dir> <path>...
#     Build job. Writes <dir>/changed.list + <dir>/deleted.list (NUL
#     separated, vs HEAD) and <dir>/files.tar (the changed files) for
#     everything under <path>... Changes outside <path>... are named;
#     REQUIRE_CLEAN_TREE=1 makes them a hard error, as in git_commit_push.sh.
#     Sets `packed=true|false` in $GITHUB_OUTPUT.
#   ci_bundle.sh unpack <dir> <path>...
#     Publish job, fresh checkout of the same commit. Applies the bundle and
#     refuses any entry outside <path>... or that is not a regular file. The
#     paths come from the workflow, never from the bundle.
#
# Then the publish job runs scripts/git_commit_push.sh with the same paths.
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "usage: ci_bundle.sh pack|unpack <dir> <path>..." >&2
  exit 1
fi
MODE="$1"
DIR="$2"
shift 2
PATHS=("$@")

inside_paths() {
  local f="$1" p
  case "/$f/" in
    *//*|*/./*|*/../*|*/.git/*) return 1 ;;
  esac
  for p in "${PATHS[@]}"; do
    p="${p%/}"
    if [ "$f" = "$p" ] || [[ "$f" == "$p/"* ]]; then
      return 0
    fi
  done
  return 1
}

count() {
  tr -cd '\0' < "$1" | wc -c | tr -d ' '
}

pack() {
  mkdir -p "$DIR"
  local excludes=() present=() p leftover
  for p in "${PATHS[@]}"; do
    excludes+=(":(exclude)$p")
    if [ -e "$p" ]; then present+=("$p"); fi
  done
  leftover="$(git status --porcelain -- . "${excludes[@]}" || true)"
  if [ -n "$leftover" ]; then
    echo "[warn] ci_bundle.sh: changed but NOT in the publish list:" >&2
    printf '%s\n' "$leftover" | sed 's/^/         /' >&2
    if [ "${REQUIRE_CLEAN_TREE:-0}" = "1" ]; then
      echo "[error] ci_bundle.sh: REQUIRE_CLEAN_TREE=1 and the working tree" \
           "holds changes this run would never publish — add the paths above" \
           "to the publish list (or drop them from the run)" >&2
      exit 1
    fi
  fi

  # vs HEAD, not `git add`: a path the job already `git rm`-ed matches no
  # pathspec and would make `git add` fail.
  git diff HEAD --name-only --no-renames -z --diff-filter=D -- "${PATHS[@]}" > "$DIR/deleted.list"
  {
    git diff HEAD --name-only --no-renames -z --diff-filter=d -- "${PATHS[@]}"
    if [ "${#present[@]}" -gt 0 ]; then
      git ls-files -z --others --exclude-standard -- "${present[@]}"
    fi
  } > "$DIR/changed.list"
  tar -cf "$DIR/files.tar" --null --no-recursion --verbatim-files-from -T "$DIR/changed.list"

  local changed deleted packed=false
  changed="$(count "$DIR/changed.list")"
  deleted="$(count "$DIR/deleted.list")"
  if [ "$changed" -gt 0 ] || [ "$deleted" -gt 0 ]; then
    packed=true
  fi
  echo "[ok] ci_bundle.sh: packed $changed changed, $deleted deleted"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "packed=$packed" >> "$GITHUB_OUTPUT"
  fi
}

unpack() {
  local f bad stage
  for f in changed.list deleted.list files.tar; do
    if [ ! -f "$DIR/$f" ]; then
      echo "[error] ci_bundle.sh: $DIR/$f missing" >&2
      exit 1
    fi
  done

  while IFS= read -r -d '' f; do
    if ! inside_paths "$f"; then
      printf '[error] ci_bundle.sh: bundle names %q, outside the publish list\n' "$f" >&2
      exit 1
    fi
  done < <(cat "$DIR/changed.list" "$DIR/deleted.list")

  # Regular files only: a link entry could aim the copy below outside the tree.
  bad="$(tar -tvf "$DIR/files.tar" | cut -c1 | sort -u | tr -d '\n-')"
  if [ -n "$bad" ]; then
    echo "[error] ci_bundle.sh: files.tar holds non-regular entries ($bad)" >&2
    exit 1
  fi

  stage="$(mktemp -d)"
  tar -xf "$DIR/files.tar" -C "$stage" --no-same-owner
  while IFS= read -r -d '' f; do
    if [ ! -f "$stage/$f" ] || [ -L "$stage/$f" ]; then
      printf '[error] ci_bundle.sh: %q missing from files.tar\n' "$f" >&2
      exit 1
    fi
    mkdir -p -- "$(dirname -- "$f")"
    cp -f -- "$stage/$f" "$f"
  done < "$DIR/changed.list"
  while IFS= read -r -d '' f; do
    rm -f -- "$f"
  done < "$DIR/deleted.list"
  rm -rf -- "$stage"

  echo "[ok] ci_bundle.sh: applied $(count "$DIR/changed.list") changed, $(count "$DIR/deleted.list") deleted"
}

case "$MODE" in
  pack) pack ;;
  unpack) unpack ;;
  *)
    echo "usage: ci_bundle.sh pack|unpack <dir> <path>..." >&2
    exit 1
    ;;
esac
