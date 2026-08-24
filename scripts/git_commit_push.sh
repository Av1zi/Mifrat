#!/usr/bin/env bash
# Shared commit+push step for anything that writes into data/ and pushes to
# main: the cloud-scrape job, the normalize job, and the Nano. All three can
# legitimately race each other (§10: "Git push conflicts between the two
# writers are handled with rebase-and-retry with jitter"), so this one
# script is the single implementation of that retry loop rather than three
# copies that could drift.
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

  echo "[warn] push rejected (attempt $attempt/$MAX_ATTEMPTS) — fetching and rebasing" >&2
  git fetch origin

  # A caller only stages/commits the paths it cares about — anything else
  # modified in the working tree (e.g. an output file the caller forgot to
  # pass, as happened with data/review_queue.json — see DECISIONS.md Aug
  # 2026) would otherwise abort the rebase below with "You have unstaged
  # changes." Stash it out of the way and restore it after, rather than
  # failing the whole run over a file this script wasn't even asked about.
  STASHED=0
  if [ -n "$(git status --porcelain)" ]; then
    git stash push --include-untracked -m "git_commit_push.sh: autostash before rebase"
    STASHED=1
  fi

  if ! git rebase origin/HEAD; then
    echo "[error] rebase conflict — manual intervention needed, aborting rebase" >&2
    git rebase --abort
    if [ "$STASHED" -eq 1 ]; then
      git stash pop || echo "[warn] stash pop failed after rebase abort — check 'git stash list'" >&2
    fi
    exit 1
  fi

  if [ "$STASHED" -eq 1 ]; then
    git stash pop
  fi

  # Jitter before retrying so two writers racing repeatedly don't stay in
  # lockstep and collide again on the very next attempt.
  sleep "$(( (RANDOM % 20) + 5 ))"
done

echo "[error] push failed after $MAX_ATTEMPTS attempts" >&2
exit 1