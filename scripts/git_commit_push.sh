#!/usr/bin/env bash
# Shared commit+push step for anything that writes into data/ and pushes to
# main: the cloud-scrape matrix jobs, the detail job, the normalize job, and
# the Nano. Several of these legitimately race each other (the 3 scrape
# matrix jobs run in PARALLEL on stale checkouts).
#
# Usage:
#   scripts/git_commit_push.sh "<commit message>" <path> [<path> ...]
#
# Exits 0 with no commit made if there's nothing staged to commit (a vendor
# producing byte-identical output to yesterday is not an error).
#
# CRITICAL INVARIANT (Sep 2026 wipeout, 5 days of plonter/ivory snapshots
# deleted): the retry path MUST NEVER `git add` a broad directory from a
# stale working tree. `git add data/raw/` on a checkout that predates a
# sibling job's push records the sibling's files as DELETED. Rules:
#   1. Callers pass NARROW paths — only files THEY wrote this run
#      (e.g. data/raw/2026-09-04/plonter.jsonl, never data/raw/).
#   2. On push rejection we `git rebase -X theirs origin/main`, which replays
#      our commit(s) onto the newest tip. Rebase only touches the files our
#      commits touched, so sibling files are never at risk. -X theirs
#      auto-resolves same-file collisions in favor of our just-generated
#      output (fresh snapshot/catalog always wins over an older run).
set -euo pipefail

COMMIT_MSG="$1"
shift
PATHS=("$@")

if [ "${#PATHS[@]}" -eq 0 ]; then
  echo "[error] git_commit_push.sh: no paths given" >&2
  exit 1
fi

# Caution (Sep 2026 wipeout, 5 days of plonter/ivory snapshots deleted):
# `git add` on a broad directory stages DELETIONS of tracked files missing
# from this checkout — which is exactly what parallel matrix jobs have
# (each checks out before its siblings push). Prefer narrow file paths
# naming only what this run generated. Directory paths are allowed only
# when the directory contains exclusively this job's outputs (e.g. a
# per-vendor image folder) — never shared trees like data/raw/.
for p in "${PATHS[@]}"; do
  if [ -d "$p" ]; then
    # Exempt: data/images/<vendor>/ is written exclusively by the job
    # committing it (cloud detail job per vendor dir; Nano for tms/) —
    # no sibling job can stage deletions through it, so the stale-
    # checkout hazard below does not apply.
    case "$p" in
      data/images/*/)
        ;;
      *)
        echo "[warn] git_commit_push.sh: directory path '$p' — must contain only this job's outputs (see header)" >&2
        ;;
    esac
  fi
done

git add -- "${PATHS[@]}"

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

  echo "[warn] push rejected (attempt $attempt/$MAX_ATTEMPTS) — rebasing onto latest main" >&2
  git fetch origin

  STASHED=0
  if [ -n "$(git status --porcelain)" ]; then
    git stash push --include-untracked -m "git_commit_push.sh: autostash before rebase"
    STASHED=1
  fi

  if git rebase -X theirs origin/main; then
    echo "[ok] rebased onto origin/main"
  else
    echo "[error] rebase onto origin/main conflicted — aborting, keeping local state" >&2
    git rebase --abort || true
    if [ "$STASHED" -eq 1 ]; then
      git stash pop || true
    fi
    exit 1
  fi

  if [ "$STASHED" -eq 1 ]; then
    if ! git stash pop; then
      echo "[error] stash pop conflicted after rebase — resolve manually" >&2
      exit 1
    fi
    # Anything the stash restored that isn't ours must not ride along.
    git add -- "${PATHS[@]}"
    if ! git diff --cached --quiet; then
      git commit -m "$COMMIT_MSG" || true
    fi
  fi

  # Jitter before retrying so two writers racing repeatedly don't stay in
  # lockstep and collide again on the very next attempt.
  sleep "$(( (RANDOM % 20) + 5 ))"
done

echo "[error] push failed after $MAX_ATTEMPTS attempts" >&2
exit 1
