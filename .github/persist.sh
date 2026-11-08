#!/usr/bin/env bash
# Commit + push seen.db after a monitor loop segment (only when it changed).
# Run after EVERY segment with `if: always()`: if a loop overruns the job timeout (or the
# run step errors), the seen.db already written to disk is still committed, so those
# alerts aren't re-fired by the next run.
set -u

# A cancel or a step timeout signals the step's shell, which can leave the python monitor
# running (orphaned) while this step copies seen.db: stop it first, then open the DB once so
# SQLite rolls back any half-written transaction (a hot journal) before the file is committed.
if pgrep -f "ebay_monitor.py" >/dev/null 2>&1; then
  echo "Stopping a still-running monitor process before committing seen.db."
  pkill -INT -f "ebay_monitor.py" || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "ebay_monitor.py" >/dev/null 2>&1 || break
    sleep 1
  done
  pkill -KILL -f "ebay_monitor.py" 2>/dev/null || true
fi
if [ -f seen.db ]; then
  python -c "import sqlite3; c = sqlite3.connect('seen.db'); print('seen.db integrity:', c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()" \
    || echo "::warning::could not open seen.db for an integrity check"
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
# A previous persist in this job may have committed but failed to push (GitHub outage):
# retry that commit too, or the next run re-alerts everything it had marked seen.
git fetch -q origin main 2>/dev/null || true
ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
if [ -z "$(git status --porcelain seen.db)" ]; then
  if [ "${ahead:-0}" -eq 0 ]; then
    echo "No new listings; seen.db unchanged."
    exit 0
  fi
  echo "Retrying push of $ahead unpushed seen.db commit(s)."
else
  git add seen.db
  git commit -m "chore: update seen listings [skip ci]"
fi
# Push to main explicitly (works even from a detached HEAD). If the remote advanced
# during this segment (e.g. a code push), DON'T rebase -- seen.db is binary and can't
# 3-way merge. Instead replay our seen.db on top of the fresh remote tip (ours-wins;
# code/config changes come from the remote, so the NEXT segment runs the new code).
if ! git push origin HEAD:main; then
  # Retry the ours-wins replay: if the remote keeps advancing (or a GitHub outage hits)
  # and we give up, this run's mark_seen rows and below/price_alert flags are LOST with the
  # ephemeral runner, so the next run re-fires them as new -> a duplicate ping storm. ~8 min
  # of backoff rides out a short git outage (the old 75 s didn't); a genuinely unrecoverable
  # persist still fails visibly (segment 2 runs anyway and its persist retries this commit).
  cp seen.db /tmp/seen_ours.db
  pushed=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    git fetch origin main || true
    git checkout -f -B main origin/main
    cp /tmp/seen_ours.db seen.db
    git add seen.db
    git diff --cached --quiet || git commit -m "chore: update seen listings [skip ci]"
    if git push origin HEAD:main; then pushed=1; break; fi
    [ "$attempt" -lt 10 ] && sleep $(( attempt * 10 < 60 ? attempt * 10 : 60 ))
  done
  [ "$pushed" = 1 ] || { echo "ERROR: could not persist seen.db after 10 retries (~8 min)" >&2; exit 1; }
fi
