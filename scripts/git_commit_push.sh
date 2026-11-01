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
#
# SECOND INVARIANT (2026-11-01 failure): the publish list must cover
# EVERYTHING the job wrote. A file that is written but not listed is never
# published, and the old retry path made it worse — it autostashed the whole
# working tree and popped it back after the rebase, so a leftover file that a
# sibling commit had also touched came back as a merge conflict and failed the
# job (normalize-and-deploy: `data/spec_gaps.json`, written by the normalizer
# but missing from the commit path list, conflicted on every rejected push).
# So:
#   1. leftovers are named on every run (`changed but NOT in the publish list`);
#   2. leftovers are DISCARDED on rebase, never re-applied — a stash pop can
#      no longer conflict, and unlisted files cannot ride along by accident;
#   3. a job that publishes a whole coherent data set sets
#      REQUIRE_CLEAN_TREE=1, which turns a leftover into a hard error BEFORE
#      anything is committed (normalize-and-deploy does this: its catalog and
#      data/site tree must be one run, so a forgotten output is a bug, not
#      noise).
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

# Name every change the publish list does not cover, so a forgotten output is
# visible in the log instead of silently unpublished (see invariant 2).
EXCLUDES=()
for p in "${PATHS[@]}"; do
  EXCLUDES+=(":(exclude)$p")
done
UNPUBLISHED="$(git status --porcelain -- . "${EXCLUDES[@]}" || true)"
if [ -n "$UNPUBLISHED" ]; then
  echo "[warn] git_commit_push.sh: changed but NOT in the publish list:" >&2
  printf '%s\n' "$UNPUBLISHED" | sed 's/^/         /' >&2
  if [ "${REQUIRE_CLEAN_TREE:-0}" = "1" ]; then
    echo "[error] git_commit_push.sh: REQUIRE_CLEAN_TREE=1 and the working tree" \
         "holds changes this commit would never publish — add the paths above" \
         "to the caller's publish list (or drop them from the run)" >&2
    exit 1
  fi
fi

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

  # Rebase onto the branch we actually push to (its upstream), not a hardcoded
  # name: `git push` and the rebase must agree on the target or the retry
  # replays our commit onto a ref nobody is comparing against.
  UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [ -z "$UPSTREAM" ]; then
    UPSTREAM="origin/main"
  fi
  echo "[warn] push rejected (attempt $attempt/$MAX_ATTEMPTS) — rebasing onto $UPSTREAM" >&2
  git fetch origin

  # `git rebase` refuses a dirty tree. Set the leftovers aside for the
  # duration and DROP them afterwards: by the invariant above they are not
  # this job's published output, and re-applying them is what turned a benign
  # race into a hard failure. The abort path is safe to pop — the tree is
  # back at the state the stash was taken from, so it always applies cleanly.
  STASHED=0
  if [ -n "$(git status --porcelain)" ]; then
    git stash push --include-untracked -m "git_commit_push.sh: set aside before rebase"
    STASHED=1
  fi

  if git rebase -X theirs "$UPSTREAM"; then
    echo "[ok] rebased onto $UPSTREAM"
  else
    echo "[error] rebase onto $UPSTREAM conflicted — aborting, keeping local state" >&2
    git rebase --abort || true
    if [ "$STASHED" -eq 1 ]; then
      git stash pop || true
    fi
    exit 1
  fi

  if [ "$STASHED" -eq 1 ]; then
    echo "[warn] discarding this run's unpublished leftovers (not in the publish list)" >&2
    git stash drop || true
  fi

  # Jitter before retrying so two writers racing repeatedly don't stay in
  # lockstep and collide again on the very next attempt.
  sleep "$(( (RANDOM % 20) + 5 ))"
done

echo "[error] push failed after $MAX_ATTEMPTS attempts" >&2
exit 1
