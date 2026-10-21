# eBay → Discord New Listing Monitor

Watches eBay for matching cards and posts a Discord notification when:
- a **new listing** appears (price, link, grade + grading company),
- a tracked listing's **price drops** (green "📉 price drop" alert showing old → new), and
- a **listing is below market** (amber "🔥 below market" alert). Market price is the
  median of **recent eBay sold prices for that card in the same grade** (real recent
  sales; TCGplayer is Cloudflare-blocked and can't be scraped) — a PSA 10 is compared
  to recent PSA 10 sales, a raw to recent raws. Alerts show the market price and the
  listing's % vs market.

**Auction (bid) listings are excluded** by default — only fixed-price / Buy-It-Now
listings are tracked (set `include_auctions: true`, or per-watch `allow_auctions`,
to include them).

**Only US + Canada sellers** are notified by default (from each listing's "Located
in" country). Change with the top-level `allowed_regions` (e.g. `["US"]` or add
more), or per-watch `allowed_regions`. Listings whose location can't be read are
skipped unless `allow_unknown_region: true`.

The monitor is TCG-agnostic (grade detection, currency, and matching all work for any
card game). Currently watching (English unless noted; grades: ungraded / PSA 10 / BGS 10 / BGS 9.5 / CGC 10):

**One Piece:**
- **Luffy ST26-005 SP** — SP only (min_price filters out the cheap base card)
- **Luffy OP05-119 SEC (Alt / Manga Art)** — the alt-art / manga-art SEC only (the title must say alt / manga / parallel: a bare OP05-119 is also the regular-art SEC and its PRB01 reprint); min_price filters the base card
- **Luffy ST10-006 One Piece Day Dallas Promo** — the 2025 Dallas event exclusive (not the starter-deck ST10-006)
- **3rd Anniversary Set (English, sealed)** — the sealed 2025 English boxed **set** (a sealed *product*, not a single; rejects the singles/promos/campaign-collection pulled from it; @mention when one lists under $500)

**Pokémon** (`language: any` — see note):
- **Giratina V 186/196** — Lost Origin alternate full art (not the regular V or any VSTAR; English, $300 floor)
- **Mew ex 232/091** — Paldean Fates "Bubble Mew" Special Illustration Rare (not the 216/091 Shiny; English, $300 floor)
- **Mewtwo & Mew GX SM191** — Sun & Moon Black Star Promo TAG TEAM full art (English; not the Unified Minds 71/222/236 versions; $75 floor; @mention when a PSA 10 lists under $1,500)
- **Slowpoke & Psyduck GX 218/236** — Unified Minds TAG TEAM alternate full art (English; not the 35/217/239 versions; $100 floor)
- **Blastoise & Piplup GX 215/236** — Cosmic Eclipse TAG TEAM alternate full art (English; not the 38/214/253 versions; $150 floor)
- **Magikarp & Wailord GX 161/181** — Team Up TAG TEAM alternate full art (English; not the 160/181 full art, 183/181 rainbow, Japanese Tag Bolt or Chinese 161/150; $200 floor)
- **Rayquaza V 194/203** — Evolving Skies alternate full art (not the VMAX alt art 218/203)
- **Rayquaza VMAX 218/203** — Evolving Skies alternate art secret rare (English; $300 floor; @mention when a PSA 10 lists under $1,900)
- **Rayquaza 3/17** — POP Series 1 (2004) Cosmos Holo Rare (holo only; non-holo excluded; also the zero-padded `003/017` spelling)
- **Rayquaza EX 123/124** — Dragons Exalted (2012) Full Art Ultra Rare (not the regular 85/124)
- **Rayquaza 144/BW-P Nobunaga's Ambition Promo** — **Japanese** 2012 "Pokémon + Nobunaga's Ambition" DS bonus, the black/shiny Rayquaza (keyed on `rayquaza` + `144/BW-P` or the game name, plus PSA's label wording "Black & White Promo #144 Rayquaza-Holo"; not the Rayquaza-EX `145/BW-P`, game-code event distributions or DS game bundles; $40 floor)
- **Oshawott 105/086** — **English** SV White Flare (2025) Illustration Rare (keyed on the secret-numbered `105/086`; verified no Black Bolt / other-set Oshawott shares it, so terse listings match too)
- **Espeon No.196** — **Japanese** Neo Discovery ("Crossing the Ruins") Holo Rare (not Neo Destiny "Dark Espeon" No.196, nor the non-holo Premium File promo)
- **Espeon 1/75** — **English** Neo Discovery (2001 WOTC) Holo Rare (the English counterpart of No.196; German/French/Italian prints share 1/75 and are excluded) — **also tracks PSA 9** (this watch only)
- **Karen's Umbreon 091/141** — 2001 **Japanese** Pokémon Card VS, Holo (1st Ed / Unlimited; not the 232/091 Mew or the adjacent Karen's siblings)
- **Growlithe #058 Vending Series 3** — **Japanese** 1998 Vending Machine promo, glossy (keyed on `growlithe` + `vending` + Series 3; the `58` is just Growlithe's Pokédex number)
- **Squirtle 007/018 McDonald's Promo** — **Japanese** 2002 McDonald's "Minimum Pack" e-Series Holo (keyed on `squirtle` + the full `007/018`, since bare `007` is Squirtle's Pokédex number and collides with modern cards like `007/165`)
- **Squirtle No.007 Squirtle Deck** — **Japanese** 1999 Intro Pack "Squirtle Deck" (VHS); tracks **all four** Squirtle variants (#16/#18/#37/#40, all `No.007`) via `squirtle` + the deck-name gate + `007` (the deck positions are collision-prone, so the shared dex number is the anchor)
- **Wartortle No.008 Squirtle Deck** — **Japanese** 1999 Intro Pack "Squirtle Deck"; tracks **both** Wartortle variants (#3/#10) via `wartortle` + the deck-name gate (excludes `007` so Squirtle+Wartortle combo listings fire neither watch)
- **Lugia 9/111 Neo Genesis** — **English** 2000 WOTC Holo Rare (the set's chase card; keyed on `lugia` + `neo genesis`, since `9/111`→`9111` collides with every `X9/111` card and is redundant)
- **Lugia ex 031/PLAY** — **Japanese** 2006 "Players" club 4th-season subscription promo (the *ex*-mechanic Lugia; keyed on `031/PLAY` + Players-Club/4th-Season phrases, never bare `031` or `ex`; excludes the stray-`031` Lugia confusables — Unseen Forces `105/115`, Silver Tempest `186/195`, etc.)
- **Light Arcanine No.059 Neo Destiny** — **Japanese** 2001 Holo Rare (keyed on the contiguous `light arcanine` + `059`; bare `light` would collide with "lightly played", and `059` selects the Japanese print over the English `12/105`)
- **Houndoom H11/H32 Aquapolis** — **English** 2003 WOTC e-Card Holo Rare (set name `aquapolis` is **required**: Houndoom is *also* `H11/H32` in Skyridge, so `houndoom`+`h11` alone would false-match it; excludes novelty `sticker` items)
- **Slowking H22/H32 Aquapolis** — **English** 2003 WOTC e-Card Holo Rare (`slowking`+`aquapolis`+`h22`; set name required for the shared e-Card `H`-numbering, `sticker` excluded)
- **Azumarill H4/H32 Aquapolis** — **English** 2003 WOTC e-Card Holo Rare (`azumarill`+`aquapolis`+`h4`; `h4` matches only `H4`, never `H14`/`H24`; `sticker` excluded)
- **Umbreon H29/H32 Aquapolis** — **English** 2003 WOTC e-Card Holo Rare (`umbreon`+`aquapolis`+`h29`; set name required for the shared e-Card `H`-numbering; distinct from the Karen's Umbreon VS watch)
- **Shining Gyarados 65/64 Neo Revelation** — **English** 2001 WOTC Secret Rare Holo (`shining gyarados` + `65/64`/`neo revelation`; EU-language prints excluded)
- **Charizard 100/97 EX Dragon** — **English** 2003 Secret Rare Holo (`charizard` + the full `100/97`, since bare `charizard`/`100` are collision-prone; EU prints excluded)
- **Dark Dragonair 38/110 Legendary Collection** — **English** 2002 **reverse holo** (`dark dragonair`+`38/110`+`reverse`; the regular non-reverse version is deliberately excluded per request)
- **Giratina 10/127 Platinum** — **English** 2009 Holo Rare (`giratina` + the full `10/127`; distinct from the Giratina V `186/196` price-alert watch)
- **Morty's Ninetales 020/141 Pokemon VS** — **Japanese** 2001 gym-leader set (`morty`+`ninetales`; unique name, no number needed)
- **Articuno Holo #144 Red/Green Gift Set** — **Japanese** 1998 Quick Starter Gift Set (`articuno` + the gift-set name, since bare `144` is just Articuno's Pokédex number)

> Vintage grade note: for the older Rayquaza cards (3/17, 123/124), graded copies are
> commonly **PSA 8/9**, which the house grade buckets treat as "other" and don't alert
> on — these track raw + PSA 10 / BGS 10 / BGS 9.5 / CGC 10 only.

> Language note: English Pokémon watches use `language: english`. A Pokémon card's English
> and Japanese prints have different collector numbers, but its **German/French/Italian/
> Spanish/Portuguese** prints share the English number (German PSA 10 Mew ex 232/091s were
> alerting as the English card), so the number alone doesn't gate language. "English **NOT
> Japanese**" titles still pass: negated language words are stripped before detection.
> Japanese-only cards use `language: any` (their titles often say "Japanese").
>
> Grade note: these watches track raw + PSA 10 / BGS 10 / BGS 9.5 / CGC 10. Other slab
> grades (PSA 9, BGS 9, CGC 9.5, SGC, …) bucket as "other" and don't alert.

## ☁️ Cloud deployment (primary — runs even when your PC is off)

This monitor runs in the cloud on **GitHub Actions**, so it works 24/7 regardless
of whether any local machine is on:

- **Repo:** https://github.com/cal-chan-cloud/ebay-listing-monitor (public)
- **Schedule / cadence:** `.github/workflows/monitor.yml` is triggered by cron, but
  GitHub throttles scheduled cron hard (fires land every ~2-7 h, not the 5 min requested).
  So each job **loops in two ~105-minute segments** (`--loop-for-minutes 105`, `seen.db`
  committed after each) and, when it finishes normally, **queues its own successor**
  (`gh workflow run`), so coverage is continuous (before that, the monitor sat idle ~20% of
  the time, with gaps up to 6 h). The cron stays as a backup; a cancelled or crashed job
  doesn't requeue. Passes run **back to back**: `poll_interval_seconds` (0) is the pause
  after a full pass ends, and the loop only ever sleeps until the next pass is due. Scans
  are serial (`scan_workers`: 1) behind a 2 s global request throttle
  (`min_request_interval_seconds`, +0-20% jitter), and each watch alerts as soon as its own
  searches return. From a GitHub runner ~40-50% of searches draw a 403 that the retry
  clears, so a search costs ~4-6 s (~12 searches/min from one IP); the grouped sweeps below take
  ~9 of those, and full passes the rest; each pass logs its eBay outcomes and each loop its
  measured cadence. A pushed
  config/code change goes live at the next segment boundary. For true near-zero delay, run
  the loop on an always-on host instead (see "Local setup").
- **Sweeps (near-instant pings):** every watch is also covered by a grouped **sweep** — ONE
  eBay OR search such as `(espeon,lugia,umbreon)`, newest first, 240 results, Buy It Now only —
  whose results go through each covered watch's own rules (config `sweeps`). Sweeps holding a
  price-target watch run every `sweep_priority_interval_seconds`, the rest every
  `sweep_interval_seconds` (both 30), interleaved with the full passes and between them; a
  sweep's 240 newest results span 40 minutes to weeks (measured), so nothing new falls out of
  the window between two sweeps. A sweep that fails (the 403s outlast every retry) runs again
  10 s later instead of a whole interval later. Fewer, larger groups (4, of up to 9 OR terms)
  keep every group at its interval within the request budget (~5 sweeps a minute alongside
  the full passes). Group terms are names every genuine title carries (eBay matches
  OR terms against title words literally, and returns NOTHING past ~10 alternatives in a
  group). A sweep counts as one more query of each covered watch: its first run seeds
  silently (credited on page evidence, so a quiet group's sweep isn't "fresh" forever), it
  never completes a one-time baseline, and below-asking uses the reference the watch's own
  last pass stored. eBay's listing time decides "new or backlog": a listing that went live
  under 20 minutes ago pings even on a fresh query or right after a rules change, while a
  sweep result listed over 6 hours ago slid in at the bottom of the window (another listing
  ended) and seeds silently unless it is under a price target. One sweep page pings at most 8
  new listings per watch (flood breaker). Each alert logs (and the embed shows) how long ago
  eBay says the listing went live; pass summaries report the median listed→pinged delay, and
  every ping is recorded in the `pings` table of `seen.db`.
  How fast can a ping be? eBay itself only shows a new listing in search **~3.2 minutes**
  after it goes live (measured 2026-10-21 with `tools/fresh_probe.py`, `corpus.yml
  ab_mode=fresh`: the same for every URL variant — eBay's no-cache flag, a cache-busting
  parameter, a 60-result page, a category firehose — and the RSS feed is gone), and the
  listing time it shows is rounded down to the minute (~30 s). So a ping lands ~4 minutes
  after the time eBay shows; the monitor's own share is the ~30 s wait for the next sweep.
- **Price bands:** per `price_alerts` rule, a Buy-It-Now search of the watch's
  `price_band_query` priced between the floor (`price_band_floor`, default the larger of
  `min_price` and 40% of the target) and the target, 240 results, every
  `price_band_interval_seconds` (600). Newest-first searches never see an OLD listing whose
  price was cut under target; a band does (the cut pings once, as a 🔔 price-target alert).
  Band pages come back unsorted and padded with other grades, so only listings that hit the
  rule are processed and a band only ever raises target pings (never new/drop/below-asking).
- **Full passes** of every watch's own queries (`max_queries_per_watch`) run back to back
  (`poll_interval_seconds` 0) in the remaining request budget (~15-20 min per pass), with at
  most 4 sweep/band searches between two watches so a slowed pace can't starve them: asking
  references, price drops on the newest results, health checks, and titles the sweep terms
  miss. The older per-watch priority rounds (`priority_interval_seconds`) are off (`0`) now
  that sweeps cover those watches every 30 s.
  (Note: truly-underpriced cards can still sell within seconds to snipers — this catches the
  1-3-min deals, not the sub-minute ones, which only an instant-buy bot could win.)
- **Played / damaged copies don't ping:** a raw listing whose title says Damaged/DMG, Heavily
  or Moderately Played (HP/MP), Played, Poor or creased never alerts (`"exclude_played": false`
  on a watch opts back in). Lightly Played (LP) still alerts; on slabs, condition words describe
  the case and are ignored.
- **Runner geography:** eBay localizes search results by the visitor's IP, and GitHub
  sometimes places the hosted runner outside the US (seen: Azure `mexicocentral`). eBay
  then serves a local-buyer page and the US/CA region gate matches nothing for that whole
  job (the "N listings scraped but 0 matched" health alert; every US-region runner is fine).
  So each segment runs with `--reroll-exit`: the monitor first asks Cloudflare's
  `/cdn-cgi/trace` which country its egress IP is in, and if it isn't in `egress_countries`
  (default `["US"]`), or two consecutive full scans come back broken, it exits with code 75
  and the job requeues itself (`gh workflow run`), so the next run lands on a different
  runner. At most 3 consecutive rerolls (budget resets after a healthy scan or 6h), so an
  eBay outage or layout change can't cause an endless requeue loop. A zero-match scan
  also logs, and puts in the health alert, which gate rejected the listings and where eBay
  said they were located.
- **Pings:** every ping's push text leads with price + shipping, grade, how far under the
  target/reference, Best Offer and how long ago eBay says it was listed (the embed shows
  "Listed 3 minutes ago"); a "new" match listed over 6 h ago is labelled "📜 Newly matched
  (listed N d ago)"; a listing at ≤50% of its reference carries a ⚠️ "unusually cheap" line;
  the embed adds the total with shipping and the condition the title states, and shows the
  location only when it isn't the US. Notices that need action (HEALTH DOWN, scans failing,
  watch error, watchdog alerts) @mention `notify_user`; all-clears stay silent.
- **Webhook:** stored as the encrypted GitHub Actions secret `DISCORD_WEBHOOK_URL`
  — it is **not** in the public code (`config.json`'s `discord_webhook_url` is left
  blank; the script reads the env var first).
- **State:** `seen.db` lives in the repo. When a run finds new listings it commits
  the updated `seen.db` back, so no listing is ever alerted twice.

Manage it:
```
gh workflow run monitor.yml -R cal-chan-cloud/ebay-listing-monitor     # queue a run (waits behind a
                                                                       # running job, up to ~3.6 h;
                                                                       # cancel that job to start now)
gh run list -R cal-chan-cloud/ebay-listing-monitor                     # recent runs
gh secret set DISCORD_WEBHOOK_URL -R cal-chan-cloud/ebay-listing-monitor --body "<url>"
```

**To add/change cards:** edit `config.json` and push (`git push`), or just ask.
The change takes effect on the next scheduled run.

> Notes: The local Windows Task Scheduler job has been **disabled** to avoid
> duplicate alerts (cloud is now the single source). GitHub disables scheduled
> workflows after 60 days of *zero* repo activity — the periodic `seen.db` commits
> on new listings keep it alive; if listings ever go quiet that long, click
> **Run workflow** once (or push any commit) to re-arm it.

## Local setup (optional / fallback)

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
python ebay_monitor.py            # run forever, a full scan every poll_interval_seconds (no priority tier)
python ebay_monitor.py --once     # one pass then exit  (use with Windows Task Scheduler)
python ebay_monitor.py --dry-run  # scan + print matches, send nothing, record nothing
```

**First run behavior:** the *first* time a watch runs it silently records all
current listings as "seen" so you don't get flooded — you'll only be alerted on
listings posted *after* that. To instead alert on everything already up, run once
with `--notify-existing`.

### Windows Task Scheduler (installed but DISABLED)

> ⚠️ This local task is currently **Disabled** because the cloud deployment above
> is now the primary runner. Running both would send duplicate Discord alerts.
> Re-enable with `Enable-ScheduledTask "eBay Luffy Monitor"` **only if** you also
> disable the GitHub Actions schedule. If you re-enable it, set the webhook via a
> Windows env var (`setx DISCORD_WEBHOOK_URL "<url>"`) since it's no longer in
> `config.json`.

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

- `queries` — a **list** of search phrasings, merged/deduped. Only the first
  `max_queries_per_watch` (2) are searched per scan (a request-rate cap), so put the
  strongest phrasings first. Broader/alternate wordings surface differently-titled
  listings of the same card; the require/grade filters keep them precise. (`query`, a
  single string, still works.) A query the watch has never run before (newly added,
  edited, or reordered into the window) seeds its existing listings silently on its
  first run, so query edits don't flood you with already-listed items.
- `rotate_queries` — set `true` to keep `queries[0]` pinned and **rotate** the last
  window slot through the remaining phrasings (one per scan), so every phrasing is
  searched once per cycle at the same request count. Useful for high-value watches whose
  tail phrasings find listings the first two miss (e.g. PSA-slab wording). Needs
  `max_queries_per_watch` >= 2 (the asking-price reference is computed from `queries[0]`).
  The one-time silent baselines (first-run seed, per-query seed, the seed after a rules
  edit) are only used up by a scan that could actually see the market: a scan that
  matched nothing across all watches (foreign runner, soft-block, layout break) leaves
  them pending, so the next healthy scan still seeds instead of flooding.
- `match_any` — **name-fallback / multi-signature matching.** A list of signatures;
  a listing matches if it satisfies ANY one. Each signature is a require-list (same
  format as `require`). Use one signature keyed on the card number and another on
  character-name + descriptors, so you also catch listings that number the card
  differently (e.g. O-Nami as OP06-101 *or* OP07-101) or omit the number entirely:
  ```json
  "match_any": [
    [["op06-101", "op07-101"], ["500 years", "op07"]],
    [["nami", "o-nami"], ["500 years", "op07"], ["sp", "alt art"]]
  ]
  ```
  When `match_any` is set it replaces `require`. `exclude`, lot-detection, grade and
  language filters still apply.
- `query` — what gets typed into eBay search. Keep it fairly broad; eBay
  fuzzy-matches, so use `require` to pin the exact card.
- `require` — **list of terms that must ALL appear in the title** (case- and
  punctuation-insensitive, so `op05-119` = `OP05 119` = `op05119`). This is what
  stops eBay's fuzzy search from alerting you about the wrong card. Add the
  distinguishing words too, e.g. `["op10-005", "flagship"]` to get only the
  Flagship promo and not the same-numbered base card.
- `exclude` — optional extra terms to reject. Proxies/replicas
  (`proxy`, `orica`, `custom`, `handmade`, …) and **extended-art display cases**
  (merch, not the card) are already excluded globally. Sealed product and bulk/quantity
  lots (booster box, ETB, "N cards lot", "lot of N", jumbo, …) are also detected
  centrally (`is_bulk_or_sealed`, word-boundary matched on the raw title so it can't
  misfire on things like "Holo TCG"), so watches don't need to list those per-card.
- `grades` — any of: `ungraded`, `psa10`, `bgs10`, `bgs9.5`, `cgc10`. (More can be
  added in `classify_grade()` — e.g. `psa9`, `sgc10`.)
- `language` — `english` (default), `japanese`, `chinese`, `korean`, or `any`.
- `min_price` / `max_price` — optional numeric filters (use `null` to disable).
- `allow_auctions` — set `true` to include auction listings for this watch
  (default: auctions excluded). Global default: `include_auctions` (top level).
- `allow_lots` — set `true` to include multi-card lots for this watch.
- `sealed_product` — set `true` for a **sealed boxed product** (e.g. an anniversary
  set). Rejects any listing carrying a single-card number (`OP13-120`, `ST01-012`, …),
  since those are singles pulled from the set, not the box. Pair with `grades:
  ["ungraded"]` (boxes aren't graded) and usually a `min_price` to cut cheap
  singles/accessories. The lot/sealed gates stay on (a plain "Set" passes; lots and
  bundles are still rejected).
- `allowed_regions` — per-watch region allow-list (canonical `US` / `CA`);
  overrides the top-level default `["US", "CA"]`.
- `all_regions` — set `true` to alert on sellers **anywhere** (bypasses the region
  gate entirely). Use for import-only cards (Japanese/Chinese exclusives) that are
  mostly sold overseas, where a US/CA filter would hide nearly every listing.
- `price_drop_pct` / `price_drop_min` — per-watch override of the drop thresholds.
- `priority` — set `true` to put this watch on the **fast-poll tier** (see
  `priority_interval_seconds` under "Fast tier" above). Watches with `price_alerts` are automatically on it,
  so under-target deals are detected/pinged sooner without speeding up every watch.
- `price_alerts` — per-watch list of **absolute price targets that @mention someone
  on Discord**. Each rule is `{"grade": <bucket, optional>, "below": <USD>, "mention":
  "<discord id>"}` and fires when a matched listing of that grade is priced strictly
  **below** the threshold (USD only — foreign-currency listings are never compared).
  Example — ping a user when a PSA 10 lists under $2,300:
  ```json
  "price_alerts": [
    {"grade": "psa10", "below": 2300, "mention": "209187722575872000"}
  ]
  ```
  A crossing is the *headline* alert for that listing (one message, not a duplicate
  drop/below-market ping); it pings **once per crossing** and re-arms only after the
  price rises back more than 3% above target (so a Canadian listing's exchange-rate drift
  can't re-fire it). Omit `grade` to alert on any grade. Adding or changing a rule
  re-baselines that watch's already-seen listings from their last observed prices, so an
  edit never @mentions listings that were already sitting under the new target. Every
  target hit — a brand-new listing under target, an old one cut under it, or an older
  listing a rules change newly matches (up to 3 per watch per pass) — uses the 🔔 format:
  the push text reads like `🔔 $2,050.00 +$5.99 ship · PSA 10 · $250 (10.9%) under your
  $2,300.00 target · Best Offer · listed 3 min ago · Mew ex 232/091 SIR`, with a large
  picture. `price_band_query` / `price_band_floor` tune the price-band search (see above).
  `mention` goes in the message content with `allowed_mentions`, so it actually pings;
  use a Discord **user** id (right-click → Copy User ID with Developer Mode on).

## Reliability & maintenance

- **Health check** — if a whole scan scrapes 0 listings across every watch, or eBay
  serves only unrelated/off-query result pages (a soft-block), or 3 consecutive scans
  match nothing, you get a one-time Discord ⚠️ alert (and a ✅ when it recovers). This
  is what stops a broken scraper from failing silently.
- **Watch isolation** — a watch whose config/processing raises is skipped for that pass
  (the other watches and the health check still run) and a one-time ⚠️ "Watch error"
  notice names it; one-time baselines wait until every watch has run.
- **Failures end the run as failed** — a whole pass that raises skips its own health check,
  so after two in a row a ⚠️ "scans failing" notice goes out, and a segment in which every
  full pass raised exits 1 (no green run, no self-requeue). Discord rejecting the webhook
  (401/404: deleted or rotated) also stops the run with exit 1, since nothing can alert. The
  watchdog fails its own scheduled run when it can't deliver an alert, so GitHub's
  failed-workflow email still reaches you.
- **Silent re-baselines that hold** — after a rules edit (require/match_any/exclude/grades/
  language/price window/regions, or the search location filter) a watch's already-listed
  backlog that newly matches is seeded silently, and every query of the watch re-seeds its
  own backlog on its first run under the new rules (so a rotating tail query or a 403'd
  query can't surface it as "new" later). A pass with a failed query doesn't complete the
  baseline (at most 3 such passes, so a query that keeps failing can't leave the watch blind).
- **Auto-pruning** — each listing's `last_seen` date is tracked; rows not seen in
  `prune_days` (default 30) move to a `gone` tombstone table (kept 6x `prune_days`), so
  `seen.db` stays small while a listing that resurfaces is restored with its price and
  flags instead of re-alerting as new. A watch that matched nothing in a scan keeps its
  rows (an eBay outage can't erase its memory). (`last_seen` only rewrites once/day, so
  it doesn't spam commits.)
- **Config validation** — `config.json` is checked on startup; warnings print for
  empty `queries`, a match-everything watch (no `require`/`match_any`), unknown
  grades/keys/languages, non-numeric prices, CJK-only require clauses (matching is
  ASCII-normalised, so they match everything), excludes that make a watch unmatchable,
  price targets below `min_price`, or bad region codes.
- **Tests + CI** — `tests/test_monitor.py` runs offline (grade/lot/region/price-drop/
  validation/health); `.github/workflows/tests.yml` runs it on every push.
- **Scraper resilience** — bids, location, and price are read by text pattern with
  CSS-class fallbacks, so eBay's frequent layout renames are less likely to break it.
- **Transient-error retries** — the HTTP session auto-retries connection resets and
  read timeouts, so a brief network blip doesn't drop a query for the pass. HTTP statuses
  (403 / 429 / 5xx and "Pardon Our Interruption" pages) are retried by `fetch_listings`
  instead: up to 4 attempts, each behind the global throttle, re-priming the homepage
  cookies in between (measured in CI: ~70% of retries after a re-prime succeed, ~97% of
  searches within 4 attempts; a fresh session per retry was far worse).
- **Adaptive pace** — if more than 20% of a pass's searches still fail after every retry,
  the request spacing slows 1.5x (up to 2x), easing back after passes with 10% or fewer.
  Plain 403s don't count: they hit ~40-50% of first attempts at 2 s and 3 s spacing alike.
- **Currency-aware pricing** — Canadian sellers on `ebay.com` show `C $` (CAD) and
  other regions show `£`/`€`; the scraper detects the currency so a CAD/GBP/EUR
  listing is never compared against the USD sold-median (which would fake "below
  market" deals). The sold-median itself is computed from USD sales only.
- **Grade-spelling tolerance** — `PSA-10`, `PSA10`, `BGS-9.5` (not just `PSA 10`)
  all classify correctly instead of falling through to "graded (other)".
- **Health-check debounce** — a single quiet pass where nothing matches no longer
  trips a false ⚠️ alert; the "0 matched" alarm only fires after several consecutive
  zero-match scans (`zero_match_alert_scans`, default 3). A true "0 scraped"
  (scraper blocked / layout change) still alerts immediately.
- **Log rotation** — `monitor.log` is capped (~2 MB); once it exceeds that it's
  rotated to `monitor.log.1` on the next start, so it can't grow without bound.
- **Market-price cache** — a real recent-sold median is cached ~6h, but a failed or
  too-few-comps lookup (`None`) is *not* cached, so it's retried on the next scan
  instead of leaving the card without a market price for hours.

## Market price & below-market deals

> ⚠️ **Sold comps are unavailable; deal detection now falls back to asking prices.**
> eBay requires sign-in to view sold/completed listings — an unauthenticated request
> returns a "Pardon Our Interruption" challenge or a sign-in wall, so no sold data
> can be read (verified 2026-07-24; every cached market price in the live DB was
> `null`). The monitor detects this, posts a one-time Discord notice, and trips a
> circuit breaker that parks sold lookups for 24h — repeatedly retrying a blocked
> endpoint was getting the whole session challenged, which would break the
> active-listing scrape too.
>
> **Fallback: "typical asking (active)".** Deal detection now uses a low percentile
> (default 25th) of *current asking prices* for the same card and grade, computed
> from the listings each scan already fetches — **zero extra requests, no account
> credentials**. This is a weaker signal than real sales (sellers list optimistically),
> so it demands a wider gap (`below_ask_pct`, default 10% vs 5% for sold) and every
> alert is labelled **"below asking"** with a **Typical asking (active)** field — never
> presented as a real market price. If sold data ever becomes readable again, sold
> automatically takes precedence and the labels switch back to "market".

The monitor estimates a market price **per grade bucket** from **recent eBay
sold/completed listings** (real transactions) for that exact card: for each grade
a watch tracks it takes the most-recent sales *in that same grade*, trims outliers
(damaged/junk lows and mislabeled highs), and uses the median. A PSA 10 listing is
therefore compared only against recent PSA 10 sales, a raw against recent raws, and
so on. Each bucket is cached ~6h in the DB (`market:<watch>:<grade>`), and a watch's
sold listings are fetched at most once per refresh (shared across its buckets).

- Priced buckets: **ungraded, PSA 10, BGS 10, BGS 9.5, CGC 10**. `other_graded` (a mix
  of companies/grades) is never priced — a single median across it would be meaningless.
- Every alert with a market price shows **Market (recent sold)** and the listing's **% vs market**.
- A listing priced between `below_market_floor` (default **0.5×** market — anything
  cheaper is treated as damaged/mislabeled junk, not a deal) and
  `1 − below_market_pct` (default **5%** below) is flagged a **🔥 below-market deal**.
- New below-market listings are flagged inline; an already-seen listing that *crosses*
  below market fires a distinct 🔥 alert (tracked so it never repeats).
- A bucket with too few recent sold comps simply gets no market price (no false deals).

Tune in `config.json`: `below_market_pct`, `below_market_floor` (both per-watch overridable).

**Asking-price fallback settings** (used while sold data is gated):
- `ask_percentile` (default `25`) — which percentile of active asking prices is the
  reference. Lower = stricter (fewer, better deals).
- `ask_min_listings` (default `8`) — minimum comparable active listings in a grade
  bucket before a reference is computed at all, so a thin market can't fake a "deal".
- `below_ask_pct` (default `10`, per-watch overridable) — how far under the asking
  reference a listing must be. Wider than the sold threshold because asks are noisier.
- `reference_override` (per-watch) — pin the reference for a grade to a fixed value,
  e.g. `"reference_override": {"ungraded": 75}`, when the computed asking percentile
  runs high and pings too much. Takes precedence over sold/asking and shows as
  **Reference (set)** in the alert. Below-market then fires only for prices in
  `[value × below_market_floor, value × (1 − below_ask_pct))` (so at $75 with the
  defaults, ~$37.50–$67.50).

## Price-drop alerts

Every scan records each tracked listing's price. When a listing's price falls at
least **`price_drop_pct`** (top-level, default **5%**) **and** at least
**`price_drop_min`** (default **$1**) below its last-recorded price, you get a
green **📉 price drop** alert (old → new, % off). The reference then resets to the
new price, so small wiggles don't spam you and only further drops re-alert. Price
rises never alert (so excluded-by-default auctions wouldn't trigger it anyway).

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
- `CGC 10` (incl. `CGC 10 Gem Mint` / `CGC 10 Pristine`) → CGC 10
- any other grading company/number (PSA 9, CGC 9.5, SGC, …) → *ignored* (not in your buckets)
- no grading company mentioned → Ungraded / Raw

Detection relies on sellers writing the grade in the title (standard practice for
slabs). `seen.db` (SQLite, auto-created) tracks which listings have already been
alerted so you never get a duplicate.

## Notes

- eBay bot-protection 403s a cold request, so the script first visits the eBay
  homepage to seed cookies, then re-primes automatically if a 403 appears later. From
  GitHub runners the 403s are frequent and random (~40-50% of first attempts, regardless of
  query, of 2 s vs 3 s spacing, and of a Chrome-TLS client vs `requests`; measured with
  `tools/http_ab.py` via the manual corpus workflow).
- Searches use eBay's North America location filter (`LH_PrefLoc=3`): US-only (`=1`) kept
  Canadian sellers out of the main results although CA is an allowed region.
- eBay's OR syntax (`(houndoom,slowking,azumarill,umbreon) aquapolis`) returns one newest-
  first page covering several cards (measured: 10/10 of each card's newest listings for 3
  of 4 test groups). It isn't used yet; it is the route to sub-minute coverage of every
  watch from one IP (see `tools/http_ab.py`, group mode).
- If eBay ever hard-blocks scraping, the robust alternative is the official
  [eBay Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html)
  (free dev account + OAuth) — `fetch_listings()` is the only function that would
  need swapping.
