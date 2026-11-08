#!/usr/bin/env python3
"""Independent watchdog for the eBay monitor.

The monitor's in-scan health check alerts when a *running* scan goes bad. It cannot
catch the cases where the monitor stops running entirely (GitHub throttles/disables
the cron, or every run crashes) — those fail silently. This runs as a SEPARATE
scheduled workflow and pings Discord if:

  1. no monitor run has STARTED in STALE_HOURS (cron throttled/disabled/broken), or
  2. the most recent completed monitor run FAILED (the job is crashing), or
  3. the committed health state is "down" (scraper/matching broken and unresolved).

It also RESTARTS the monitor when its self-requeue chain has dropped: nothing running or
queued, and the last run either finished normally or failed only at "Queue the next run"
(2026-11-05: GitHub's API answered HTTP 500/502 to every try, and the monitor sat idle
until the next cron fire). A run that crashed while scanning is left alone (alert only)
unless nothing has run for STALE_HOURS.

Because it's a distinct workflow, a break in the monitor workflow itself doesn't stop
this. The Discord alert (and log) is the signal; the job FAILS only when that alert can't
be delivered (no or rejected webhook), so GitHub's failed-run email reaches the owner.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

STALE_HOURS = 5.0     # alert when no monitor run has been ACTIVE for this long
TIMEOUT_MINUTES = 300  # monitor.yml timeout-minutes: a run cancelled after this long hit it
RESTART_AFTER_MIN = 15  # a finished run queues its successor within ~1 min; 15 min idle = dropped
REQUEUE_STEP = "Queue the next run"
# Steps that run no scan: when only these failed it was GitHub (git, the API, setup), not the
# monitor's code, so the chain is restarted at once instead of waiting STALE_HOURS like a crash.
INFRA_STEPS = ("Set up job", "Checkout latest main", "Set up Python", "Install dependencies",
               "Persist seen listings", REQUEUE_STEP, "Post ", "Complete job")
# Discord's Cloudflare front rejects urllib's default "Python-urllib/3.x" agent with HTTP 403
# ("error code: 1010") before the webhook is even looked up, so every watchdog alert failed
# (found 2026-11-05). Any named agent goes through.
USER_AGENT = "ebay-listing-monitor-watchdog/1.1 (+https://github.com/cal-chan-cloud/ebay-listing-monitor)"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root
DB = os.path.join(HERE, "seen.db")


def notify_user():
    """config.json's notify_user (the owner's Discord id), or None."""
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            who = json.load(f).get("notify_user")
        return str(who) if who else None
    except Exception:
        return None


def discord(msg, mention=True):
    """Post the alert; True if Discord accepted it. mention=False for a notice that needs no
    action (the watchdog already restarted the monitor)."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url or url.startswith("PASTE_"):
        print("watchdog: no webhook configured; not sending.")
        return False
    payload = {"embeds": [{
        "title": "\U0001F415 eBay monitor watchdog",
        "description": msg,
        "color": 0xB71C1C,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}
    who = notify_user() if mention else None
    if who:   # embed-only messages don't notify anyone; an @mention does
        payload["content"] = f"<@{who}> eBay monitor watchdog"
        payload["allowed_mentions"] = {"users": [who]}
    else:
        payload["allowed_mentions"] = {"parse": []}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        urllib.request.urlopen(req, timeout=20)
        print("watchdog: Discord alert sent.")
        return True
    except urllib.error.HTTPError as e:
        try:
            body = e.read()[:200]
        except Exception:
            body = b""
        print(f"watchdog: Discord send failed: HTTP {e.code} {body!r}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"watchdog: Discord send failed: {e}", file=sys.stderr)
        return False


def recent_runs():
    """Recent monitor.yml runs via the GitHub CLI, newest first.

    Returns a list (possibly empty = genuinely no runs found) on success, or None if the
    gh call ERRORED — the caller distinguishes these so a persistent gh failure falls back
    to a gh-independent staleness signal instead of silently skipping all checks.
    """
    try:
        out = subprocess.check_output(
            ["gh", "run", "list", "--workflow", "monitor.yml", "-L", "20",
             "--json", "databaseId,createdAt,startedAt,updatedAt,status,conclusion", "-R", REPO],
            text=True, timeout=60)
        return json.loads(out)
    except Exception as e:
        print(f"watchdog: could not list runs: {e}", file=sys.stderr)
        return None


def job_minutes(run_id):
    """Minutes the run's job actually RAN (its own start -> end), or None if unknown. A run's
    createdAt-based span includes hours spent queued behind the previous monitor job."""
    try:
        out = subprocess.check_output(
            ["gh", "run", "view", str(run_id), "--json", "jobs", "-R", REPO], text=True, timeout=60)
        jobs = json.loads(out).get("jobs") or []
        spans = [(datetime.fromisoformat(j["completedAt"].replace("Z", "+00:00"))
                  - datetime.fromisoformat(j["startedAt"].replace("Z", "+00:00"))).total_seconds() / 60
                 for j in jobs if j.get("startedAt") and j.get("completedAt")]
        return max(spans) if spans else None
    except Exception as e:
        print(f"watchdog: could not read jobs of run {run_id}: {e}", file=sys.stderr)
        return None


def failed_steps(run_id):
    """Names of the run's failed steps, or None if they can't be read."""
    try:
        out = subprocess.check_output(
            ["gh", "run", "view", str(run_id), "--json", "jobs", "-R", REPO], text=True, timeout=60)
        jobs = json.loads(out).get("jobs") or []
        return [st.get("name") or "" for j in jobs for st in (j.get("steps") or [])
                if st.get("conclusion") == "failure"]
    except Exception as e:
        print(f"watchdog: could not read steps of run {run_id}: {e}", file=sys.stderr)
        return None


def dispatch_monitor():
    """Queue a monitor run; True if GitHub accepted it. Retries through a brief API outage,
    bounded (3 x 30 s + 2 x 15 s) so the Discord alert still goes out inside the job timeout."""
    if not REPO:
        print("watchdog: GITHUB_REPOSITORY unset; not dispatching.", file=sys.stderr)
        return False
    for attempt in range(3):
        try:
            subprocess.run(["gh", "workflow", "run", "monitor.yml", "--ref", "main", "-R", REPO],
                           check=True, timeout=30)
            print("watchdog: queued a new monitor run.")
            return True
        except Exception as e:
            print(f"watchdog: dispatch attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(15)
    return False


def workflow_state():
    """monitor.yml's state ('active', 'disabled_manually', 'disabled_inactivity', ...) or None."""
    if not REPO:
        return None
    try:
        return subprocess.check_output(
            ["gh", "api", f"repos/{REPO}/actions/workflows/monitor.yml", "--jq", ".state"],
            text=True, timeout=30).strip() or None
    except Exception as e:
        print(f"watchdog: could not read the workflow state: {e}", file=sys.stderr)
        return None


def seen_db_commit_age_hours():
    """Age in hours of the newest seen.db commit, or None if unreadable.

    A gh-independent liveness proxy: each scan bumps seen.db (the per-scan
    zero_match_streak meta write changes the DB), so it's committed ~once per run.
    """
    try:
        out = subprocess.check_output(
            ["git", "-C", HERE, "log", "-1", "--format=%ct", "--", "seen.db"],
            text=True, timeout=30).strip()
        if not out:
            return None
        commit = datetime.fromtimestamp(int(out), tz=timezone.utc)
        return (datetime.now(timezone.utc) - commit).total_seconds() / 3600
    except Exception as e:
        print(f"watchdog: seen.db commit-age read failed: {e}", file=sys.stderr)
        return None


def main():
    if os.environ.get("WATCHDOG_TEST") == "1":    # manual "test_alert" run: delivery check only
        ok = discord("Test message: the watchdog can deliver alerts to this channel (manual run, "
                     "nothing is wrong).", mention=False)
        sys.exit(0 if ok else 1)
    now = datetime.now(timezone.utc)
    problems = []
    restart = None          # why the requeue chain looks dropped (-> dispatch a new run)

    # Disabling monitor.yml is how the owner STOPS the monitor: don't alert (or try to restart
    # it) every few hours afterwards. GitHub's own inactivity disable is a different story.
    state = workflow_state()
    if state == "disabled_manually":
        print("watchdog: monitor.yml is disabled (stopped on purpose); nothing to check.")
        return
    if state == "disabled_inactivity":
        problems.append("GitHub disabled the monitor workflow for inactivity. Re-enable it: Actions → "
                        "eBay Listing Monitor → Enable workflow.")

    runs = recent_runs()
    if runs:
        def _t(r, k):
            v = r.get(k) or r.get("createdAt")
            return datetime.fromisoformat(v.replace("Z", "+00:00"))

        def _minutes(r):
            return (_t(r, "updatedAt") - _t(r, "createdAt")).total_seconds() / 60

        # GitHub reports a job that hit timeout-minutes as conclusion 'cancelled' (never
        # 'timed_out'). A short 'cancelled' run is a superseded pending run (the concurrency
        # group cancels it) or a manual cancel: it neither scanned nor crashed, so it must
        # not mask the real last run. A QUEUED run hasn't scanned anything either.
        def _hung(r):   # long cancelled run: confirm with the job's own run time (queue excluded)
            ran = job_minutes(r["databaseId"]) if r.get("databaseId") else None
            return ran is None or ran >= TIMEOUT_MINUTES - 5

        timed_out = [r for r in runs if r.get("status") == "completed"
                     and r.get("conclusion") == "cancelled" and _minutes(r) >= TIMEOUT_MINUTES and _hung(r)]
        real = [r for r in runs if r.get("conclusion") not in ("cancelled", "skipped") or r in timed_out]
        # Liveness = when a run was last ACTIVE: now, if one is running (a multi-hour looping
        # job; a hung one is bounded by timeout-minutes), else the END (updatedAt) of the
        # newest run that really ran. startedAt is useless here: GitHub sets it to createdAt,
        # which includes time spent waiting in the concurrency queue.
        running = any(r.get("status") == "in_progress" for r in runs)
        ended = [_t(r, "updatedAt") for r in real if r.get("status") == "completed"]
        if not running:
            last = max(ended) if ended else _t(runs[-1], "createdAt")
            idle_h = (now - last).total_seconds() / 3600
            if idle_h > STALE_HOURS:
                problems.append(
                    f"No monitor run has been active for {idle_h:.1f}h (last ended: {last:%Y-%m-%d %H:%M} UTC). "
                    "GitHub cron may be throttled/disabled, or the workflow is failing to trigger.")
        completed = [r for r in real if r.get("status") == "completed"]
        newest = completed[0] if completed else None
        crashed = False
        if newest and newest in timed_out:
            crashed = True
            problems.append(f"The most recent monitor run hit the {TIMEOUT_MINUTES}-min job timeout "
                            "(hung) and was cancelled.")
        elif newest and newest.get("conclusion") in ("failure", "startup_failure"):
            steps = failed_steps(newest["databaseId"]) if newest.get("databaseId") else None
            if steps and all(st.startswith(REQUEUE_STEP) for st in steps):
                restart = (f"The last monitor run scanned normally but GitHub refused to queue the next one "
                           f"(its \"{REQUEUE_STEP}\" step failed), so the monitor stopped at "
                           f"{_t(newest, 'updatedAt'):%Y-%m-%d %H:%M} UTC.")
            elif steps and all(st.startswith(INFRA_STEPS) for st in steps):
                restart = (f"The last monitor run failed outside the scan (failed step: {', '.join(steps)}), "
                           "most likely a GitHub outage rather than a crash"
                           + ("; its seen listings may not have been saved, so a few alerts may repeat"
                              if any(st.startswith("Persist") for st in steps) else "")
                           + f". The monitor stopped at {_t(newest, 'updatedAt'):%Y-%m-%d %H:%M} UTC.")
            else:
                crashed = True
                problems.append("The most recent completed monitor run FAILED — the job is crashing"
                                + (f" (failed step: {', '.join(steps)})." if steps else "."))
        # The chain dropped: nothing running or queued. A failed requeue is restarted at once
        # (nothing is retrying it any more); a successful run whose successor is missing after
        # RESTART_AFTER_MIN; a crash only once nothing has run for STALE_HOURS (no crash loop).
        queued = any(r.get("status") in ("queued", "pending", "waiting", "requested") for r in runs)
        if newest and not running and not queued:
            idle_min = (now - _t(newest, "updatedAt")).total_seconds() / 60
            if restart is not None:
                pass
            elif not crashed and newest.get("conclusion") == "success" and idle_min >= RESTART_AFTER_MIN:
                restart = (f"The monitor stopped at {_t(newest, 'updatedAt'):%Y-%m-%d %H:%M} UTC: its last run "
                           "finished normally but no next run was queued.")
            elif crashed and idle_min >= STALE_HOURS * 60:
                restart = "Nothing has run since that failure, so the watchdog is giving it another try."
        else:
            restart = None       # a run is running or queued again: nothing to restart
    elif runs is None:
        # gh ERRORED — fall back to a gh-independent liveness signal (seen.db commit
        # recency) so a stopped monitor is still caught. Wide threshold (2x) avoids false
        # alarms on quiet periods / a single transient gh blip within the window.
        age_h = seen_db_commit_age_hours()
        if age_h is not None and age_h > 2 * STALE_HOURS:
            problems.append(
                f"gh CLI is unavailable AND seen.db hasn't been committed in {age_h:.1f}h — "
                "the monitor appears stopped (can't confirm via GitHub API).")
        else:
            print("watchdog: gh unavailable; seen.db commit recency within threshold "
                  f"(age={age_h if age_h is None else f'{age_h:.1f}h'}).")
    else:
        # runs == [] : gh succeeded but found no runs — note it, don't hard-alert.
        print("watchdog: gh returned no monitor runs (skipping recency/failure checks).")

    try:
        if os.path.exists(DB):
            c = sqlite3.connect(DB)
            row = c.execute("SELECT value FROM meta WHERE key='health'").fetchone()
            if row and row[0] == "down":
                problems.append("Committed health state is DOWN (0 scraped, or 0 matched across scans) "
                                "and hasn't recovered — the scraper or matching is broken.")
    except Exception as e:
        print(f"watchdog: health read error: {e}", file=sys.stderr)

    healed = False
    if restart is not None:
        healed = dispatch_monitor()
        problems.append(restart + (" ✅ Restarted it: a new monitor run is queued." if healed else
                                   " ❌ Couldn't queue a new run: start it from Actions → "
                                   "eBay Listing Monitor → Run workflow."))
    if problems:
        msg = "\n".join(f"• {p}" for p in problems)
        if REPO:
            msg += f"\n\nActions: https://github.com/{REPO}/actions"
        print("WATCHDOG ALERT:\n" + msg)
        # A chain the watchdog just restarted needs no action: notify without the @mention.
        if not discord(msg, mention=not (healed and len(problems) == 1)):
            # Undeliverable alert (no/rejected webhook): fail this scheduled run instead, so
            # GitHub's failed-workflow email reaches the owner.
            sys.exit(1)
    else:
        print("watchdog: monitor is running and healthy.")


if __name__ == "__main__":
    main()
