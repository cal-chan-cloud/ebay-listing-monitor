# eBay → Discord New Listing Monitor

Watches eBay for **newly listed** items matching your search terms, and posts a
Discord notification for each new listing that matches the grade buckets you care
about. The notification includes the **price**, a **link to the listing**, and the
**grade + grading company** (or "Ungraded").

Currently watching: **Luffy ST26-005 SP** — **English only**, ungraded / PSA 10 / BGS 10 / BGS 9.5.

## Setup

1. Install dependencies (already present on this machine):
   ```
   pip install -r requirements.txt
   ```

2. Create a Discord webhook:
   - In Discord: pick the channel → **Edit Channel** (gear) → **Integrations** →
     **Webhooks** → **New Webhook** → **Copy Webhook URL**.

3. Paste that URL into `config.json` → `discord_webhook_url`
   (replace `PASTE_YOUR_DISCORD_WEBHOOK_URL_HERE`).

## Run

```
python ebay_monitor.py            # run forever, checking every 5 min (config poll_interval_seconds)
python ebay_monitor.py --once     # one pass then exit  (use with Windows Task Scheduler)
python ebay_monitor.py --dry-run  # scan + print matches, send nothing, record nothing
```

**First run behavior:** the *first* time a watch runs it silently records all
current listings as "seen" so you don't get flooded — you'll only be alerted on
listings posted *after* that. To instead alert on everything already up, run once
with `--notify-existing`.

### Windows Task Scheduler (already set up)

A scheduled task named **"eBay Luffy Monitor"** is installed. It runs
`pythonw.exe ebay_monitor.py --once` **every 5 minutes** while you are logged in,
using the real Python install (`...\Programs\Python\Python311\pythonw.exe`) so no
console window pops up. It's configured to **catch up on missed runs** after the
PC wakes/turns on and to **wake the PC from sleep** to run.

> **About "even when the computer is off":** no local scheduled task can run while
> the PC is fully powered **off** — Windows isn't running to launch anything. This
> task covers the next best thing: it runs whenever the PC is on, wakes it from
> **sleep/hibernate**, and catches up after it powers back on. For true 24/7
> coverage (including while your PC is off) the monitor needs to live on an
> always-on host — a cheap cloud VM, a Raspberry Pi, or a service like Render.
> The script runs unchanged there; ask and I'll set that up.

Manage the task:

```powershell
Get-ScheduledTaskInfo "eBay Luffy Monitor"     # last run time + result (0x0 = OK) + next run
Start-ScheduledTask     "eBay Luffy Monitor"   # run right now
Disable-ScheduledTask   "eBay Luffy Monitor"   # pause
Enable-ScheduledTask    "eBay Luffy Monitor"   # resume
Unregister-ScheduledTask "eBay Luffy Monitor" -Confirm:$false   # remove
```

Activity is also logged to `monitor.log` in this folder.

To make it run **whether or not you're logged in**, re-register the task with a
stored password (`-LogonType Password`); that requires your Windows account
password, so it wasn't done automatically.

## Adding more items

Add entries to the `watches` array in `config.json`:

```json
{
  "name": "Zoro OP01-001",
  "query": "zoro op01-001 alt art",
  "require": ["op01-001"],
  "grades": ["ungraded", "psa10", "bgs10", "bgs9.5"],
  "language": "english",
  "min_price": null,
  "max_price": null
}
```

- `query` — what gets typed into eBay search. Keep it fairly broad; eBay
  fuzzy-matches, so use `require` to pin the exact card.
- `require` — **list of terms that must ALL appear in the title** (case- and
  punctuation-insensitive, so `op05-119` = `OP05 119` = `op05119`). This is what
  stops eBay's fuzzy search from alerting you about the wrong card. Add the
  distinguishing words too, e.g. `["op10-005", "flagship"]` to get only the
  Flagship promo and not the same-numbered base card.
- `exclude` — optional extra terms to reject. Proxies/replicas
  (`proxy`, `orica`, `custom`, `handmade`, …) are already excluded globally.
- `grades` — any of: `ungraded`, `psa10`, `bgs10`, `bgs9.5`. (More can be added in
  `classify_grade()` — e.g. `psa9`, `cgc10`.)
- `language` — `english` (default), `japanese`, `chinese`, `korean`, or `any`.
- `min_price` / `max_price` — optional numeric filters (use `null` to disable).

### Language filtering

By default a watch is **English only**: listings whose titles are flagged
Japanese/Chinese/Korean (the words "Japanese", "Jp", "Chinese", CJK characters,
etc.) are dropped. To monitor a card in Japanese instead, set that watch's
`"language": "japanese"`.

> Note: listings with **no** language marker at all are kept (so genuine English
> listings that simply don't say "English" aren't missed). This can occasionally
> let through an unmarked import — tell me if you'd prefer strict "must say
> English" matching instead.

## How grading is detected

The listing title is scanned:
- `PSA 10` → PSA 10
- `BGS 9.5` / `Beckett 9.5` → BGS 9.5
- `BGS 10` / `Beckett 10` → BGS 10
- any other grading company/number (PSA 9, CGC, SGC, …) → *ignored* (not in your buckets)
- no grading company mentioned → Ungraded / Raw

Detection relies on sellers writing the grade in the title (standard practice for
slabs). `seen.db` (SQLite, auto-created) tracks which listings have already been
alerted so you never get a duplicate.

## Notes

- eBay bot-protection 403s a cold request, so the script first visits the eBay
  homepage to seed cookies, then re-primes automatically if a 403 appears later.
- If eBay ever hard-blocks scraping, the robust alternative is the official
  [eBay Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html)
  (free dev account + OAuth) — `fetch_listings()` is the only function that would
  need swapping.
