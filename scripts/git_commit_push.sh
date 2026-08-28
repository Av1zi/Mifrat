#!/usr/bin/env bash
# Shared commit+push step for anything that writes into data/ and pushes to
# main: the cloud-scrape job, the normalize job, and the Nano. All three can
# legitimately race each other. Generated catalog files are not meaningfully
# mergeable, so a rejected push is handled by recreating the local output
# commit on top of the newest remote commit rather than rebasing it.
#
# Usage:
#   scripts/git_commit_push.sh "<commit message>" <path> [<path> ...]
#
# Exits 0 with no commit made if there's nothing staged to commit (a vendor
# producing byte-identical output to yesterday is not an error).
set -euo pipefail

COMMIT_MSG="$1"
shift
PATHS=("$@")

if [ "${#PATHS[@]}" -eq 0 ]; then
  echo "[error] git_commit_push.sh: no paths given" >&2
  exit 1
fi

git add "${PATHS[@]}"

if git diff --cached --quiet; then
  echo "[ok] nothing to commit (no changes in: ${PATHS[*]})"
  exit 0
fi

git commit -m "$COMMIT_MSG"

MAX_ATTEMPTS=5
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if git push; then
    echo "[ok] pushed on attempt $attempt"
    exit 0
  fi

  echo "[warn] push rejected (attempt $attempt/$MAX_ATTEMPTS) — refreshing base commit" >&2
  git fetch origin

  # A caller only stages/commits the paths it cares about. Preserve any other
  # local changes while replacing the generated commit with an equivalent
  # commit based on the latest remote tip.
  STASHED=0
  if [ -n "$(git status --porcelain)" ]; then
    git stash push --include-untracked -m "git_commit_push.sh: autostash before refresh"
    STASHED=1
  fi

  git reset --mixed origin/HEAD
  git add "${PATHS[@]}"

  if git diff --cached --quiet; then
    echo "[ok] remote already contains the generated output"
    if [ "$STASHED" -eq 1 ]; then
      git stash pop
    fi
    exit 0
  fi

  git commit -m "$COMMIT_MSG"

  if [ "$STASHED" -eq 1 ]; then
    git stash pop
  fi

  # Jitter before retrying so two writers racing repeatedly don't stay in
  # lockstep and collide again on the very next attempt.
  sleep "$(( (RANDOM % 20) + 5 ))"
done

echo "[error] push failed after $MAX_ATTEMPTS attempts" >&2
exit 1