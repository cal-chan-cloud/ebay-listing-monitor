#!/usr/bin/env python3
"""
eBay new-listing monitor -> Discord notifications.

Scrapes eBay's "newly listed" search results for one or more watches, classifies
each listing by grade bucket (ungraded / PSA 10 / BGS 10 / BGS 9.5 / other),
and posts a Discord webhook notification for each *new* listing that matches a
watch's wanted grade buckets.

Usage:
    python ebay_monitor.py            # loop forever at config poll interval
    python ebay_monitor.py --once     # single pass then exit (for Task Scheduler / cron)
    python ebay_monitor.py --dry-run  # scan + print matches, send nothing, don't record as seen
    python ebay_monitor.py --notify-existing   # on first run, notify for listings already up
"""

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
DB_PATH = os.path.join(HERE, "seen.db")
LOG_PATH = os.path.join(HERE, "monitor.log")


class _Tee:
    """Write stdout/stderr to both the console and a rolling log file.

    Lets the scheduled task (launched via pythonw with no console) still leave a
    debuggable trail in monitor.log.
    """

    def __init__(self, stream, logfile):
        self.stream = stream
        self.logfile = logfile

    def write(self, data):
        try:
            if self.stream:
                self.stream.write(data)
        except Exception:
            pass
        try:
            self.logfile.write(data)
            self.logfile.flush()
        except Exception:
            pass

    def flush(self):
        for s in (self.stream, self.logfile):
            try:
                if s:
                    s.flush()
            except Exception:
                pass


def enable_file_logging():
    try:
        f = open(LOG_PATH, "a", encoding="utf-8")
        sys.stdout = _Tee(sys.stdout, f)
        sys.stderr = _Tee(sys.stderr, f)
    except Exception as e:
        print(f"could not open log file: {e}", file=sys.stderr)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}

# eBay's bot protection 403s a cold request; visiting the homepage first seeds the
# cookies needed for search pages to return 200. We keep one session and re-prime
# it if a search ever comes back forbidden.
_SESSION = None


def get_session(domain: str):
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(HEADERS)
        prime_session(domain)
    return _SESSION


def prime_session(domain: str):
    try:
        _SESSION.get(f"https://{domain}/", timeout=25)
    except Exception as e:
        print(f"session prime warning: {e}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Grade classification
# ---------------------------------------------------------------------------

# Unambiguous grader tokens — their mere presence means the card is slabbed.
GRADING_COMPANIES = [
    "PSA", "BGS", "BECKETT", "CGC", "SGC", "GMA", "HGA", "KSA"
]

# Buckets we can detect. Order matters: check specific grades first.
_PSA10 = re.compile(r"\bPSA\s*10\b")
_BGS95 = re.compile(r"\b(?:BGS|BECKETT)\s*9\.5\b")
_BGS10 = re.compile(r"\b(?:BGS|BECKETT)\s*10\b")
# "is this graded at all?" — an unambiguous company token anywhere in the title.
_GRADED_HINT = re.compile(
    r"\b(?:" + "|".join(GRADING_COMPANIES) + r")\b", re.IGNORECASE
)
# ACE, TAG and ARS are real third-party graders but collide with the character
# "Ace", the word "tag", and common letters, so only count them as graders when
# immediately followed by a grade number ("ACE 10", "TAG 9.5", "ARS 10"). Bare
# "Portgas D. Ace" / "with tag" stay ungraded.
_GRADED_NUM = re.compile(r"\b(?:ACE|TAG|ARS)\s*(?:10|\d(?:\.\d)?)\b", re.IGNORECASE)


def classify_grade(title: str) -> str:
    """Return a bucket key: 'psa10', 'bgs10', 'bgs9.5', 'other_graded', or 'ungraded'."""
    t = title.upper()
    if _PSA10.search(t):
        return "psa10"
    if _BGS95.search(t):
        return "bgs9.5"
    if _BGS10.search(t):
        return "bgs10"
    if _GRADED_HINT.search(title) or _GRADED_NUM.search(title):
        return "other_graded"
    return "ungraded"


# ---------------------------------------------------------------------------
# Language detection (English-only by default)
# ---------------------------------------------------------------------------

# CJK / full-width characters -> definitely a Japanese/Chinese/Korean listing.
_CJK = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿＀-￯]")
_LANG_JP = re.compile(r"\b(japanese|japan|jpn|jp)\b", re.IGNORECASE)
_LANG_CN = re.compile(r"\b(chinese|china|chn|cn)\b", re.IGNORECASE)
_LANG_KR = re.compile(r"\b(korean|korea|kor)\b", re.IGNORECASE)
_LANG_EN = re.compile(r"\b(english|eng)\b", re.IGNORECASE)


def title_language(title: str) -> str:
    """Best-effort language of a listing from its title.

    Returns 'english', 'japanese', 'chinese', 'korean', 'cjk' (foreign but
    unspecified), or 'unknown' (no language marker at all).
    """
    # Explicit word markers win over raw script detection (a listing can contain
    # CJK but explicitly say "Japanese").
    if _LANG_CN.search(title):
        return "chinese"
    if _LANG_JP.search(title):
        return "japanese"
    if _LANG_KR.search(title):
        return "korean"
    if _CJK.search(title):
        return "cjk"
    if _LANG_EN.search(title):
        return "english"
    return "unknown"


def passes_language(title: str, want: str) -> bool:
    """Does this listing match the watch's desired language?

    'english' (default): keep English + unmarked listings; drop anything flagged
    Japanese/Chinese/Korean/CJK. 'any': keep everything.
    """
    want = (want or "english").lower()
    if want == "any":
        return True
    lang = title_language(title)
    if want == "english":
        return lang in ("english", "unknown")
    if want == "japanese":
        return lang in ("japanese", "cjk")
    if want == "chinese":
        return lang in ("chinese", "cjk")
    if want == "korean":
        return lang in ("korean", "cjk")
    return True


# ---------------------------------------------------------------------------
# Title matching: card-number verification + junk/fake exclusion
# ---------------------------------------------------------------------------

# eBay fuzzy-matches card numbers, so a watch should list the exact identifier(s)
# in "require" (ALL must appear). These are dropped everywhere by default — they're
# proxies / replicas, not real singles.
DEFAULT_EXCLUDE = ["proxy", "orica", "oricard", "custommade", "handmade", "metalcard", "sealedbooster"]


def _norm(s: str) -> str:
    """Lowercase and strip non-alphanumerics so 'OP05-119' == 'op05 119' == 'op05119'."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Normalize the constant exclude list once, not per-listing.
_DEFAULT_EXCLUDE_NORM = [_norm(t) for t in DEFAULT_EXCLUDE if _norm(t)]


# A title with 2+ *distinct* card numbers (e.g. "OP12-015 + ST26-005 + OP02-062")
# is a multi-card lot/bundle, not the single card a watch is tracking. We require
# the dash form (OP06-101) — real lots use it, and it avoids false hits on set
# code + year adjacency like "OP15 2026".
_CARDNUM_RE = re.compile(r"\b[a-z]{2,4}\d{1,2}-\d{2,4}\b", re.IGNORECASE)


def is_lot(title: str) -> bool:
    """True if the title references two or more different card numbers."""
    nums = {m.lower() for m in _CARDNUM_RE.findall(title)}
    return len(nums) >= 2


def matches_filters(title: str, require, exclude) -> bool:
    """True if the title satisfies every 'require' clause and no 'exclude' term.

    Each 'require' clause is either a string (the title must contain it) or a list
    of alternatives (the title must contain AT LEAST ONE of them) — so a clause
    like ["500 years", "op07"] matches either phrasing of the same card.
    """
    nt = _norm(title)
    for clause in (require or []):
        if isinstance(clause, (list, tuple)):
            if not any(_norm(alt) in nt for alt in clause if _norm(alt)):
                return False
        elif _norm(clause) not in nt:
            return False
    for t in _DEFAULT_EXCLUDE_NORM:
        if t in nt:
            return False
    for term in (exclude or []):
        t = _norm(term)
        if t and t in nt:
            return False
    return True


GRADE_LABELS = {
    "psa10": "PSA 10",
    "bgs10": "BGS 10",
    "bgs9.5": "BGS 9.5",
    "other_graded": "Graded (other)",
    "ungraded": "Ungraded / Raw",
}

GRADE_COLORS = {
    "psa10": 0xD32F2F,      # red
    "bgs10": 0x1565C0,      # blue
    "bgs9.5": 0x00897B,     # teal
    "other_graded": 0x8E24AA,  # purple
    "ungraded": 0x616161,   # grey
}

GRADE_EMOJI = {
    "psa10": "🔴",
    "bgs10": "🔵",
    "bgs9.5": "🟢",
    "other_graded": "🟣",
    "ungraded": "⚪",
}

GRADE_COMPANY = {
    "psa10": "PSA",
    "bgs10": "BGS (Beckett)",
    "bgs9.5": "BGS (Beckett)",
    "other_graded": "Graded",
    "ungraded": "Raw / Ungraded",
}

# ---------------------------------------------------------------------------
# eBay scraping
# ---------------------------------------------------------------------------

ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d{9,})")

# eBay appends accessibility/boilerplate noise to the scraped title text.
_TITLE_NOISE = re.compile(r"\s*Opens in a new window or tab\s*", re.IGNORECASE)


def clean_title(title: str) -> str:
    """Strip eBay boilerplate ('New Listing', 'Opens in a new window or tab') and
    collapse whitespace to a single clean line."""
    title = re.sub(r"^\s*New Listing\s*", "", title, flags=re.IGNORECASE)
    title = _TITLE_NOISE.sub(" ", title)
    return re.sub(r"\s+", " ", title).strip()


def _cell_text(li, selector):
    """Collapsed text of the first element matching selector inside li, or None."""
    e = li.select_one(selector)
    if not e:
        return None
    val = " ".join(e.get_text(" ", strip=True).split())
    return val or None


def build_search_url(domain: str, query: str) -> str:
    # _sop=10 -> sort by "newly listed"; LH_BIN not forced so auctions show too.
    params = {
        "_nkw": query,
        "_sop": "10",     # newest first
        "_ipg": "60",     # items per page
    }
    return f"https://{domain}/sch/i.html?" + urlencode(params)


def parse_price(text: str):
    """Return (display_string, low_float_or_None)."""
    text = " ".join(text.split())
    m = re.search(r"[\d,]+\.?\d*", text.replace("$", ""))
    low = float(m.group(0).replace(",", "")) if m else None
    return text, low


def _looks_blocked(text: str) -> bool:
    """eBay's soft block ('Pardon Our Interruption') returns HTTP 200 with no
    listings — detect it so we can re-prime and retry instead of reporting 0."""
    low = text.lower()
    return ("pardon our interruption" in low) or ("s-item__link" not in text and "s-card" not in text and len(text) < 60000)


def fetch_listings(domain: str, query: str, max_attempts: int = 4):
    """Return a list of dicts: {item_id, title, price_str, price_low, url}.

    Retries through eBay's 403 and 'Pardon Our Interruption' soft-block pages,
    re-priming cookies between attempts.
    """
    url = build_search_url(domain, query)
    session = get_session(domain)

    html_text = None
    for attempt in range(1, max_attempts + 1):
        resp = session.get(url, timeout=25)
        if resp.status_code == 403 or _looks_blocked(resp.text):
            if attempt < max_attempts:
                prime_session(domain)
                time.sleep(1.5 * attempt)
                continue
            resp.raise_for_status()  # give a real error if it was a 403
            print(f"warning: eBay soft-block persisted after {max_attempts} attempts", file=sys.stderr)
            return []
        html_text = resp.text
        break

    soup = BeautifulSoup(html_text, "html.parser")

    listings = []
    seen_ids = set()
    for li in soup.select("li.s-item, li.s-card"):
        link_el = li.select_one("a.s-item__link") or li.select_one("a[href*='/itm/']")
        if not link_el or not link_el.get("href"):
            continue
        href = link_el["href"].split("?")[0]
        id_match = ITEM_ID_RE.search(href)
        if not id_match:
            continue
        item_id = id_match.group(1)
        if item_id in seen_ids:
            continue

        title_el = (
            li.select_one(".s-item__title")
            or li.select_one(".s-card__title")
            or link_el
        )
        title = html.unescape(title_el.get_text(" ", strip=True)) if title_el else ""
        title = clean_title(title)
        # eBay injects a placeholder "Shop on eBay" card — skip it.
        if not title or title.lower() == "shop on ebay":
            continue

        price_el = li.select_one(".s-item__price") or li.select_one(".s-card__price")
        price_str, price_low = parse_price(price_el.get_text(" ", strip=True)) if price_el else ("N/A", None)

        img_el = li.select_one("img")
        image = None
        if img_el:
            image = img_el.get("src") or img_el.get("data-src")
        if image:
            # bump eBay's tiny grid thumbnail (s-l140/225) up to a crisp 500px.
            image = re.sub(r"s-l\d+", "s-l500", image)

        condition = _cell_text(li, ".s-item__subtitle") or _cell_text(li, ".SECONDARY_INFO")
        shipping = _cell_text(li, ".s-item__shipping") or _cell_text(li, ".s-item__logisticsCost")
        bids = _cell_text(li, ".s-item__bids") or _cell_text(li, ".s-item__bidCount")
        fmt = (_cell_text(li, ".s-item__purchase-options-with-icon")
               or _cell_text(li, ".s-item__dynamic.s-item__buyItNowOption"))

        seen_ids.add(item_id)
        listings.append({
            "item_id": item_id,
            "title": title,
            "price_str": price_str,
            "price_low": price_low,
            "url": f"https://{domain}/itm/{item_id}",
            "image": image,
            "condition": condition,
            "shipping": shipping,
            "bids": bids,
            "format": fmt,
        })
    return listings


def fetch_all(domain: str, watch: dict, delay: float = 0.6):
    """Fetch a watch across all its search phrasings and merge+dedupe by item id.

    A watch may set "queries" (a list) to search several wordings; falls back to
    the single "query". Broader/alternate searches surface differently-worded
    listings of the same card, which the require/grade filters then keep precise.
    """
    queries = watch.get("queries") or ([watch["query"]] if watch.get("query") else [])
    merged = {}
    for i, q in enumerate(queries):
        if i:
            time.sleep(delay)  # be gentle between searches
        try:
            for lst in fetch_listings(domain, q):
                merged.setdefault(lst["item_id"], lst)
        except Exception as e:
            print(f"[{watch.get('name','?')}] query {q!r} error: {e}", file=sys.stderr)
    return list(merged.values())


# ---------------------------------------------------------------------------
# Seen-listing store
# ---------------------------------------------------------------------------

def db_connect():
    # timeout lets a run wait out a lock instead of erroring if a manual run
    # overlaps the scheduled one.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        "  watch TEXT, item_id TEXT, grade TEXT, first_seen TEXT,"
        "  PRIMARY KEY (watch, item_id))"
    )
    return conn


def is_seen(conn, watch, item_id):
    cur = conn.execute("SELECT 1 FROM seen WHERE watch=? AND item_id=?", (watch, item_id))
    return cur.fetchone() is not None


def mark_seen(conn, watch, item_id, grade):
    conn.execute(
        "INSERT OR IGNORE INTO seen (watch, item_id, grade, first_seen) VALUES (?,?,?,?)",
        (watch, item_id, grade, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def watch_has_history(conn, watch):
    cur = conn.execute("SELECT 1 FROM seen WHERE watch=? LIMIT 1", (watch,))
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def _listing_type(listing):
    """Human-readable buying format, e.g. 'Auction · 5 bids' or 'Buy It Now · Best Offer'."""
    bids = listing.get("bids")
    fmt = (listing.get("format") or "").lower()
    if bids:
        return f"🔨 Auction · {bids}"
    if "best offer" in fmt:
        return "🏷️ Buy It Now · or Best Offer"
    if "buy it now" in fmt or "buy-it-now" in fmt:
        return "🏷️ Buy It Now"
    if listing.get("format"):
        return listing["format"]
    return None


def send_discord(webhook_url, watch_name, listing, grade):
    label = GRADE_LABELS.get(grade, grade)
    color = GRADE_COLORS.get(grade, 0x2F3136)
    emoji = GRADE_EMOJI.get(grade, "•")
    company = GRADE_COMPANY.get(grade, "—")
    price = listing.get("price_str") or "N/A"
    url = listing["url"]
    shipping = listing.get("shipping")

    # Headline: big price (with shipping suffix when known), grade badge, CTA link.
    price_bit = f"## {price}" + (f"  ·  _{shipping}_" if shipping else "")
    headline = f"{price_bit}\n" if price != "N/A" else ""
    description = (
        f"{headline}"
        f"{emoji} **{label}**  ·  {company}\n\n"
        f"**[View listing on eBay  ↗]({url})**"
    )

    # Secondary details, only shown when eBay provided them.
    fields = []
    ltype = _listing_type(listing)
    if ltype:
        fields.append({"name": "Format", "value": ltype[:80], "inline": True})
    if listing.get("condition"):
        fields.append({"name": "Condition", "value": listing["condition"][:80], "inline": True})

    embed = {
        "author": {"name": f"🆕  {watch_name}"},
        "title": listing["title"][:250],
        "url": url,
        "color": color,
        "description": description,
        "fields": fields,
        "footer": {"text": f"eBay · newly listed · #{listing.get('item_id', '')}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if listing.get("image"):
        embed["thumbnail"] = {"url": listing["image"]}

    # content drives the mobile/desktop push preview — make it self-contained.
    payload = {
        "content": f"{emoji} **{watch_name}** — {label} · {price}",
        "embeds": [embed],
    }
    resp = requests.post(webhook_url, json=payload, timeout=20)
    # Discord returns 204 on success; 429 = rate limited.
    if resp.status_code == 429:
        retry = resp.json().get("retry_after", 1)
        time.sleep(float(retry) + 0.5)
        resp = requests.post(webhook_url, json=payload, timeout=20)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def price_ok(price_low, watch):
    lo, hi = watch.get("min_price"), watch.get("max_price")
    if price_low is None:
        return True  # can't tell (e.g. auction range) -> don't filter out
    if lo is not None and price_low < lo:
        return False
    if hi is not None and price_low > hi:
        return False
    return True


def scan_once(cfg, conn, dry_run=False, notify_existing=False, reseed=False):
    # Prefer the env var (used by the cloud/GitHub Actions deploy so the webhook
    # stays out of the public repo); fall back to config.json for local runs.
    webhook = os.environ.get("DISCORD_WEBHOOK_URL") or cfg.get("discord_webhook_url", "")
    domain = cfg.get("ebay_domain", "www.ebay.com")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for watch in cfg.get("watches", []):
        name = watch["name"]
        wanted = set(g.lower() for g in watch.get("grades", []))
        # normalise "bgs9.5" vs "bgs 9.5"
        wanted = {g.replace(" ", "") for g in wanted}

        try:
            listings = fetch_all(domain, watch)
        except Exception as e:
            print(f"[{ts}] [{name}] fetch error: {e}", file=sys.stderr)
            continue

        # Load this watch's already-seen ids in a single query, then dedup in
        # memory (cheaper than a SELECT per listing).
        seen_ids = {row[0] for row in
                    conn.execute("SELECT item_id FROM seen WHERE watch=?", (name,))}

        # Seed silently (mark matches seen, no alerts) on a watch's first run, or
        # whenever --reseed is used (e.g. after broadening filters, to avoid a flood
        # of alerts for listings that were already up but newly match).
        seeding = reseed or (not seen_ids and not notify_existing and not dry_run)
        matched = 0
        new_count = 0
        lang_pref = watch.get("language", "english")
        require = watch.get("require", [])
        exclude = watch.get("exclude", [])
        to_seed = []
        now_iso = datetime.now(timezone.utc).isoformat()

        allow_lots = watch.get("allow_lots", False)
        for lst in listings:
            if is_lot(lst["title"]) and not allow_lots:
                continue
            if not matches_filters(lst["title"], require, exclude):
                continue
            grade = classify_grade(lst["title"])
            if grade not in wanted:
                continue
            if not passes_language(lst["title"], lang_pref):
                continue
            if not price_ok(lst["price_low"], watch):
                continue
            matched += 1

            item_id = lst["item_id"]
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            if dry_run:
                print(f"[DRY] [{name}] {GRADE_LABELS[grade]:16} {lst['price_str']:>12}  {lst['title'][:70]}  {lst['url']}")
                new_count += 1
                continue

            if seeding:
                to_seed.append((name, item_id, grade, now_iso))
                continue

            # Genuinely new + wanted -> notify.
            if not webhook or webhook.startswith("PASTE_"):
                print(f"[{ts}] [{name}] NEW {GRADE_LABELS[grade]} {lst['price_str']} {lst['url']} "
                      f"(no webhook configured — not sent)")
            else:
                try:
                    send_discord(webhook, name, lst, grade)
                    print(f"[{ts}] [{name}] notified: {GRADE_LABELS[grade]} {lst['price_str']} {lst['url']}")
                except Exception as e:
                    print(f"[{ts}] [{name}] discord error: {e}", file=sys.stderr)
                    seen_ids.discard(item_id)  # don't mark seen so we retry next pass
                    continue
            mark_seen(conn, name, item_id, grade)
            new_count += 1
            time.sleep(0.4)  # be gentle with the webhook

        # Batch the first-run seeding into one transaction (one commit, not N).
        if to_seed:
            conn.executemany(
                "INSERT OR IGNORE INTO seen (watch, item_id, grade, first_seen) VALUES (?,?,?,?)",
                to_seed,
            )
            conn.commit()

        if seeding:
            print(f"[{ts}] [{name}] first run: seeded {len(to_seed)} existing matched listing(s) as seen (no alerts).")
        else:
            print(f"[{ts}] [{name}] {len(listings)} scraped, {matched} matched wanted grades, {new_count} new.")


def main():
    ap = argparse.ArgumentParser(description="eBay -> Discord new listing monitor")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--dry-run", action="store_true", help="scan + print, send nothing, record nothing")
    ap.add_argument("--notify-existing", action="store_true",
                    help="on a watch's first run, alert for listings already up (default: seed silently)")
    ap.add_argument("--reseed", action="store_true",
                    help="mark all current matches as seen without alerting (run after broadening "
                         "filters/queries so already-listed items don't flood you)")
    args = ap.parse_args()

    enable_file_logging()
    cfg = load_config()
    conn = db_connect()

    if args.once or args.dry_run or args.reseed:
        scan_once(cfg, conn, dry_run=args.dry_run,
                  notify_existing=args.notify_existing, reseed=args.reseed)
        return

    interval = int(cfg.get("poll_interval_seconds", 300))
    print(f"Starting eBay monitor. Interval={interval}s. Watches={[w['name'] for w in cfg['watches']]}")
    while True:
        try:
            scan_once(cfg, conn, notify_existing=args.notify_existing)
        except Exception as e:
            print(f"scan error: {e}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    main()
