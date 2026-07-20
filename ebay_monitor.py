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
from datetime import datetime, timedelta, timezone

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


def _require_ok(nt: str, require) -> bool:
    """AND of clauses; each clause is a string (must be present) or a list of
    alternatives (at least one must be present)."""
    for clause in (require or []):
        if isinstance(clause, (list, tuple)):
            if not any(_norm(alt) in nt for alt in clause if _norm(alt)):
                return False
        elif _norm(clause) not in nt:
            return False
    return True


def matches_filters(title: str, require, exclude, match_any=None) -> bool:
    """True if the title matches the card and hits no 'exclude' term.

    Excludes are always applied. The card is identified by either:
      - a single `require` signature (AND of clauses, each clause str or alias-list), or
      - `match_any`: a list of signatures — match if ANY one fully matches. This is
        how a name-based fallback works, e.g. one signature keyed on the card number
        and another on character-name + descriptors for listings that omit the number.
    """
    nt = _norm(title)
    for t in _DEFAULT_EXCLUDE_NORM:
        if t in nt:
            return False
    for term in (exclude or []):
        t = _norm(term)
        if t and t in nt:
            return False
    if match_any:
        return any(_require_ok(nt, sig) for sig in match_any)
    return _require_ok(nt, require)


# ---------------------------------------------------------------------------
# Seller/item region (from the listing's "Located in <country>")
# ---------------------------------------------------------------------------

def canon_region(text: str):
    """Normalize a location string to 'US', 'CA', 'OTHER', or None (unknown)."""
    low = (text or "").strip().lower()
    if not low:
        return None
    if re.search(r"\bunited states\b", low) or low in {"us", "usa", "u.s.", "u.s.a."}:
        return "US"
    if re.search(r"\bcanada\b", low) or low == "ca":
        return "CA"
    return "OTHER"


def passes_region(location, allowed, allow_unknown):
    """True if the listing's location is in `allowed` (a set of canonical codes).
    Unknown locations pass only when allow_unknown is True."""
    reg = canon_region(location)
    if reg is None:
        return allow_unknown
    return reg in allowed


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


def _fmt_price(v):
    return f"${v:,.2f}" if v is not None else "N/A"


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

        li_text = li.get_text(" ", strip=True)

        price_el = li.select_one(".s-item__price") or li.select_one(".s-card__price")
        if price_el:
            price_str, price_low = parse_price(price_el.get_text(" ", strip=True))
        else:
            # fallback: first $-amount in the card text — survives price-class renames.
            fm = re.search(r"\$[\d,]+(?:\.\d{2})?", li_text)
            price_str, price_low = parse_price(fm.group(0)) if fm else ("N/A", None)

        img_el = li.select_one("img")
        image = None
        if img_el:
            # prefer the real lazy-loaded URL; skip 1x2 spacer/data: placeholders.
            src = img_el.get("data-src") or img_el.get("src") or ""
            if src.startswith("http"):
                # bump eBay's tiny grid thumbnail (s-l140/225) up to a crisp 500px.
                image = re.sub(r"s-l\d+", "s-l500", src)

        # Bid count identifies auctions. eBay keeps renaming the CSS class
        # (.s-item__bids -> .s-card__attribute-row/.su-styled-text), so detect it
        # from the card's text instead — durable across layout changes.
        bm = re.search(r"\b(\d[\d,]*)\s+bids?\b", li_text, re.IGNORECASE)
        bids = bm.group(0) if bm else None

        # Item location, e.g. "Located in United States" -> "United States".
        location = None
        loc_node = li.find(string=re.compile(r"Located in\s+\S", re.IGNORECASE))
        if loc_node:
            location = re.sub(r"^.*?Located in\s+", "", loc_node.strip(), flags=re.IGNORECASE).strip()

        condition = (_cell_text(li, ".s-item__subtitle") or _cell_text(li, ".SECONDARY_INFO")
                     or _cell_text(li, ".s-card__subtitle"))
        # Shipping: read from card text (durable) with a legacy-selector fallback.
        sm = re.search(r"(Free (?:delivery|shipping|postage)|\+?\s*\$[\d,.]+\s*(?:delivery|shipping|postage))",
                       li_text, re.IGNORECASE)
        shipping = (" ".join(sm.group(0).split()) if sm
                    else _cell_text(li, ".s-item__shipping") or _cell_text(li, ".s-item__logisticsCost"))
        fmt = _cell_text(li, ".s-item__purchase-options-with-icon")

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
            "location": location,
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
        "  price REAL, price_str TEXT, last_seen TEXT,"
        "  PRIMARY KEY (watch, item_id))"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    # Migrate older DBs that predate later columns.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(seen)")}
    if "price" not in cols:
        conn.execute("ALTER TABLE seen ADD COLUMN price REAL")
    if "price_str" not in cols:
        conn.execute("ALTER TABLE seen ADD COLUMN price_str TEXT")
    if "last_seen" not in cols:
        conn.execute("ALTER TABLE seen ADD COLUMN last_seen TEXT")
    # Baseline last_seen (to first_seen's date) so pruning has a reference.
    conn.execute("UPDATE seen SET last_seen=substr(first_seen,1,10) WHERE last_seen IS NULL")
    conn.commit()
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(conn, key, value):
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def prune_seen(conn, days):
    """Delete seen rows not observed in `days` days (sold/ended listings)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    cur = conn.execute("DELETE FROM seen WHERE last_seen IS NOT NULL AND last_seen < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def mark_seen(conn, watch, item_id, grade, price=None, price_str=None):
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT OR IGNORE INTO seen (watch, item_id, grade, first_seen, price, price_str, last_seen) "
        "VALUES (?,?,?,?,?,?,?)",
        (watch, item_id, grade, now.isoformat(), price, price_str, now.date().isoformat()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def _post_webhook(webhook_url, payload, attempts=4):
    """POST to Discord, backing off correctly on 429 (whose body may be HTML)."""
    resp = None
    for _ in range(attempts):
        resp = requests.post(webhook_url, json=payload, timeout=20)
        if resp.status_code == 429:
            retry = None
            try:
                retry = float(resp.json().get("retry_after", 0))
            except Exception:
                pass
            if not retry:
                try:
                    retry = float(resp.headers.get("Retry-After", 1))
                except Exception:
                    retry = 1.0
            time.sleep(min(retry, 30) + 0.5)
            continue
        resp.raise_for_status()
        return
    if resp is not None:
        resp.raise_for_status()


def send_simple_discord(webhook_url, title, text, color):
    """Post a plain (non-listing) embed, e.g. a health/status alert."""
    payload = {"embeds": [{"title": title, "description": text, "color": color,
                           "timestamp": datetime.now(timezone.utc).isoformat()}]}
    _post_webhook(webhook_url, payload)


def is_auction(listing):
    """True if the listing is an auction (eBay shows a bid count on auctions only)."""
    bids = listing.get("bids") or ""
    fmt = listing.get("format") or ""
    return "bid" in bids.lower() or "bid" in fmt.lower()


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


def send_discord(webhook_url, watch_name, listing, grade,
                 event="new", old_price_str=None, drop_pct=None):
    label = GRADE_LABELS.get(grade, grade)
    emoji = GRADE_EMOJI.get(grade, "•")
    company = GRADE_COMPANY.get(grade, "—")
    price = listing.get("price_str") or "N/A"
    url = listing["url"]
    shipping = listing.get("shipping")

    if event == "drop":
        # Price-drop styling: green, struck-through old price, % off.
        color = 0x2E7D32
        author = f"📉  Price drop · {watch_name}"
        foot = "eBay · price drop"
        content = f"📉 **{watch_name}** — price drop {old_price_str} → {price}" + (
            f"  (−{drop_pct}%)" if drop_pct else "")
        pct_bit = f"  ·  **−{drop_pct}% off**" if drop_pct else ""
        headline = f"## {price}   ~~{old_price_str}~~{pct_bit}\n" if price != "N/A" else ""
    else:
        color = GRADE_COLORS.get(grade, 0x2F3136)
        author = f"🆕  {watch_name}"
        foot = "eBay · newly listed"
        content = f"{emoji} **{watch_name}** — {label} · {price}"
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
    if listing.get("location"):
        fields.append({"name": "Location", "value": f"📍 {listing['location'][:78]}", "inline": True})

    embed = {
        "author": {"name": author},
        "title": listing["title"][:250],
        "url": url,
        "color": color,
        "description": description,
        "fields": fields,
        "footer": {"text": f"{foot} · #{listing.get('item_id', '')}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if listing.get("image"):
        embed["thumbnail"] = {"url": listing["image"]}

    payload = {
        "content": content,
        "embeds": [embed],
    }
    _post_webhook(webhook_url, payload)


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
    # A price drop alerts when the price falls at least this % AND this many $
    # below the last-recorded price (per-watch overridable).
    cfg_drop_pct = float(cfg.get("price_drop_pct", 5))
    cfg_drop_min = float(cfg.get("price_drop_min", 1))
    # Only alert for listings located in these regions (default US + Canada).
    cfg_regions = {canon_region(x) for x in cfg.get("allowed_regions", ["US", "CA"])}
    cfg_regions.discard(None)
    cfg_allow_unknown_region = bool(cfg.get("allow_unknown_region", False))
    prune_days = int(cfg.get("prune_days", 30))
    total_scraped = 0
    total_matched = 0

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
        total_scraped += len(listings)

        # Load this watch's seen items as {item_id: (last_price, last_price_str)}
        # in one query (also serves as the dedup set).
        seen_prices = {row[0]: (row[1], row[2]) for row in
                       conn.execute("SELECT item_id, price, price_str FROM seen WHERE watch=?", (name,))}

        # Seed silently (mark matches seen, no alerts) on a watch's first run, or
        # whenever --reseed is used (e.g. after broadening filters, to avoid a flood
        # of alerts for listings that were already up but newly match).
        seeding = reseed or (not seen_prices and not notify_existing and not dry_run)
        matched = new_count = drop_count = 0
        lang_pref = watch.get("language", "english")
        require = watch.get("require", [])
        exclude = watch.get("exclude", [])
        match_any = watch.get("match_any")
        allow_lots = watch.get("allow_lots", False)
        allow_auctions = watch.get("allow_auctions", cfg.get("include_auctions", False))
        drop_pct = float(watch.get("price_drop_pct", cfg_drop_pct))
        drop_min = float(watch.get("price_drop_min", cfg_drop_min))
        if "allowed_regions" in watch:
            regions = {canon_region(x) for x in watch["allowed_regions"]}
            regions.discard(None)
        else:
            regions = cfg_regions
        allow_unknown_region = bool(watch.get("allow_unknown_region", cfg_allow_unknown_region))
        to_seed = []          # brand-new items to bulk-insert
        price_updates = []    # (price, price_str, item_id) baselines / post-drop
        refresh_ids = []      # seen items observed this scan (refresh last_seen)
        now_iso = datetime.now(timezone.utc).isoformat()
        today = now_iso[:10]

        for lst in listings:
            if is_lot(lst["title"]) and not allow_lots:
                continue
            if is_auction(lst) and not allow_auctions:
                continue
            if not passes_region(lst.get("location"), regions, allow_unknown_region):
                continue
            if not matches_filters(lst["title"], require, exclude, match_any):
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
            cur = lst["price_low"]
            cur_str = lst["price_str"]

            # ---- already-seen listing: watch for a price drop ----
            if item_id in seen_prices:
                ref_price, ref_str = seen_prices[item_id]
                if dry_run:
                    if (ref_price is not None and cur is not None
                            and cur <= ref_price * (1 - drop_pct / 100)
                            and (ref_price - cur) >= drop_min):
                        pct = round((ref_price - cur) / ref_price * 100)
                        print(f"[DRY][DROP] [{name}] {ref_str or _fmt_price(ref_price)} -> {cur_str} ({pct}%)  {lst['url']}")
                    continue
                refresh_ids.append(item_id)   # observed today -> keep alive from pruning
                if ref_price is None or seeding:
                    # baseline the price (migration / reseed) — never alert
                    if cur is not None:
                        price_updates.append((cur, cur_str, item_id))
                        seen_prices[item_id] = (cur, cur_str)
                    continue
                if cur is None:
                    continue
                if cur <= ref_price * (1 - drop_pct / 100) and (ref_price - cur) >= drop_min:
                    pct = round((ref_price - cur) / ref_price * 100)
                    old_str = ref_str or _fmt_price(ref_price)
                    if not webhook or webhook.startswith("PASTE_"):
                        print(f"[{ts}] [{name}] PRICE DROP {old_str} -> {cur_str} {lst['url']} (no webhook)")
                    else:
                        try:
                            send_discord(webhook, name, lst, grade, event="drop",
                                         old_price_str=old_str, drop_pct=pct)
                            print(f"[{ts}] [{name}] price drop: {old_str} -> {cur_str} ({pct}%) {lst['url']}")
                        except Exception as e:
                            print(f"[{ts}] [{name}] discord error: {e}", file=sys.stderr)
                            continue  # keep old ref; retry next pass
                    # Rebaseline immediately (commit now) so a crash can't re-send this drop.
                    conn.execute("UPDATE seen SET price=?, price_str=?, last_seen=? WHERE watch=? AND item_id=?",
                                 (cur, cur_str, today, name, item_id))
                    conn.commit()
                    seen_prices[item_id] = (cur, cur_str)
                    drop_count += 1
                    time.sleep(0.4)
                continue

            # ---- brand-new listing ----
            seen_prices[item_id] = (cur, cur_str)
            if dry_run:
                print(f"[DRY] [{name}] {GRADE_LABELS[grade]:16} {cur_str:>12}  {lst['title'][:70]}  {lst['url']}")
                new_count += 1
                continue
            if seeding:
                to_seed.append((name, item_id, grade, now_iso, cur, cur_str, today))
                continue
            if not webhook or webhook.startswith("PASTE_"):
                print(f"[{ts}] [{name}] NEW {GRADE_LABELS[grade]} {cur_str} {lst['url']} "
                      f"(no webhook configured — not sent)")
            else:
                try:
                    send_discord(webhook, name, lst, grade)
                    print(f"[{ts}] [{name}] notified: {GRADE_LABELS[grade]} {cur_str} {lst['url']}")
                except Exception as e:
                    print(f"[{ts}] [{name}] discord error: {e}", file=sys.stderr)
                    seen_prices.pop(item_id, None)  # don't mark seen so we retry next pass
                    continue
            mark_seen(conn, name, item_id, grade, cur, cur_str)
            new_count += 1
            time.sleep(0.4)  # be gentle with the webhook

        # Batch DB writes: bulk-insert new seeds, bulk-update changed prices,
        # and refresh last_seen (only rewrites rows whose date actually changed,
        # so this churns the DB at most once per day).
        if to_seed:
            conn.executemany(
                "INSERT OR IGNORE INTO seen (watch, item_id, grade, first_seen, price, price_str, last_seen) "
                "VALUES (?,?,?,?,?,?,?)", to_seed)
        if price_updates:
            conn.executemany(
                "UPDATE seen SET price=?, price_str=? WHERE watch=? AND item_id=?",
                [(p, s, name, i) for (p, s, i) in price_updates])
        if refresh_ids:
            conn.executemany(
                "UPDATE seen SET last_seen=? WHERE watch=? AND item_id=? "
                "AND (last_seen IS NULL OR last_seen<>?)",
                [(today, name, i, today) for i in refresh_ids])
        if to_seed or price_updates or refresh_ids:
            conn.commit()

        if seeding:
            print(f"[{ts}] [{name}] first run: seeded {len(to_seed)} existing matched listing(s) as seen (no alerts).")
        else:
            print(f"[{ts}] [{name}] {len(listings)} scraped, {matched} matched, "
                  f"{new_count} new, {drop_count} price drop(s).")
        total_matched += matched

    # --- after all watches: prune stale rows + health check on the whole scan ---
    if not dry_run:
        pruned = prune_seen(conn, prune_days)
        if pruned:
            print(f"[{ts}] pruned {pruned} stale seen row(s) not seen in > {prune_days}d.")

    if not dry_run and not reseed:
        watches = cfg.get("watches", [])
        healthy = (total_scraped > 0 and total_matched > 0) or not watches
        prev = meta_get(conn, "health", "ok")
        if not healthy and prev == "ok":
            meta_set(conn, "health", "down")
            if total_scraped == 0:
                msg = (f"0 listings scraped across all {len(watches)} watch(es) — eBay may be blocking "
                       "the scraper or changed its page layout.")
            else:
                msg = (f"{total_scraped} listings scraped but 0 matched any watch — a filter, the region "
                       "filter, or an eBay layout change likely broke matching.")
            msg += " No alerts will fire until this recovers."
            print(f"[{ts}] HEALTH DOWN: {msg}", file=sys.stderr)
            if webhook and not webhook.startswith("PASTE_"):
                try:
                    send_simple_discord(webhook, "⚠️ eBay monitor health", msg, 0xB71C1C)
                except Exception as e:
                    print(f"health alert error: {e}", file=sys.stderr)
        elif healthy and prev == "down":
            meta_set(conn, "health", "ok")
            print(f"[{ts}] HEALTH RECOVERED.")
            if webhook and not webhook.startswith("PASTE_"):
                try:
                    send_simple_discord(webhook, "✅ eBay monitor recovered",
                                        "Scraping is working again — alerts resume.", 0x2E7D32)
                except Exception as e:
                    print(f"health alert error: {e}", file=sys.stderr)


def validate_config(cfg):
    """Print warnings for likely-misconfigured watches. Returns the warning list."""
    warnings = []
    watches = cfg.get("watches", [])
    if not watches:
        warnings.append("no watches configured")
    valid_grades = set(GRADE_LABELS)
    for i, w in enumerate(watches):
        tag = w.get("name") or f"watch #{i}"
        if not (w.get("queries") or w.get("query")):
            warnings.append(f"{tag}: no 'queries'/'query' to search")
        if not w.get("require") and not w.get("match_any"):
            warnings.append(f"{tag}: no 'require'/'match_any' — would match EVERY search result")
        if not w.get("grades"):
            warnings.append(f"{tag}: no 'grades' — nothing will match")
        for g in w.get("grades", []):
            if g.lower().replace(" ", "") not in valid_grades:
                warnings.append(f"{tag}: unknown grade {g!r}")
        for r in w.get("allowed_regions", []):
            if canon_region(r) in (None, "OTHER"):
                warnings.append(f"{tag}: unrecognized region {r!r} (use US/CA)")
    for r in cfg.get("allowed_regions", []):
        if canon_region(r) in (None, "OTHER"):
            warnings.append(f"top-level allowed_regions: unrecognized region {r!r}")
    for wmsg in warnings:
        print(f"config warning: {wmsg}", file=sys.stderr)
    return warnings


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
    validate_config(cfg)
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
