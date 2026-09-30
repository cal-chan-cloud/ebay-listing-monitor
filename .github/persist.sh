#!/usr/bin/env bash
# Commit + push seen.db after a monitor loop segment (only when it changed).
# Run after EVERY segment with `if: always()`: if a loop overruns the job timeout (or the
# run step errors), the seen.db already written to disk is still committed, so those
# alerts aren't re-fired by the next run.
set -u

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
  # Retry the ours-wins replay a few times: if the remote keeps advancing (or a
  # transient GitHub error hits) and we give up, this run's mark_seen rows and
  # below/price_alert flags are LOST with the ephemeral runner, so the next run
  # re-fires them as new -> a duplicate ping storm. Bounded loop + fail-visible
  # exit so a genuinely unrecoverable persist marks the run failed (watchdog sees it).
  cp seen.db /tmp/seen_ours.db
  pushed=0
  for attempt in 1 2 3 4 5; do
    git fetch origin main || true
    git checkout -f -B main origin/main
    cp /tmp/seen_ours.db seen.db
    git add seen.db
    git diff --cached --quiet || git commit -m "chore: update seen listings [skip ci]"
    if git push origin HEAD:main; then pushed=1; break; fi
    sleep $((attempt * 5))
  done
  [ "$pushed" = 1 ] || { echo "ERROR: could not persist seen.db after 5 retries" >&2; exit 1; }
fi
