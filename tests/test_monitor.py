#!/usr/bin/env python3
"""Offline regression tests for ebay_monitor (no network). Run: python tests/test_monitor.py

Covers grade classification, language, card/lot/auction/region filters, price
parsing, config validation, and the end-to-end new-listing + price-drop logic in
scan_once (with fetch/Discord mocked and a temp DB).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_monitor as m

# Real fetch_all captured before any test mocks m.fetch_all (it calls the module-global
# fetch_listings by name, so patching m.fetch_listings still applies to this reference).
_REAL_FETCH_ALL = m.fetch_all
# Other real functions later tests need after earlier sections mocked them.
_REAL = {k: getattr(m, k) for k in ("fetch_all", "fetch_listings", "fetch_sold_sales", "get_market_prices",
                                    "active_asking_reference", "send_discord", "send_simple_discord",
                                    "get_session")}

# Emojis appear in some log lines. Production wraps stdout in _Tee (which swallows
# console-encoding errors) and CI is UTF-8; a bare Windows console (cp1252) is not,
# so make this harness tolerate un-encodable chars the same way.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

# Private temp dir per run: fixed %TEMP% DB names collided when two suites ran at once.
_TMPD = tempfile.mkdtemp(prefix="ebay_test_")

fails = []


def check(name, got, want):
    if got != want:
        fails.append(name)
        print(f"  [FAIL] {name}: got={got!r} want={want!r}")
    else:
        print(f"  [pass] {name}")


def ok(name, cond):
    check(name, bool(cond), True)


# --------------------------------------------------------------------------
print("== classify_grade ==")
# BGS/Beckett grade word BEFORE the number ("BGS Gem Mint 9.5", "BGS Pristine 10",
# "Beckett Black Label 10") must still bucket as bgs9.5/bgs10 (audit fix).
check("BGS Gem Mint 9.5", m.classify_grade("Charizard BGS Gem Mint 9.5"), "bgs9.5")
check("BGS Pristine 10", m.classify_grade("Charizard BGS Pristine 10"), "bgs10")
check("Beckett Black Label 10", m.classify_grade("Espeon Beckett Black Label 10"), "bgs10")
check("BGS GEM MT 9.5", m.classify_grade("Lugia BGS GEM MT 9.5"), "bgs9.5")
check("Beckett Graded 10 lot stays other", m.classify_grade("Beckett Graded 10 Cards Lot"), "other_graded")
check("PSA 10", m.classify_grade("PSA 10 Luffy ST26-005"), "psa10")
check("PSA 100 not PSA10", m.classify_grade("Lot of PSA 100 Luffy"), "other_graded")
check("BGS 9.5", m.classify_grade("Luffy BGS 9.5"), "bgs9.5")
check("BGS 10 not 9.5", m.classify_grade("Luffy BGS 10 Pristine"), "bgs10")
check("Beckett 9.5", m.classify_grade("Luffy Beckett 9.5"), "bgs9.5")
check("PSA 9 -> other", m.classify_grade("Luffy PSA 9"), "other_graded")
check("CGC 10", m.classify_grade("Luffy CGC 10"), "cgc10")
check("CGC 10 Gem Mint", m.classify_grade("Zapdos ex 202/165 CGC 10 Gem Mint"), "cgc10")
check("CGC 10 Pristine", m.classify_grade("Charizard CGC 10 Pristine"), "cgc10")
check("CGC Pristine 10", m.classify_grade("Charizard CGC Pristine 10"), "cgc10")
check("CGC-10 hyphen", m.classify_grade("Luffy CGC-10"), "cgc10")
check("CGC10 no space", m.classify_grade("Luffy CGC10"), "cgc10")
check("CGC 9.5 stays other", m.classify_grade("Luffy CGC 9.5"), "other_graded")
check("CGC 10th anniversary not cgc10", m.classify_grade("Pokemon CGC 10th Anniversary Promo"), "other_graded")
check("ready for CGC -> raw", m.classify_grade("Mew 232/091 NM ready for CGC grading"), "ungraded")
check("raw", m.classify_grade("Luffy ST26-005 SP Foil English"), "ungraded")
check("ACE 10 slab -> other", m.classify_grade("O-Nami ACE 10 OP06-101"), "other_graded")
check("TAG 10 slab -> other", m.classify_grade("Chopper TAG 10 ST01-006"), "other_graded")
check("ARS 10 slab -> other", m.classify_grade("Luffy ARS 10 ST26-005"), "other_graded")
check("Ace character raw", m.classify_grade("Portgas D. Ace OP01-002 NM"), "ungraded")
check("with tag raw", m.classify_grade("Nami OP06-101 mint with tag"), "ungraded")
check("PSA-10 hyphen", m.classify_grade("Luffy ST26-005 PSA-10 Gem"), "psa10")
check("PSA10 no space", m.classify_grade("Luffy ST26-005 PSA10"), "psa10")
check("BGS-9.5 hyphen", m.classify_grade("Luffy BGS-9.5"), "bgs9.5")
check("BGS10 no space", m.classify_grade("Luffy BGS10 Pristine"), "bgs10")
# GLUED mid-grade slabs (grader fused to a single/half digit, no space) must bucket
# as other_graded, not leak into ungraded. Regression: a bare \b after the company
# name failed here because "A9" has no letter/digit boundary.
check("PSA9 glued -> other", m.classify_grade("Lugia ex 031/PLAY PSA9"), "other_graded")
check("PSA8 glued -> other", m.classify_grade("Charizard Base Set PSA8"), "other_graded")
check("BGS9 glued -> other", m.classify_grade("Lugia BGS9"), "other_graded")
check("CGC9 glued -> other", m.classify_grade("Lugia CGC9"), "other_graded")
check("SGC9 glued -> other", m.classify_grade("Lugia SGC9"), "other_graded")
check("PSA9.5 glued -> other", m.classify_grade("Lugia PSA9.5"), "other_graded")
# grade words between "PSA" and "10" must still bucket as psa10 (common on slabs)
check("PSA GEM MT 10", m.classify_grade("Charizard PSA GEM MT 10 020/073"), "psa10")
check("PSA Grade 10", m.classify_grade("Celebi V 245/264 PSA Grade 10"), "psa10")
check("PSA GEM MINT 10", m.classify_grade("Mew ex 232/091 PSA GEM MINT 10"), "psa10")
check("PSA Graded 10 lot stays other", m.classify_grade("PSA Graded 10 Cards Lot"), "other_graded")
# aspirational grading on RAW cards must stay ungraded (not read as graded)
check("ready for PSA -> raw", m.classify_grade("Charizard 020/073 NM Ready for PSA Grading"), "ungraded")
check("perfect for PSA -> raw", m.classify_grade("Luffy OP05-119 Mint Perfect for PSA"), "ungraded")
check("send in for BGS -> raw", m.classify_grade("Rayquaza V 194/203 prime to send in for BGS"), "ungraded")

print("== language ==")
check("japanese word", m.title_language("Luffy ST26-005 Japanese"), "japanese")
check("cjk", m.title_language("ルフィ ST26-005"), "cjk")
check("unknown", m.title_language("Luffy ST26-005 Foil"), "unknown")
ok("en keeps unknown", m.passes_language("Luffy ST26-005 Foil", "english"))
ok("en drops japanese", not m.passes_language("Luffy Japanese", "english"))
ok("any keeps japanese", m.passes_language("Luffy Japanese", "any"))
# enumerated/negated language run must NOT flip an English card to a foreign language
check("english NOT jp+cn -> english", m.title_language("Luffy OP05-119 English NOT Japanese Chinese"), "english")
check("english NOT jp/kr -> english", m.title_language("Charizard English NOT Japanese/Korean"), "english")
check("not from japan -> english", m.title_language("Charizard English not from Japan"), "english")
ok("enumerated negation passes english", m.passes_language("Luffy English NOT Japanese Chinese", "english"))
ok("real japanese still dropped", not m.passes_language("Luffy from Japan", "english"))
check("korean hangul -> cjk", m.title_language("루피 카드 OP05-119"), "cjk")
# negated foreign mentions ("English NOT Japanese") must not flip an English card
check("English NOT Japanese", m.title_language("Luffy OP05-119 English NOT Japanese"), "english")
check("not a Japan import", m.title_language("Luffy OP05-119 not a Japan import English"), "english")
ok("en keeps 'not japanese'", m.passes_language("Luffy OP05-119 English NOT Japanese", "english"))
# a determiner between "not" and the language word ("not THE/this/any Japanese") must also
# be stripped so a genuinely-English listing isn't dropped (audit fix).
ok("en keeps 'not the japanese'", m.passes_language("Luffy English not the Japanese version", "english"))
ok("en keeps 'not this japanese'", m.passes_language("Espeon 1/75 Neo Discovery not this Japanese", "english"))
ok("en keeps 'not any japanese'", m.passes_language("Psyduck #20 not any Japanese reprint", "english"))
# ...but a NON-determiner word between "not" and the language word must NOT over-strip:
# a real foreign card is still dropped.
ok("drops 'not the cheap japanese'", not m.passes_language("Charizard not the cheap Japanese knockoff", "english"))
ok("drops bare japanese", not m.passes_language("Mew ex 347/190 Japanese SAR", "english"))
ok("bare japanese still dropped", not m.passes_language("Luffy OP05-119 Japanese", "english"))
# European-language prints share the collector number, so an 'english' watch must DROP
# them (added when Aquapolis turned out NOT to be English-only). Whole-word markers +
# only the safe short abbreviations (ita/ital/deu), never fr/de/it/es.
check("italiano -> eu", m.title_language("Umbreon H29/H32 Aquapolis Italiano"), "eu")
check("deutsch -> eu", m.title_language("Umbreon H29/H32 Aquapolis Deutsch"), "eu")
check("ITA abbrev -> eu", m.title_language("Azumarill H4/H32 Aquapolis Holo ITA WOTC"), "eu")
ok("en drops eu (italian)", not m.passes_language("Umbreon H29/H32 Aquapolis Italian", "english"))
ok("en drops eu (francais)", not m.passes_language("Charizard 100/97 EX Dragon francais", "english"))
ok("any keeps eu", m.passes_language("Umbreon H29 Aquapolis Italiano", "any"))
# safety: 'ita' inside a word (digital) must NOT flag; 'FR'=Fair grade must NOT flag French
check("digital not eu (word boundary)", m.title_language("Pokemon Digital Umbreon H29 Aquapolis"), "unknown")
check("FR=Fair not eu", m.title_language("Charizard 100/97 EX Dragon FR condition"), "unknown")
ok("en keeps 'English NOT German'", m.passes_language("Umbreon H29 Aquapolis English NOT German", "english"))

print("== matches_filters / require / aliases / match_any ==")
ok("require hit (punct-insensitive)", m.matches_filters("Luffy OP05 119 Manga", ["op05-119"], []))
ok("require miss", not m.matches_filters("Luffy OP05-060", ["op05-119"], []))
ok("AND both", m.matches_filters("Sanji OP10-005 Flagship", ["op10-005", "flagship"], []))
ok("AND one missing", not m.matches_filters("Sanji OP10-005 Royal Blood", ["op10-005", "flagship"], []))
ok("alias OR hit", m.matches_filters("O-Nami OP06-101 OP07 Alt", ["op06-101", ["500 years", "op07"]], []))
ok("alias OR miss", not m.matches_filters("O-Nami OP06-101 Wings", ["op06-101", ["500 years", "op07"]], []))
ok("default excludes proxy", not m.matches_filters("Luffy OP05-119 Proxy", ["op05-119"], []))
ok("per-watch exclude", not m.matches_filters("Luffy OP05-119 bundle", ["op05-119"], ["bundle"]))
MA = [["op15-086", ["alt art"]], [["nami"], ["alt art"], ["kami island"], ["sr"]]]
ok("match_any via number", m.matches_filters("Nami OP15-086 Alt Art SR", None, [], MA))
ok("match_any via name fallback", m.matches_filters("Nami Alt Art SR Kami Island", None, [], MA))
ok("match_any base excluded", not m.matches_filters("Nami OP15-086 Foil Kami Island", None, [], MA))

print("== is_lot ==")
ok("multi-number lot", m.is_lot("Luffy OP12-015 + ST26-005 + OP02-062 Set"))
ok("single card not lot", not m.is_lot("Bandai OP15 Luffy ST26-005 SP 2026"))
# Pokemon same-set multi-number lot (two numbers sharing a set total)
ok("pokemon two-number lot", m.is_lot("Mew ex 232/091 + 216/091 two-card lot"))
ok("pokemon single not lot", not m.is_lot("Mew ex 232/091 Paldean Fates SIR"))
ok("pop-report ratio not lot", not m.is_lot("Mew ex 232/091 PSA 10 POP 12/500"))
# a single card naming a sibling number in a comparison is NOT a lot
ok("sibling comparison not lot", not m.is_lot("Rayquaza V 194/203 not the VMAX 218/203"))
ok("paren sibling not lot", not m.is_lot("Giratina V 186/196 (not 130/196 regular)"))
ok("real 2-number lot still lot", m.is_lot("Mew ex 232/091 + 216/091 two-card lot"))

print("== is_bulk_or_sealed (word-boundary; no substring misfire) ==")
ok("booster box", m.is_bulk_or_sealed("Celebi V 245/264 Fusion Strike Booster Box Sealed"))
ok("ETB", m.is_bulk_or_sealed("Giratina V 186/196 Lost Origin Elite Trainer Box ETB"))
ok("bulk lot", m.is_bulk_or_sealed("Mew ex 232/091 Bulk Lot 50 Cards"))
ok("cards collection", m.is_bulk_or_sealed("Fusion Strike 245 Cards Collection Celebi V"))
ok("bare word lot", m.is_bulk_or_sealed("Giratina V 186/196 + Palkia lot"))
ok("Holo TCG single (not sealed)", not m.is_bulk_or_sealed("Giratina V 186/196 Lost Origin Holo TCG"))
ok("Holo Trading Card single", not m.is_bulk_or_sealed("Celebi V 245/264 Fusion Strike Holo Trading Card"))
ok("etb substring not misfire", not m.is_bulk_or_sealed("Pokemon trumpetbandit Celebi V 245/264"))
ok("plain single not sealed", not m.is_bulk_or_sealed("Mew ex 232/091 Paldean Fates SIR NM"))
ok("'not a lot' single not sealed", not m.is_bulk_or_sealed("Luffy OP05-119 SEC single card not a lot"))
ok("real bare-word lot still caught", m.is_bulk_or_sealed("Giratina V 186/196 + Palkia lot"))
# PLURAL sealed/bulk terms must also be caught (the trailing \b previously let plurals slip; audit fix)
ok("booster boxes plural", m.is_bulk_or_sealed("Lost Origin Booster Boxes chase Giratina V 186/196"))
ok("booster packs plural", m.is_bulk_or_sealed("Neo Genesis Booster Packs Lugia 9/111"))
ok("bundles plural", m.is_bulk_or_sealed("Evolving Skies Bundles Rayquaza V 194/203"))
ok("card lots plural", m.is_bulk_or_sealed("Psyduck #20 WOTC Black Star Card Lots"))
ok("playsets plural", m.is_bulk_or_sealed("Espeon 1/75 Neo Discovery Playsets"))
ok("plural 'not a lot' guard still holds", not m.is_bulk_or_sealed("Lugia 9/111 Neo Genesis single not a lot"))

print("== extended-art-case merch exclude ==")
ok("extended artwork case excluded",
   not m.matches_filters("Pokemon Mew EX SIR Paldean Fates 232/091 Extended Artwork Case", ["mew ex"], []))
ok("extended art case excluded",
   not m.matches_filters("Celebi V 245/264 Fusion Strike Extended Art Case Display", ["celebi v"], []))
ok("real card not excluded by art-case term",
   m.matches_filters("Mew ex 232/091 Paldean Fates SIR NM", ["mew ex"], []))
# session-added merch/proxy excludes (DEFAULT_EXCLUDE) — dropped everywhere
ok("fan art excluded",
   not m.matches_filters("Squirtle 007/018 McDonald's Fan Art Card", ["squirtle"], []))
ok("custom art excluded",
   not m.matches_filters("Squirtle 007/018 Custom Art Card", ["squirtle"], []))
ok("hand painted excluded",
   not m.matches_filters("Lugia 9/111 Hand Painted Neo Genesis", ["lugia"], []))
ok("acrylic card-case merch excluded",
   not m.matches_filters("Luffy OP05-119 Acrylic Card Case Display", ["op05-119"], []))
ok("playmat merch excluded",
   not m.matches_filters("Charizard 100/97 EX Dragon Playmat", ["charizard"], []))
# ...but a real card 'in a case' / a 'customs' mention must NOT be excluded (no adjacent merch phrase)
ok("card in hard case not excluded",
   m.matches_filters("Charizard 4/102 Base Set in hard case NM", ["charizard"], []))
ok("customs fee not excluded",
   m.matches_filters("Squirtle 007/018 McDonald's buyer pays customs fees", ["squirtle"], []))

print("== is_auction ==")
ok("auction with bids", m.is_auction({"bids": "5 bids", "format": None}))
ok("zero bids still auction", m.is_auction({"bids": "0 bids", "format": None}))
ok("BIN not auction", not m.is_auction({"bids": None, "format": "Buy It Now"}))

print("== region ==")
check("US", m.canon_region("United States"), "US")
check("CA", m.canon_region("Canada"), "CA")
check("other", m.canon_region("Japan"), "OTHER")
check("none", m.canon_region(None), None)
ok("US passes", m.passes_region("United States", {"US", "CA"}, False))
ok("Japan fails", not m.passes_region("Japan", {"US", "CA"}, False))
ok("unknown strict fails", not m.passes_region(None, {"US", "CA"}, False))
ok("unknown lenient passes", m.passes_region(None, {"US", "CA"}, True))

print("== parse_price / currency / price_ok / clean_title ==")
check("price simple", m.parse_price("$949.99")[1], 949.99)
check("price thousands", m.parse_price("$2,600.00")[1], 2600.0)
check("price range low", m.parse_price("$10.00 to $20.00")[1], 10.0)
check("currency plain USD", m.parse_price("$949.99")[2], "USD")
check("currency US $", m.parse_price("US $949.99")[2], "USD")
check("currency CAD C $", m.parse_price("C $80.00")[2], "CAD")
check("currency GBP", m.parse_price("£75.00")[2], "GBP")
check("currency EUR", m.parse_price("€90.00")[2], "EUR")
check("currency AUD", m.parse_price("AU $120.00")[2], "AUD")
check("currency JPY yen", m.detect_currency("¥893,534"), "JPY")
check("currency JPY code", m.detect_currency("JPY 749,136"), "JPY")
check("currency KRW won", m.detect_currency("₩120,000"), "KRW")
# other dollar-family currencies must NOT be swallowed by the bare-$ USD catch-all (audit fix)
check("currency HKD", m.detect_currency("HK $95.00"), "HKD")
check("currency SGD", m.detect_currency("S$ 80.00"), "SGD")
check("currency NZD", m.detect_currency("NZ $120.00"), "NZD")
check("currency TWD", m.detect_currency("NT$ 990"), "TWD")
check("currency MXN", m.detect_currency("MX$ 1,500.00"), "MXN")
check("currency BRL", m.detect_currency("R$ 50,00"), "BRL")
check("US $ still USD (not SGD)", m.detect_currency("US $95.00"), "USD")
check("bare $ still USD", m.detect_currency("$95.00"), "USD")
check("currency none", m.parse_price("90.00")[2], None)
ok("active search forces US-located items", "LH_PrefLoc=1" in m.build_search_url("www.ebay.com", "x"))
ok("sold search not US-forced", "LH_PrefLoc" not in m.build_search_url("www.ebay.com", "x", sold=True))
check("CAD number still parsed", m.parse_price("C $80.00")[1], 80.0)
ok("min floor", not m.price_ok(50.0, {"min_price": 100}))
ok("none passes", m.price_ok(None, {"min_price": 100}))
check("clean title", m.clean_title("Luffy ST26-005 Opens in a new window or tab"), "Luffy ST26-005")

print("== validate_config ==")
warns = m.validate_config({"watches": [
    {"name": "ok", "queries": ["x"], "require": ["op01-001"], "grades": ["psa10"]},
    {"name": "bad", "grades": ["psa11"], "allowed_regions": ["Mars"]},
]})
ok("flags missing queries", any("no 'queries'" in w for w in warns))
ok("flags match-all", any("match EVERY" in w for w in warns))
ok("flags bad grade", any("unknown grade" in w for w in warns))
ok("flags bad region", any("unrecognized region" in w for w in warns))
# non-numeric reference_override is surfaced up front (companion to the runtime guard; audit fix)
_row = m.validate_config({"watches": [{"name": "R", "queries": ["x"], "require": ["a"],
    "grades": ["ungraded"], "reference_override": {"ungraded": "$75"}}]})
ok("flags bad reference_override", any("reference_override" in w and "numeric" in w for w in _row))
# scan-aggressiveness guard (encodes the eBay rate-block lesson: bursts/volume block)
_aggro = m.validate_config({
    "poll_interval_seconds": 60, "priority_interval_seconds": 30,
    "scan_workers": 4, "min_request_interval_seconds": 0,
    "watches": [{"name": f"w{i}", "queries": ["a", "b", "c", "d"], "require": ["x"],
                 "grades": ["ungraded"], "price_alerts": [{"below": 1, "mention": "1"}]} for i in range(20)],
})
ok("flags high scan rate", any("req/min" in w for w in _aggro))
ok("flags request bursts", any("BURSTS" in w for w in _aggro))
_safe = m.validate_config({
    "poll_interval_seconds": 300, "priority_interval_seconds": 120,
    "scan_workers": 1, "max_queries_per_watch": 2, "min_request_interval_seconds": 2.0,
    "watches": [{"name": f"w{i}", "queries": ["a", "b"], "require": ["x"], "grades": ["ungraded"]} for i in range(32)],
})
ok("safe cadence -> no rate/burst warning", not any(("req/min" in w or "BURSTS" in w) for w in _safe))

print("== discord sender (author cap + transient-error retry) ==")
_cap = []
_real_post = m._post_webhook
m._post_webhook = lambda url, payload, **k: _cap.append(payload)
_L = {"item_id": "1", "title": "T", "url": "http://x", "price_str": "$1", "price_low": 1.0,
      "shipping": None, "condition": None, "location": None, "image": None}
m.send_discord("http://wh", "W" * 300, _L, "psa10")   # 300-char watch name
ok("author.name capped <=256", len(_cap[0]["embeds"][0]["author"]["name"]) <= 256)
m._post_webhook = _real_post
# _post_webhook retries transient 5xx / connection errors (not just 429), then succeeds
class _Resp:
    def __init__(s, code): s.status_code = code; s.headers = {}
    def json(s): return {}
    def raise_for_status(s):
        if s.status_code >= 400: raise Exception(f"HTTP {s.status_code}")
_saved_post, _saved_sleep = m.requests.post, m.time.sleep
m.time.sleep = lambda *a, **k: None
_seq = [_Resp(500), _Resp(503), _Resp(200)]; _n = {"i": 0}
def _fp(url, **k):
    r = _seq[_n["i"]]; _n["i"] += 1; return r
m.requests.post = _fp
m._post_webhook("http://wh", {"x": 1})
ok("webhook retries 5xx then succeeds", _n["i"] == 3)
_n2 = {"i": 0}
def _fp_conn(url, **k):
    _n2["i"] += 1
    if _n2["i"] == 1:
        raise m.requests.exceptions.ConnectionError("reset")
    return _Resp(200)
m.requests.post = _fp_conn
m._post_webhook("http://wh", {"x": 1})
ok("webhook retries a connection error", _n2["i"] == 2)
_n3 = {"i": 0}
m.requests.post = lambda url, **k: (_n3.__setitem__("i", _n3["i"] + 1), _Resp(500))[1]
try:
    m._post_webhook("http://wh", {"x": 1}); _persistent_raised = False
except Exception:
    _persistent_raised = True
ok("webhook still raises on persistent 5xx (fail-visible)", _persistent_raised and _n3["i"] == 4)
m.requests.post, m.time.sleep = _saved_post, _saved_sleep

# --------------------------------------------------------------------------
print("== scan_once: new-listing + dedup + price-drop (mocked) ==")

def L(item_id, price_str, price_low, title="Luffy OP05-119 Manga English", currency="USD"):
    return {"item_id": item_id, "title": title, "price_str": price_str, "price_low": price_low,
            "currency": currency,
            "url": f"https://www.ebay.com/itm/{item_id}", "image": None, "condition": None,
            "shipping": None, "bids": None, "format": None, "location": "United States"}

WATCH = {"name": "W", "require": ["op05-119"], "grades": ["ungraded"], "language": "english"}
CFG = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
       "price_drop_pct": 5, "price_drop_min": 1, "watches": [WATCH]}

tmp = os.path.join(_TMPD, "ebay_test_monitor.db")
if os.path.exists(tmp):
    os.remove(tmp)
m.DB_PATH = tmp
conn = m.db_connect()
sends = []
m.send_discord = lambda url, name, lst, grade, event="new", old_price_str=None, drop_pct=None, \
    market_price=None, **kw: \
    sends.append((event, lst["item_id"], old_price_str, lst["price_str"], drop_pct))
health = []
m.send_simple_discord = lambda url, title, text, color: health.append((title, text))

def run(fixtures, **kw):
    m.fetch_listings = lambda d, q, **k: list(fixtures)
    m.fetch_all = lambda d, w, **k: list(fixtures)
    sends.clear()
    m.scan_once(CFG, conn, **kw)
    return list(sends)

ok("seed silent", run([L("1", "$100.00", 100.0)]) == [])
ok("new listing alerts", run([L("1", "$100.00", 100.0), L("2", "$50.00", 50.0)]) == [("new", "2", None, "$50.00", None)])
ok("no duplicate", run([L("1", "$100.00", 100.0), L("2", "$50.00", 50.0)]) == [])
s = run([L("1", "$90.00", 90.0), L("2", "$50.00", 50.0)])
ok("price drop alert 10%", s == [("drop", "1", "$100.00", "$90.00", 10)])
ok("no re-drop when stable", run([L("1", "$90.00", 90.0), L("2", "$50.00", 50.0)]) == [])
ok("increase no alert", run([L("1", "$200.00", 200.0), L("2", "$50.00", 50.0)]) == [])
jp = L("7", "$10.00", 10.0); jp["location"] = "Japan"
res = run([jp, L("1", "$200.00", 200.0)])   # jp excluded (region); item 1 seen -> no alert
ok("japan listing excluded in scan", not any(r[1] == "7" for r in res))

# scan_once returns the number of alerts fired this pass (informational; CI persists
# seen.db after each loop segment, see .github/persist.sh).
def run_ret(fixtures, **kw):
    m.fetch_listings = lambda d, q, **k: list(fixtures)
    m.fetch_all = lambda d, w, **k: list(fixtures)
    sends.clear()
    r = m.scan_once(CFG, conn, **kw)
    return r, list(sends)
rc, s1 = run_ret([L("retnew", "$40.00", 40.0)])         # brand-new item -> 1 alert
ok("scan_once returns alert count", rc == len(s1) == 1)
rc2, s2 = run_ret([L("retnew", "$40.00", 40.0)])        # now seen -> 0 alerts
ok("returns 0 when nothing new", rc2 == 0 and s2 == [])

print("== health check + prune ==")
m.meta_set(conn, "health", "ok"); health.clear()
run([])                                   # 0 scraped across all watches -> down (scrape broken)
ok("health down on 0 scraped", any("scraped across" in txt for _, txt in health))
health.clear()
run([L("1", "$200.00", 200.0)])           # scraping + matching back -> recovered
ok("health recovered alerted", any("recover" in t.lower() for t, _ in health))
health.clear()
# 0 matched is debounced: a single quiet pass must NOT alert; only a sustained
# streak (default 3 scans) does — that's a real filter/layout break, not quiet inventory.
run([L("z", "$10.00", 10.0, "Unrelated Card XYZ")])
ok("single 0-matched pass does not alert", not any("0 matched" in txt for _, txt in health))
run([L("z", "$10.00", 10.0, "Unrelated Card XYZ")])
ok("second 0-matched pass still quiet", not any("0 matched" in txt for _, txt in health))
run([L("z", "$10.00", 10.0, "Unrelated Card XYZ")])   # 3rd consecutive -> down
ok("health down after sustained 0 matched", any("0 matched" in txt for _, txt in health))
health.clear()
run([L("1", "$200.00", 200.0)])                       # match returns -> streak resets, recovered
ok("recovered after match returns", any("recover" in t.lower() for t, _ in health))

stale = (m.datetime.now(m.timezone.utc) - m.timedelta(days=40)).date().isoformat()
conn.execute("INSERT OR REPLACE INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen) "
             "VALUES(?,?,?,?,?,?,?)", ("W", "999", "ungraded", "t", 10.0, "$10", stale))
conn.commit()
before = conn.execute("SELECT COUNT(*) FROM seen WHERE item_id='999'").fetchone()[0]
m.prune_seen(conn, 30)
after = conn.execute("SELECT COUNT(*) FROM seen WHERE item_id='999'").fetchone()[0]
ok("prune removes stale row", before == 1 and after == 0)
fresh = conn.execute("SELECT COUNT(*) FROM seen WHERE item_id='1'").fetchone()[0]
ok("prune keeps fresh row", fresh == 1)

print("== market price + below-market ==")
check("median", m._median([3, 1, 2]), 2)
check("median even", m._median([1, 2, 3, 4]), 2.5)
check("sold date parse", m._parse_sold_date("Sold Jul 19, 2026"), "2026-07-19")
# Year rollover: a yearless "Sold <far-future-month> <day>" must roll back a year
# rather than land in the future. Pick the month 6 months ahead of 'today'.
_future_mo = (m.datetime.now(m.timezone.utc).month % 12) + 6
_future_mo = _future_mo if _future_mo <= 12 else _future_mo - 12
_mon = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"][_future_mo - 1]
_parsed_year = int(m._parse_sold_date(f"Sold {_mon.capitalize()} 15")[:4])
ok("yearless future month rolls back a year", _parsed_year <= m.datetime.now(m.timezone.utc).year)
check("median recent price (trimmed)",
      m.median_recent_price([("2026-07-01", 100.0, "ungraded"),
                             ("2026-07-02", 110.0, "ungraded"),
                             ("2026-07-03", 5.0, "ungraded"),   # junk low, trimmed
                             ("2026-07-04", 90.0, "ungraded")], "ungraded"), 100.0)
check("median recent price ignores other buckets",
      m.median_recent_price([("2026-07-01", 500.0, "psa10")], "ungraded"), None)

MKT = {"v": 100.0}
m.get_market_prices = lambda conn_, domain, watch, grades, **k: {"ungraded": MKT["v"]}
run([L("b2", "$98.00", 98.0)])            # market 100 -> 98 not below (needs <95); seeds below_alerted=0
MKT["v"] = 120.0                          # market rises -> 98 now below 120*0.95=114
s = run([L("b2", "$98.00", 98.0)])
ok("below-market crossing pings", any(r[0] == "below_market" and r[1] == "b2" for r in s))
ok("below-market not repeated", not any(r[0] == "below_market" for r in run([L("b2", "$98.00", 98.0)])))
below_flag = conn.execute("SELECT below_alerted FROM seen WHERE item_id='b2'").fetchone()[0]
ok("below_alerted persisted", below_flag == 1)
# STICKY: the asking reference jitters (and is None on thin scans). Once alerted, an
# item must NOT re-fire below-market when the reference dips "not below" then returns.
MKT["v"] = 100.0                            # 98 no longer below (needs <95) -> would clear the flag
ok("no ping on jitter to not-below", not any(r[0] == "below_market" for r in run([L("b2", "$98.00", 98.0)])))
MKT["v"] = None                            # reference unavailable this scan (too few comps)
ok("no ping when reference missing", not any(r[0] == "below_market" for r in run([L("b2", "$98.00", 98.0)])))
MKT["v"] = 120.0                           # reference returns; item below again
ok("no DUPLICATE below-market on re-cross", not any(r[0] == "below_market" for r in run([L("b2", "$98.00", 98.0)])))
ok("below_alerted stays sticky", conn.execute("SELECT below_alerted FROM seen WHERE item_id='b2'").fetchone()[0] == 1)
# A price DROP must not clear the sticky below flag either (even if the post-drop price
# isn't below a jittery/low reference this pass) -- otherwise a later below re-fires.
MKT["v"] = 94.0                             # $90 is NOT below 94 (needs < 89.3), so 'below' is False
sdrop = run([L("b2", "$90.00", 90.0)])     # 98 -> 90 drop fires
ok("price drop fires on b2", any(r[0] == "drop" and r[1] == "b2" for r in sdrop))
ok("drop keeps sticky below flag", conn.execute("SELECT below_alerted FROM seen WHERE item_id='b2'").fetchone()[0] == 1)
MKT["v"] = 100.0

# A CAD-priced listing must NOT be compared against the USD market median (that
# manufactured fake deals). It still alerts as new, but never below-market.
MKT["v"] = 100.0
cad = L("cad1", "C $60.00", 60.0, currency="CAD")   # 60 < 95 in raw number, but CAD
scad = run([cad])                                    # first pass: watch W already seeded -> new alert
ok("CAD listing alerts as new", any(r[1] == "cad1" for r in scad))
cad_below = conn.execute("SELECT below_alerted FROM seen WHERE item_id='cad1'").fetchone()[0]
ok("CAD not flagged below USD market", cad_below == 0)

print("== reference_override pins the below-market reference ==")
# Pin ungraded ref to 75: below-market fires only in [75*floor, 75*(1-below_pct)) = [37.5, 67.5).
OW = {"name": "OV", "require": ["op05-119"], "grades": ["ungraded"], "language": "english",
      "reference_override": {"ungraded": 75}}
OCFG = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com", "watches": [OW]}
m.get_market_prices = lambda conn_, d, w, g, **k: {"ungraded": None}    # no sold; override drives it
conn.execute("INSERT OR IGNORE INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen) "
             "VALUES('OV','ovseed','ungraded','t',999,'$999','2026-07-01')"); conn.commit()
m.fetch_all = lambda d, w, **k: [L("ovhi", "$70.00", 70.0), L("ovlo", "$60.00", 60.0)]
sends.clear(); m.scan_once(OCFG, conn)
ok("override: $60 flagged below pinned $75 ref",
   conn.execute("SELECT below_alerted FROM seen WHERE item_id='ovlo'").fetchone()[0] == 1)
ok("override: $70 NOT below (>= $67.50)",
   conn.execute("SELECT below_alerted FROM seen WHERE item_id='ovhi'").fetchone()[0] == 0)

print("== per-grade market (graded slab priced against its own bucket) ==")
# A PSA 10 listing is flagged below-market only against the PSA 10 sold median,
# and is unaffected by the ungraded median.
GWATCH = {"name": "G", "require": ["op05-119"], "grades": ["ungraded", "psa10"], "language": "english"}
GCFG = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
        "price_drop_pct": 5, "price_drop_min": 1, "watches": [GWATCH]}
m.get_market_prices = lambda conn_, domain, watch, grades, **k: {"ungraded": 100.0, "psa10": 1000.0}
# Pre-seed watch G so it isn't in silent first-run mode -> new listings alert.
conn.execute("INSERT OR IGNORE INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen) "
             "VALUES('G','seed0','psa10','t',999,'$999','2026-07-01')")
conn.commit()
def grun(fixtures):
    m.fetch_all = lambda d, w, **k: list(fixtures)
    sends.clear(); m.scan_once(GCFG, conn, **{}); return list(sends)
psa = L("g1", "$800.00", 800.0, "PSA 10 Luffy OP05-119 Manga English")     # 800 < 1000*0.95 -> below
raw = L("g2", "$800.00", 800.0, "Luffy OP05-119 Manga English")           # 800 > 100 ungraded -> not below
s = grun([psa, raw])
ok("psa10 slab alerts as new", any(r[0] == "new" and r[1] == "g1" for r in s))
ok("raw alerts as new", any(r[0] == "new" and r[1] == "g2" for r in s))
g1_below = conn.execute("SELECT below_alerted FROM seen WHERE item_id='g1'").fetchone()[0]
g2_below = conn.execute("SELECT below_alerted FROM seen WHERE item_id='g2'").fetchone()[0]
ok("psa10 slab below its own bucket", g1_below == 1)      # priced vs psa10 median (1000)
ok("raw not below (own bucket 100)", g2_below == 0)       # NOT dragged below by psa10 median

print("== market-prices cache (None not cached, real cached, shared fetch) ==")
import importlib
importlib.reload(m)          # restore real market functions (monkeypatched above)
fetch_calls = {"n": 0}
def _fake_sold(domain, watch):
    fetch_calls["n"] += 1
    if fetch_calls["n"] == 1:
        return []                                    # too few comps -> None everywhere
    return [(f"2026-07-{i:02d}", 42.0, "ungraded") for i in range(1, 6)]
m.fetch_sold_sales = _fake_sold
m.meta_set(conn, "market_circuit", '{"fails": 0, "until": null}')
mw = {"name": "MKTcache", "require": ["op05-119"], "grades": ["ungraded"]}
r1 = m.get_market_prices(conn, "www.ebay.com", mw, ["ungraded"])   # no comps -> None
ok("unpriceable bucket returns None", r1["ungraded"] is None)
_cached = m.meta_get(conn, "market:MKTcache:ungraded")
ok("None is negative-cached", _cached is not None and json.loads(_cached)["price"] is None)
r2 = m.get_market_prices(conn, "www.ebay.com", mw, ["ungraded"])   # inside negative TTL
ok("negative cache avoids refetch every scan", fetch_calls["n"] == 1 and r2["ungraded"] is None)
# Expire the negative entry -> it retries and now finds real comps.
_old = (m.datetime.now(m.timezone.utc) - m.timedelta(hours=m.MARKET_NONE_CACHE_HOURS + 1)).isoformat()
m.meta_set(conn, "market:MKTcache:ungraded", json.dumps({"price": None, "ts": _old}))
r3 = m.get_market_prices(conn, "www.ebay.com", mw, ["ungraded"])
ok("negative cache expires and recomputes", r3["ungraded"] == 42.0 and fetch_calls["n"] == 2)
r4 = m.get_market_prices(conn, "www.ebay.com", mw, ["ungraded"])   # served from cache
ok("real market served from cache", r4["ungraded"] == 42.0 and fetch_calls["n"] == 2)
ok("other_graded never priced",
   m.get_market_prices(conn, "www.ebay.com", mw, ["other_graded"]) == {})

print("== one-time below-flag baseline (no alert storm on first reference) ==")
# Simulate the real deploy: existing rows stored with below_alerted=0 while no
# reference existed. The first scan that HAS a reference must baseline silently.
_real_gmp, _real_send = m.get_market_prices, m.send_discord   # restored after this block
m.send_discord = lambda url, name, lst, grade, event="new", old_price_str=None, \
    drop_pct=None, market_price=None, **kw: \
    sends.append((event, lst["item_id"], old_price_str, lst["price_str"], drop_pct))
m.meta_set(conn, "ask_baseline_done", "")
conn.execute("DELETE FROM seen WHERE watch='BL'")
for i, p in enumerate([50.0, 55.0, 60.0]):
    conn.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted) "
                 "VALUES('BL',?,'ungraded','t',?,?, '2026-07-01',0)", (f"bl{i}", p, f"${p}"))
conn.commit()
BLW = {"name": "BL", "require": ["op05-119"], "grades": ["ungraded"], "language": "english"}
BLCFG = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
         "watches": [BLW]}
m.get_market_prices = lambda conn_, domain, watch, grades, **k: {"ungraded": 100.0}
blf = [L(f"bl{i}", f"${p}", p) for i, p in enumerate([50.0, 55.0, 60.0])]
m.fetch_all = lambda d, w, **k: list(blf)
sends.clear(); m.scan_once(BLCFG, conn)
ok("no below-market storm on first reference",
   not any(r[0] == "below_market" for r in sends))
flags = [r[0] for r in conn.execute("SELECT below_alerted FROM seen WHERE watch='BL'")]
ok("below flags baselined instead", all(f == 1 for f in flags))
ok("baseline marked done", m.meta_get(conn, "ask_baseline_done") == m.ASK_BASELINE_VERSION)
# A genuine later crossing still alerts. Clear the flag only (changing the stored
# price would register as a price DROP and short-circuit the below check).
conn.execute("UPDATE seen SET below_alerted=0 WHERE watch='BL' AND item_id='bl0'")
conn.commit()
sends.clear(); m.scan_once(BLCFG, conn)
ok("real crossing still alerts after baseline",
   any(r[0] == "below_market" and r[1] == "bl0" for r in sends))
m.get_market_prices, m.send_discord = _real_gmp, _real_send   # don't leak into later tests

print("== active-asking reference (fallback when sold data is gated) ==")
check("percentile p25", m._percentile([10, 20, 30, 40, 50], 25), 20.0)
check("percentile p50", m._percentile([10, 20, 30, 40, 50], 50), 30.0)
check("percentile single", m._percentile([7], 25), 7)
check("percentile empty", m._percentile([], 25), None)

AW = {"name": "AR", "require": ["op05-119"], "grades": ["ungraded"], "language": "english"}
def AL(i, price, title="Luffy OP05-119 Manga English", **kw):
    d = L(str(i), f"${price}", float(price), title)
    d.update(kw)
    return d
# 8 raw asks: 100..170 -> p25 = 117.5 (interpolated)
asks = [AL(i, p) for i, p in enumerate([100, 110, 120, 130, 140, 150, 160, 170])]
ref = m.active_asking_reference(asks, AW, {"ungraded"})
check("asking p25 reference", ref.get("ungraded"), 117.5)
ok("too few asks -> no reference",
   m.active_asking_reference(asks[:4], AW, {"ungraded"}) == {})
# auctions must not drag the reference down
withauc = asks + [AL(99, 5, bids="3 bids")]
check("auctions excluded from reference",
      m.active_asking_reference(withauc, AW, {"ungraded"}).get("ungraded"), 117.5)
# non-USD must not pollute a USD reference
withcad = asks + [AL(98, 5, currency="CAD")]
check("non-USD excluded from reference",
      m.active_asking_reference(withcad, AW, {"ungraded"}).get("ungraded"), 117.5)
# graded listings land in their own bucket, not the raw one
mixed = asks + [AL(200 + i, p, "PSA 10 Luffy OP05-119 Manga English")
                for i, p in enumerate([500, 520, 540, 560, 580, 600, 620, 640])]
mref = m.active_asking_reference(mixed, AW, {"ungraded", "psa10"})
ok("per-grade asking buckets stay separate",
   mref.get("ungraded") == 117.5 and mref.get("psa10") == 535.0)
# A card number covering both a cheap base printing and an expensive SP: without a
# price window the p25 lands in the junk cluster; min_price isolates the real card.
bimodal = [AL(300 + i, p) for i, p in enumerate([3, 4, 5, 6, 7, 8, 9, 10])] + \
          [AL(400 + i, p) for i, p in enumerate([300, 320, 340, 360, 380, 400, 420, 440])]
check("bimodal without window picks junk cluster",
      m.active_asking_reference(bimodal, AW, {"ungraded"}).get("ungraded"), 6.75)
AW_MIN = dict(AW, min_price=100)
check("min_price isolates the real comparables",
      m.active_asking_reference(bimodal, AW_MIN, {"ungraded"}).get("ungraded"), 335.0)

print("== market circuit breaker (sold data blocked) ==")
# eBay requires sign-in for sold listings, so the fetch returns []. Retrying that
# every scan risks getting the whole session challenged, which would break the
# active-listing scrape. After N failed rounds the breaker parks sold lookups.
m.meta_set(conn, "market_circuit", '{"fails": 0, "until": null}')
blocked = {"n": 0}
def _blocked_sold(domain, watch):
    blocked["n"] += 1
    return []                                   # challenge/sign-in page -> no sales
m.fetch_sold_sales = _blocked_sold
cw = {"name": "CB", "require": ["x"], "grades": ["ungraded"]}
for i in range(m.MARKET_FAIL_THRESHOLD):
    m.meta_set(conn, f"market:CB:ungraded", "")   # force a cache miss each round
    m.get_market_prices(conn, "www.ebay.com", cw, ["ungraded"])
ok("breaker attempted up to threshold", blocked["n"] == m.MARKET_FAIL_THRESHOLD)
is_open, _st = m._market_circuit_open(conn, m.datetime.now(m.timezone.utc))
ok("breaker opens after threshold", is_open)
before_n = blocked["n"]
m.meta_set(conn, f"market:CB:ungraded", "")       # cache miss, but breaker is open
res = m.get_market_prices(conn, "www.ebay.com", cw, ["ungraded"])
ok("open breaker skips the network entirely", blocked["n"] == before_n)
ok("open breaker reports no market price", res["ungraded"] is None)

# When the cooldown LAPSES the fail counter must reset — else the next single failure
# re-trips the breaker (the N-consecutive guard would only work once). (audit fix)
_past = (m.datetime.now(m.timezone.utc) - m.timedelta(hours=1)).isoformat()
m.meta_set(conn, "market_circuit", '{"fails": %d, "until": "%s"}' % (m.MARKET_FAIL_THRESHOLD, _past))
_lapsed_open, _lapsed_st = m._market_circuit_open(conn, m.datetime.now(m.timezone.utc))
ok("lapsed cooldown -> not open", not _lapsed_open)
ok("lapsed cooldown -> fails reset to 0", int(_lapsed_st.get("fails", 0)) == 0)
m._market_record_result(conn, _lapsed_st, False, m.datetime.now(m.timezone.utc))
_reopen, _ = m._market_circuit_open(conn, m.datetime.now(m.timezone.utc))
ok("single failure after lapse does NOT immediately re-open", not _reopen)

# A successful round resets the breaker.
m.meta_set(conn, "market_circuit", '{"fails": 0, "until": null}')
m.fetch_sold_sales = lambda d, w: [(f"2026-07-{i:02d}", 42.0, "ungraded") for i in range(1, 6)]
m.meta_set(conn, f"market:CB:ungraded", "")
m.get_market_prices(conn, "www.ebay.com", cw, ["ungraded"])
still_open, st2 = m._market_circuit_open(conn, m.datetime.now(m.timezone.utc))
ok("success resets breaker", (not still_open) and int(st2.get("fails", 0)) == 0)

# Negative results are cached briefly (not refetched every scan).
m.fetch_sold_sales = _blocked_sold
m.meta_set(conn, "market_circuit", '{"fails": 0, "until": null}')
m.meta_set(conn, f"market:CB:ungraded", "")
m.get_market_prices(conn, "www.ebay.com", cw, ["ungraded"])
n_after_first = blocked["n"]
m.get_market_prices(conn, "www.ebay.com", cw, ["ungraded"])   # within negative TTL
ok("None result negative-cached (no immediate refetch)", blocked["n"] == n_after_first)

print("== log rotation ==")
import tempfile as _tf
_logdir = _tf.mkdtemp()
m.LOG_PATH = os.path.join(_logdir, "monitor.log")
m.LOG_MAX_BYTES = 100
with open(m.LOG_PATH, "w", encoding="utf-8") as _f:
    _f.write("x" * 250)                                    # over the cap
m._rotate_log_if_large()
ok("large log rotated to .1", os.path.exists(m.LOG_PATH + ".1")
   and not os.path.exists(m.LOG_PATH))
with open(m.LOG_PATH, "w", encoding="utf-8") as _f:
    _f.write("small")                                      # under the cap
m._rotate_log_if_large()
ok("small log not rotated", os.path.exists(m.LOG_PATH))

print("== fetch_all_watches (parallel fetch: mapping + error isolation) ==")
_saved_fetch_all = m.fetch_all
_wl = [{"name": f"W{i}", "queries": ["q"]} for i in range(6)]
m.fetch_all = lambda d, w, **k: [{"item_id": w["name"] + "-1"}]
_res = m.fetch_all_watches("www.ebay.com", _wl, workers=4)
ok("all watches fetched", len(_res) == 6)
ok("per-watch mapping preserved", all(_res[i][0]["item_id"] == f"W{i}-1" for i in range(6)))
ok("workers=1 fallback", len(m.fetch_all_watches("www.ebay.com", _wl, workers=1)) == 6)
ok("empty watches -> empty", m.fetch_all_watches("www.ebay.com", [], workers=4) == {})
def _flaky(d, w, **k):
    if w["name"] == "W2":
        raise RuntimeError("boom")
    return [{"item_id": w["name"]}]
m.fetch_all = _flaky
_r = m.fetch_all_watches("www.ebay.com", _wl, workers=4)
ok("failed watch isolated to []", _r[2] == [] and _r[0] and _r[1])
m.fetch_all = _saved_fetch_all

print("== build_search_url (worldwide vs US-only + CJK query) ==")
_u_us = m.build_search_url("www.ebay.com", "espeon 196")
ok("US-only search forces LH_PrefLoc=1", "LH_PrefLoc=1" in _u_us)
_u_ww = m.build_search_url("www.ebay.com", "espeon 196", worldwide=True)
ok("worldwide search omits LH_PrefLoc", "LH_PrefLoc" not in _u_ww)
_u_cjk = m.build_search_url("www.ebay.com", "宝可梦 月亮伊布 cbb2c-06 15/15", worldwide=True)
ok("CJK query URL-encodes without error", _u_cjk.startswith("https://www.ebay.com/sch/") and "%" in _u_cjk)
# fetch_all passes worldwide=True iff the watch sets all_regions
_seen_ww = {}
def _cap_fl(d, q, sold=False, worldwide=False, **k):
    _seen_ww["v"] = worldwide
    return []
_saved_fl = m.fetch_listings
m.fetch_listings = _cap_fl
_REAL_FETCH_ALL("www.ebay.com", {"name": "w", "queries": ["q"], "all_regions": True})
ok("all_regions watch -> worldwide fetch", _seen_ww.get("v") is True)
_seen_ww.clear()
_REAL_FETCH_ALL("www.ebay.com", {"name": "w", "queries": ["q"]})
ok("normal watch -> US-only fetch", _seen_ww.get("v") is False)
m.fetch_listings = _saved_fl

print("== max_queries cap (rate-limit safety) ==")
_qcalls = []
def _cap_q(d, q, sold=False, worldwide=False, **k):
    _qcalls.append(q)
    return []
_saved_fl3 = m.fetch_listings
m.fetch_listings = _cap_q
_REAL_FETCH_ALL("www.ebay.com", {"name": "w", "queries": ["a", "b", "c", "d"]}, max_queries=2)
ok("max_queries caps to 2", len(_qcalls) == 2)
_qcalls.clear()
_REAL_FETCH_ALL("www.ebay.com", {"name": "w", "queries": ["a", "b", "c", "d"]})
ok("no cap -> all 4 queries", len(_qcalls) == 4)
m.fetch_listings = _saved_fl3

print("== request throttle (anti-burst spacing) ==")
import time as _time
_saved_mri = m._MIN_REQUEST_INTERVAL
m._MIN_REQUEST_INTERVAL = 0.2
m._LAST_REQUEST_AT[0] = 0.0
m._throttle_request()          # first call primes the clock (no wait)
_t0 = _time.time()
m._throttle_request()          # second must wait ~one interval
ok("throttle enforces >= interval between requests", (_time.time() - _t0) >= 0.18)
m._MIN_REQUEST_INTERVAL = _saved_mri
m._LAST_REQUEST_AT[0] = 0.0

print("== price_alerts (@mention on an absolute price target) ==")
# --- pure helpers ---
_par = m.parse_price_alerts({"price_alerts": [
    {"grade": "PSA 10", "below": "2700", "mention": 209187722575872000},
    {"below": 50},                 # any-grade, mention omitted
    {"grade": "psa10"},            # no 'below' -> dropped
    "junk",                        # not a dict -> dropped
]})
ok("parse: valid rules kept", len(_par) == 2)
ok("parse: grade normalized", _par[0]["grade"] == "psa10")
ok("parse: below -> float", _par[0]["below"] == 2700.0)
ok("parse: mention -> str", _par[0]["mention"] == "209187722575872000")
ok("parse: any-grade/no-mention", _par[1]["grade"] is None and _par[1]["mention"] is None)
ok("hit: psa10 below fires", m.price_alert_hit(_par, "psa10", 2650.0)["mention"] == "209187722575872000")
ok("hit: at threshold no", m.price_alert_hit(_par, "psa10", 2700.0) is None)
ok("hit: wrong grade no", m.price_alert_hit(_par, "bgs10", 100.0) is None)     # 100<2700 but rule is psa10; any-rule is <50
ok("hit: any-grade fires", m.price_alert_hit(_par, "bgs10", 40.0)["grade"] is None)
ok("hit: price None no", m.price_alert_hit(_par, "psa10", None) is None)

# --- validate_config warnings ---
_vw = m.validate_config({"watches": [{"name": "X", "queries": ["q"], "require": ["a"],
    "grades": ["psa10"], "price_alerts": [
        {"grade": "psa10", "below": 2700, "mention": "1"},   # ok
        {"grade": "bgs9.5", "below": 10, "mention": "1"},    # grade not in this watch's grades
        {"below": "notnum", "mention": "1"},                 # bad 'below'
        {"grade": "psa10", "below": 5}]}]})                  # missing mention
ok("validate: grade-not-in-watch", any("never fire" in w for w in _vw))
ok("validate: bad below", any("invalid numeric" in w for w in _vw))
ok("validate: missing mention", any("without an @ping" in w for w in _vw))

# --- scan_once integration ---
_MENT = "209187722575872000"
_paw = {"name": "PA", "require": ["232/091"], "grades": ["ungraded", "psa10"], "language": "any",
        "allow_unknown_region": True,
        "price_alerts": [{"grade": "psa10", "below": 2700, "mention": _MENT}]}
_PACFG = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
          "allow_unknown_region": True, "watches": [_paw]}
_padb = os.path.join(_TMPD, "ebay_test_pa.db")
if os.path.exists(_padb):
    os.remove(_padb)
m.DB_PATH = _padb
paconn = m.db_connect()
m.meta_set(paconn, "ask_baseline_done", m.ASK_BASELINE_VERSION)
m.meta_set(paconn, "pa_baseline_done", "1")
_sv_gmp, _sv_aar, _sv_send = m.get_market_prices, m.active_asking_reference, m.send_discord
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}
_sa = []
m.send_discord = lambda url, name, lst, grade, event="new", old_price_str=None, drop_pct=None, \
    market_price=None, market_kind="sold", is_deal=None, mention=None, alert_threshold=None: \
    _sa.append({"event": event, "id": lst["item_id"], "mention": mention})

def _PL(item_id, price_low, grade_prefix="PSA 10 ", currency="USD"):
    return {"item_id": item_id, "title": f"{grade_prefix}Pokemon Mew ex 232/091 Paldean Fates SIR",
            "price_str": f"${price_low:,.2f}", "price_low": price_low, "currency": currency,
            "url": f"https://www.ebay.com/itm/{item_id}", "image": None, "condition": None,
            "shipping": None, "bids": None, "format": None, "location": "United States"}

def _parun(fixtures):
    m.fetch_all = lambda d, w, **k: list(fixtures)
    _sa.clear(); m.scan_once(_PACFG, paconn); return list(_sa)

def _seed_pa(item_id, price, grade="psa10", pa=0):
    paconn.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,"
                   "below_alerted,price_alerted) VALUES('PA',?,?,?,?,?,?,0,?)",
                   (item_id, grade, "2026-01-01T00:00:00", price, f"${price}", "2026-01-01", pa))
    paconn.commit()

_seed_pa("decoy", 9999)                       # so the watch isn't on its silent first run
ok("pa: new below-target pings once", [x for x in _parun([_PL("n1", 2650)]) if x["id"] == "n1"]
   == [{"event": "new", "id": "n1", "mention": _MENT}])
ok("pa: no re-ping while below", _parun([_PL("n1", 2650)]) == [])
ok("pa: above-target new no ping",
   [x for x in _parun([_PL("hi", 3200)]) if x["id"] == "hi"][0]["mention"] is None)

_seed_pa("x1", 2800)                          # existing, above target
_xr = [x for x in _parun([_PL("x1", 2650)]) if x["id"] == "x1"]   # drops below (also a >5% drop)
ok("pa: crossing is ONE message", len(_xr) == 1)
ok("pa: crossing is price_alert (drop folded)", _xr and _xr[0]["event"] == "price_alert")
ok("pa: crossing pings", _xr and _xr[0]["mention"] == _MENT)
ok("pa: crossing baselines stored price",
   paconn.execute("SELECT price FROM seen WHERE item_id='x1'").fetchone()[0] == 2650)
ok("pa: no re-ping stays below", [x for x in _parun([_PL("x1", 2640)]) if x["id"] == "x1"] == [])
_parun([_PL("x1", 2750)])                     # rises above target -> re-arm
ok("pa: re-armed on rise",
   paconn.execute("SELECT price_alerted FROM seen WHERE item_id='x1'").fetchone()[0] == 0)
ok("pa: re-pings second crossing",
   [x for x in _parun([_PL("x1", 2650)]) if x["id"] == "x1"][0]["mention"] == _MENT)
ok("pa: non-USD below no ping",
   [x for x in _parun([_PL("gbp", 2000, currency="GBP")]) if x["id"] == "gbp"][0]["mention"] is None)
ok("pa: wrong grade no ping",
   [x for x in _parun([_PL("ung", 50, grade_prefix="")]) if x["id"] == "ung"][0]["mention"] is None)

# baseline suppresses the first-scan flood but records flags
_padb2 = os.path.join(_TMPD, "ebay_test_pa2.db")
if os.path.exists(_padb2):
    os.remove(_padb2)
m.DB_PATH = _padb2
paconn2 = m.db_connect()
m.meta_set(paconn2, "ask_baseline_done", m.ASK_BASELINE_VERSION)   # pa_baseline_done deliberately unset
paconn2.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,"
                "below_alerted,price_alerted) VALUES('PA','b1','psa10','2026-01-01T00:00:00',"
                "2600,'$2600','2026-01-01',0,0)")
paconn2.commit()
m.fetch_all = lambda d, w, **k: [_PL("b1", 2600)]
_sa.clear(); m.scan_once(_PACFG, paconn2)
ok("pa: baseline suppresses first-scan @mention", _sa == [])
ok("pa: baseline records the flag",
   paconn2.execute("SELECT price_alerted FROM seen WHERE item_id='b1'").fetchone()[0] == 1)
ok("pa: baseline marks done", m.meta_get(paconn2, "pa_baseline_done") == "1")

# all_regions bypasses the US/CA region gate (for import-only foreign cards)
def _mk_arcfg(allregions):
    w = {"name": "ARw", "require": ["232/091"], "grades": ["ungraded", "psa10"], "language": "any"}
    if allregions:
        w["all_regions"] = True
    return {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com", "watches": [w]}
_ardb = os.path.join(_TMPD, "ebay_test_ar.db")
def _ar_run(cfg, fixtures):
    if os.path.exists(_ardb):
        os.remove(_ardb)
    m.DB_PATH = _ardb
    c = m.db_connect()
    c.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,"
              "below_alerted,price_alerted) VALUES('ARw','dec','psa10','2026-01-01T00:00:00',"
              "999,'$999','2026-01-01',0,0)")   # decoy so the watch isn't on its silent first run
    c.commit()
    m.fetch_all = lambda d, w, **k: list(fixtures)
    _sa.clear(); m.scan_once(cfg, c); c.close(); return list(_sa)
_jp = _PL("jp1", 3000); _jp["location"] = "Japan"
ok("all_regions off -> Japan filtered", _ar_run(_mk_arcfg(False), [_jp]) == [])
_jp2 = _PL("jp1", 3000); _jp2["location"] = "Japan"
ok("all_regions on -> Japan alerts",
   [x for x in _ar_run(_mk_arcfg(True), [_jp2]) if x["id"] == "jp1"] != [])

# cgc10 grade + one-time silent baseline (seed pre-existing CGC 10 without alerting)
_cdb = os.path.join(_TMPD, "ebay_test_cgc.db")
if os.path.exists(_cdb):
    os.remove(_cdb)
m.DB_PATH = _cdb
cconn = m.db_connect()
m.meta_set(cconn, "ask_baseline_done", m.ASK_BASELINE_VERSION)     # isolate the cgc10 baseline under test
_ccfg = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
         "watches": [{"name": "CG", "require": ["232/091"], "language": "any",
                      "grades": ["ungraded", "psa10", "cgc10"], "allow_unknown_region": True}]}
def _cg(item_id, title):
    return {"item_id": item_id, "title": title, "price_str": "$500.00", "price_low": 500.0,
            "currency": "USD", "url": f"https://ebay.com/itm/{item_id}", "image": None,
            "condition": None, "shipping": None, "bids": None, "format": None, "location": "USA"}
def _cg_run(fixtures):
    m.fetch_all = lambda d, w, **k: list(fixtures)
    _sa.clear(); m.scan_once(_ccfg, cconn); return list(_sa)
cconn.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,"
              "below_alerted,price_alerted) VALUES('CG','dec','psa10','2026-01-01T00:00:00',9,'$9','2026-01-01',0,0)")
cconn.commit()   # decoy so the watch is past its silent first-run seed
# scan 1 (baseline active): pre-existing CGC 10 is seeded silently; psa10 still alerts
_r1 = _cg_run([_cg("c1", "Mew ex 232/091 CGC 10 Gem Mint"), _cg("p1", "Mew ex 232/091 PSA 10")])
ok("cgc10 baseline: pre-existing CGC 10 not alerted", [x for x in _r1 if x["id"] == "c1"] == [])
ok("cgc10 baseline: psa10 still alerts (cgc10-only baseline)", any(x["id"] == "p1" for x in _r1))
ok("cgc10 baseline: seeded as cgc10",
   cconn.execute("SELECT grade FROM seen WHERE item_id='c1'").fetchone()[0] == "cgc10")
ok("cgc10 baseline: flag set", m.meta_get(cconn, "cgc10_baseline_done") == "1")
# scan 2 (baseline done): a genuinely new CGC 10 listing now alerts
_r2 = _cg_run([_cg("c1", "Mew ex 232/091 CGC 10 Gem Mint"), _cg("c2", "Mew ex 232/091 CGC 10 Pristine")])
ok("cgc10 post-baseline: new CGC 10 alerts", any(x["id"] == "c2" for x in _r2))
ok("cgc10 post-baseline: baselined CGC 10 not re-alerted", [x for x in _r2 if x["id"] == "c1"] == [])

# sealed_product: reject dash-code singles, keep the sealed box, don't false-reject ship dates
_sdb = os.path.join(_TMPD, "ebay_test_sealed.db")
if os.path.exists(_sdb):
    os.remove(_sdb)
m.DB_PATH = _sdb
sconn = m.db_connect()
m.meta_set(sconn, "ask_baseline_done", m.ASK_BASELINE_VERSION); m.meta_set(sconn, "cgc10_baseline_done", "1")
_scfg = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
         "watches": [{"name": "SEAL", "require": ["one piece", "3rd anniv", "set"], "exclude": ["campaign"],
                      "sealed_product": True, "grades": ["ungraded"], "language": "english", "min_price": 500}]}
def _sl(item_id, title, price):
    return {"item_id": item_id, "title": title, "price_str": f"${price}", "price_low": float(price),
            "currency": "USD", "url": f"https://ebay.com/itm/{item_id}", "image": None, "condition": None,
            "shipping": None, "bids": None, "format": None, "location": "USA"}
sconn.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted,"
              "price_alerted) VALUES('SEAL','dec','ungraded','2026-01-01T00:00:00',9,'$9','2026-01-01',0,0)")
sconn.commit()   # decoy so the watch is past its silent first run
m.fetch_all = lambda d, w, **k: [
    _sl("box1", "ONE PIECE CARD GAME English Version 3rd Anniversary Set BANDAI Sealed", 1000),
    _sl("box2", "One Piece Card Game 3rd Anniversary Set English In Hand Ships 8/10", 950),
    _sl("single", "Sabo OP13-120 Promo English Version 3rd Anniversary Set One Piece", 250),
    _sl("promo", "Luffy ST01-012 3rd Anniversary Winner Promo Prize Set One Piece English", 800),
    _sl("cheap", "One Piece 3rd Anniversary Set English Alt art", 160),
    _sl("camp", "One Piece 3rd Anniversary Campaign Promo Card Collection Set English", 40)]
_sa.clear(); m.scan_once(_scfg, sconn); _sids = {x["id"] for x in _sa}
ok("sealed: sealed box alerts", "box1" in _sids)
ok("sealed: box with ship-date 8/10 alerts (date != card number)", "box2" in _sids)
ok("sealed: dash-code single (OP13-120) rejected", "single" not in _sids)
ok("sealed: dash-code promo (ST01-012) rejected", "promo" not in _sids)
ok("sealed: under-min_price single rejected", "cheap" not in _sids)
ok("sealed: campaign promo collection rejected", "camp" not in _sids)

m.get_market_prices, m.active_asking_reference, m.send_discord = _sv_gmp, _sv_aar, _sv_send

# a non-numeric reference_override must NOT crash the scan (it wedges this + all later
# watches in the CI loop). The runtime guard skips it and keeps scanning. (audit fix)
_rodb = os.path.join(_TMPD, "ebay_test_ro.db")
if os.path.exists(_rodb):
    os.remove(_rodb)
m.DB_PATH = _rodb
_roconn = m.db_connect()
m.meta_set(_roconn, "ask_baseline_done", m.ASK_BASELINE_VERSION)
_ro_g, _ro_a, _ro_s = m.get_market_prices, m.active_asking_reference, m.send_discord
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}
_ro_sent = []
m.send_discord = lambda url, name, lst, grade, **k: _ro_sent.append(lst["item_id"])
m.fetch_all = lambda d, w, **k: [{"item_id": "r1", "title": "Mew ex 232/091 PSA 10",
    "price_str": "$50", "price_low": 50.0, "currency": "USD", "url": "http://x", "image": None,
    "condition": None, "shipping": None, "bids": None, "format": None, "location": "USA"}]
_ro_cfg = {"discord_webhook_url": "https://x", "ebay_domain": "www.ebay.com", "watches": [{
    "name": "RO", "require": ["232/091"], "grades": ["ungraded", "psa10"], "language": "any",
    "allow_unknown_region": True, "reference_override": {"ungraded": "oops"}}]}
_roconn.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,"
                "below_alerted,price_alerted) VALUES('RO','dec','psa10','2026-01-01T00:00:00',9,'$9','2026-01-01',0,0)")
_roconn.commit()   # decoy so it isn't a silent first run
try:
    m.scan_once(_ro_cfg, _roconn)
    ok("scan_once survives a bad reference_override", True)
    ok("...and still alerts the new listing", "r1" in _ro_sent)
except Exception as _roe:
    ok(f"scan_once survives a bad reference_override (raised {_roe!r})", False)
m.get_market_prices, m.active_asking_reference, m.send_discord = _ro_g, _ro_a, _ro_s

print("== priority fast-tier (full_scan=False) ==")
ok("priority_watches picks price_alert + explicit-priority watches",
   [w["name"] for w in m.priority_watches({"watches": [
       {"name": "A", "price_alerts": [{"below": 1}]}, {"name": "B"}, {"name": "C", "priority": True}]})] == ["A", "C"])
ok("priority_watches empty when none", m.priority_watches({"watches": [{"name": "B"}]}) == [])
_pdb = os.path.join(_TMPD, "ebay_test_prio.db")
if os.path.exists(_pdb):
    os.remove(_pdb)
m.DB_PATH = _pdb
_pconn = m.db_connect()
m.meta_set(_pconn, "ask_baseline_done", m.ASK_BASELINE_VERSION)
m.meta_set(_pconn, "cgc10_baseline_done", "1")
m.meta_set(_pconn, "health", "ok")
_pg, _pa2, _ps2, _pss = m.get_market_prices, m.active_asking_reference, m.send_discord, m.send_simple_discord
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}
m.send_simple_discord = lambda *a, **k: None   # health-down path -> don't hit the network
_psent = []
m.send_discord = lambda url, name, lst, grade, **k: _psent.append(lst["item_id"])
_pconn.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,"
               "below_alerted,price_alerted) VALUES('PR','dec','psa10','2026-01-01T00:00:00',9,'$9','2026-01-01',0,0)")
_pconn.commit()   # decoy so it isn't a silent first run
_pcfg = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com", "watches": [{
    "name": "PR", "require": ["232/091"], "grades": ["ungraded", "psa10"], "language": "any",
    "allow_unknown_region": True}]}
m.fetch_all = lambda d, w, **k: [{"item_id": "p1", "title": "Mew ex 232/091 PSA 10", "price_str": "$50",
    "price_low": 50.0, "currency": "USD", "url": "http://x", "image": None, "condition": None,
    "shipping": None, "bids": None, "format": None, "location": "USA"}]
m.scan_once(_pcfg, _pconn, full_scan=False)
ok("priority sub-scan still alerts a new listing", "p1" in _psent)
m.fetch_all = lambda d, w, **k: []          # a 0-scraped priority sub-scan must NOT flip health
m.scan_once(_pcfg, _pconn, full_scan=False)
ok("priority sub-scan skips the health check (no false down)", m.meta_get(_pconn, "health") == "ok")
m.scan_once(_pcfg, _pconn, full_scan=True)   # ...but a full 0-scraped scan does flag it
ok("full scan still runs the health check", m.meta_get(_pconn, "health") == "down")
m.get_market_prices, m.active_asking_reference, m.send_discord, m.send_simple_discord = _pg, _pa2, _ps2, _pss

# ==========================================================================
# 2026-09 deep-review fixes
# ==========================================================================
print("== grading-candidate / negated grades are not slabs ==")
for _t in ("Mew ex 232/091 Paldean Fates SIR NM PSA 10 Potential", "Mew ex 232/091 Pack Fresh - PSA 10 Candidate?",
           "Mew ex 232/091 SIR Raw Mint could be a PSA 10", "Gengar 94/102 POTENTIAL for PSA 10",
           "Mew ex 232/091 SIR raw psa 10?", "Charizard CGC 10 potential"):
    check(f"candidate -> ungraded: {_t[-24:]}", m.classify_grade(_t), "ungraded")
check("negated grade keeps real slab (cgc10)", m.classify_grade("Charizard CGC 10 Pristine not PSA 10"), "cgc10")
check("CGC 9.5 not PSA 10 -> other_graded", m.classify_grade("Charizard CGC 9.5 not PSA 10"), "other_graded")
for _t in ("Mew ex PSA 10 - Ready To Ship", "Mew ex PSA 10 (Possible Pop Increase)", "Awakened Potential PSA 10",
           "Prizm Auto PSA 10 Potential Penmanship", "Mew ex 232/091 PSA 10 GEM MINT"):
    check(f"real slab stays psa10: {_t[-26:]}", m.classify_grade(_t), "psa10")

print("== unnamed / unknown-grader slabs ==")
for _t in ("Monkey D. Luffy ST26-005 SP Foil Graded 2026", "Espeon Crossing the Ruins Holo PRISTINE 10 GOLD LABEL",
           "Lugia 9/111 Neo Genesis Holo TAG Graded NM/MT", "Espeon 1/75 wotc OCE - PRISTINE 10",
           "Light Arcanine 059 Ace Graded Mint 9"):
    check(f"unnamed slab -> other_graded: {_t[-26:]}", m.classify_grade(_t), "other_graded")
for _t in ("Charizard Gem Mint 10 Candidate", "Charizard Un-Graded raw", "Charizard Never been graded",
           "Charizard Ungraded NM", "Charizard Pre-Graded", "Lightly played not graded"):
    check(f"raw stays ungraded: {_t[-22:]}", m.classify_grade(_t), "ungraded")
check("BGS 10 Black Label stays bgs10", m.classify_grade("Charizard BGS 10 Black Label"), "bgs10")

print("== quantity multiples ==")
for _t in ("Rayquaza 3/17 Holo Pokemon POP Series 1 X6",
           "PSA 10 Luffy Gold Silver OP05-119 Manga Alt Art Parallel One Piece Set of 3",
           "4x Ho-Oh ex Lugia ex Promo Pokemon Card Play Set", "Mew ex 232/091 x2 NM"):
    ok(f"multiple flagged: {_t[-28:]}", m.is_bulk_or_sealed(_t))
for _t in ("Charizard X 25/108", "M Charizard EX X 13/106", "One Piece 3rd Anniversary Set English",
           "Rayquaza 3/17 Holo POP Series 1"):
    ok(f"single not flagged: {_t[-28:]}", not m.is_bulk_or_sealed(_t))

print("== merch / toy / fan-made excludes ==")
_DALLAS = ["luffy", "one piece day", "dallas"]
_ANNIV = ["one piece", ["3rd anniv", "third anniv"], "set"]
for _t, _req in (("Rayquaza V Alt Art Evolving Skies 194/203 Pokemon TCG Card Novelty Keychain", ["rayquaza", "194/203"]),
                 ("The Pokemon Company Mew ex 232/091 Special Illustration Rare (Keychain)", ["232/091"]),
                 ("Mew ex 232/091 Paldean Fates Card Blanket 50x60", ["232/091"]),
                 ("Mew ex 232/091 *Fantasy Art* Card", ["232/091"]),
                 ("Slowking H22/H32 Aquapolis Pokemon Hand Drawn DIY", ["slowking", "h22"]),
                 ("Tamashi Logotype Luffy Figure One Piece Day Dallas 2025 Exclusive", _DALLAS),
                 ("One Piece Day Dallas 2025 Luffy Key Chain", _DALLAS),
                 ("One Piece Card Game 3rd Anniversary Set Tamashii Logotype Luffy Figure", _ANNIV),
                 ("LUFFY's ONE PIECE Card Game -LOGOTYPE- Figure 3rd Anniversary Set Tamashii Nations", _ANNIV)):
    ok(f"merch rejected: {_t[:40]}", not m.matches_filters(_t, _req, []))
ok("genuine Dallas single still matches",
   m.matches_filters("Monkey.D.Luffy (One Piece Day Dallas 2025) ST10-006 One Piece Card", _DALLAS, []))
ok("genuine sealed 3rd Anniversary set still matches",
   m.matches_filters("ONE PIECE CARD GAME English Version 3rd Anniversary Set BANDAI IN HAND NEW", _ANNIV, []))

print("== played / damaged copies ==")
for _t in ("Lugia 9/111 Neo Genesis Holo DMG", "Umbreon H29/H32 Aquapolis Holo HP", "Espeon (LP/MP)",
           "Rayquaza 3/17 Pokemon TCG POP Series 1 HP", "Giratina (10) Reverse Holo Rare Platinum 10/127 HP",
           "Charizard 100/97 Heavily Played", "Lugia Holo creased"):
    ok(f"played: {_t[-30:]}", m.is_played(_t))
for _t in ("Espeon 1/75 Neo Discovery Holo Rare 80 HP English", "Charizard ex HP 170", "Charizard 310HP",
           "Lugia 9/111 No damage near mint", "Lugia 9/111 Holo NM"):
    ok(f"not played: {_t[-30:]}", not m.is_played(_t))
_pa_w = {"name": "PLY", "require": ["lugia"], "grades": ["ungraded"]}
_pa_pool = [dict(L(f"pl{i}", "$50.00", 50.0, title="Lugia 9/111 Holo HP")) for i in range(8)] + \
           [dict(L(f"nm{i}", f"${100 + i}", 100.0 + i, title="Lugia 9/111 Holo NM")) for i in range(8)]
ok("played copies excluded from the raw asking reference",
   m.active_asking_reference(_pa_pool, _pa_w, {"ungraded"}).get("ungraded", 0) >= 100)

print("== currency catch-all ==")
check("currency CHF other", m.detect_currency("CHF 2,500.00"), "OTHER")
check("currency trailing kr other", m.detect_currency("500 kr"), "OTHER")
check("currency peso symbol other", m.detect_currency("₱5,000.00"), "OTHER")
check("currency bare number stays None", m.detect_currency("90.00"), None)
check("currency $ still USD", m.detect_currency("$1,234.00 to $2,000.00"), "USD")

print("== sold probe: 1 query, 1 attempt, full scans only ==")
_sv_fa = m.fetch_all
_sold_kw = {}
m.fetch_all = lambda d, w, **k: (_sold_kw.update(k), [])[1]
_REAL["fetch_sold_sales"]("www.ebay.com", {"name": "w", "queries": ["a", "b", "c"]})
ok("sold probe max_queries=1", _sold_kw.get("max_queries") == 1)
ok("sold probe max_attempts=1 (no re-primes on the sign-in wall)", _sold_kw.get("max_attempts") == 1)
m.fetch_all = _sv_fa
_gdb = os.path.join(_TMPD, "ebay_test_gmp.db")
m.DB_PATH = _gdb
_gconn = m.db_connect()
_sv_fss = m.fetch_sold_sales
_fss_calls = []
m.fetch_sold_sales = lambda d, w, **k: (_fss_calls.append(w["name"]), [])[1]
_gm = _REAL["get_market_prices"](_gconn, "www.ebay.com", {"name": "G"}, {"psa10"}, allow_fetch=False)
ok("priority pass (allow_fetch=False) never probes sold", _fss_calls == [] and _gm == {"psa10": None})
_REAL["get_market_prices"](_gconn, "www.ebay.com", {"name": "G"}, {"psa10"})
ok("full pass still probes sold", _fss_calls == ["G"])
m.fetch_sold_sales = _sv_fss

print("== prime_session is throttled ==")
_sv_thr = m._throttle_request
_thr_n = []
m._throttle_request = lambda: _thr_n.append(1)
class _FakeS:
    def get(self, *a, **k):
        return None
m.prime_session("www.ebay.com", _FakeS())
ok("prime_session goes through the global throttle", _thr_n == [1])
m._throttle_request = _sv_thr

print("== query_window (rotation) ==")
_Q = ["A", "B", "C", "D"]
check("fixed window (not opted in)", m.query_window(_Q, 2, None), ["A", "B"])
check("rot 0", m.query_window(_Q, 2, 0), ["A", "B"])
check("rot 1", m.query_window(_Q, 2, 1), ["A", "C"])
check("rot 2", m.query_window(_Q, 2, 2), ["A", "D"])
check("rot 3 wraps", m.query_window(_Q, 2, 3), ["A", "B"])
check("under the cap -> all", m.query_window(["A", "B"], 2, 5), ["A", "B"])
check("no cap -> all", m.query_window(_Q, None, 1), _Q)

# ---- shared scan_once harness for the integration tests below ----
_sv = {k: getattr(m, k) for k in ("fetch_all", "fetch_listings", "get_market_prices", "active_asking_reference",
                                   "send_discord", "send_simple_discord", "get_session")}
_sv_sleep = m.time.sleep
m.time.sleep = lambda s: None          # fetch_all jitter / webhook pacing: no real waits in tests
_X = []                                # (event, item_id, kwargs)
_N = []                                # simple (health/notice) messages
m.send_discord = lambda url, name, lst, grade, **k: _X.append((k.get("event", "new"), lst["item_id"], k))
m.send_simple_discord = lambda url, title, text, color: _N.append((title, text))
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}

def _db(tag):
    p = os.path.join(_TMPD, f"ebay_test_{tag}.db")
    if os.path.exists(p):
        os.remove(p)
    m.DB_PATH = p
    c = m.db_connect()
    m.meta_set(c, "ask_baseline_done", m.ASK_BASELINE_VERSION)
    for _k in ("pa_baseline_done", "cgc10_baseline_done"):
        m.meta_set(c, _k, "1")
    m.meta_set(c, "health", "ok")
    return c

def _decoy(c, watch):
    c.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted,price_alerted)"
              " VALUES(?,'decoy','psa10','2026-01-01T00:00:00',9,'$9',?,0,0)",
              (watch, m.datetime.now(m.timezone.utc).date().isoformat()))
    c.commit()

def _scan(cfg, c, fixtures=None, **kw):
    if fixtures is not None:
        m.fetch_all = lambda d, w, **k: [dict(x) for x in fixtures.get(w["name"], [])]
    _X.clear(); _N.clear()
    m.scan_once(cfg, c, **kw)
    return list(_X)

def _cfg(*watches, **top):
    return {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
            "min_request_interval_seconds": 0, "watches": list(watches), **top}

print("== one bad watch doesn't blind the rest (+ notice, baselines held) ==")
_bc = _db("badwatch")
m.meta_set(_bc, "pa_baseline_done", "")
_bad = {"name": "BAD", "require": ["op05-119"], "grades": ["ungraded"], "min_price": "500",
        "price_alerts": [{"grade": "ungraded", "below": 100, "mention": "1"}]}
_good = {"name": "GOOD", "require": ["op05-119"], "grades": ["ungraded"]}
_bcfg = _cfg(_bad, _good)
for _w in ("BAD", "GOOD"):
    _decoy(_bc, _w)
_r = _scan(_bcfg, _bc, {"BAD": [L("b1", "$50.00", 50.0)], "GOOD": [L("g1", "$50.00", 50.0)]})
ok("good watch after a bad one still alerts", any(x[1] == "g1" for x in _r))
ok("watch error notice sent", any("Watch error" in t for t, _ in _N))
ok("pa_baseline NOT retired while a watch errors", m.meta_get(_bc, "pa_baseline_done") != "1")
_scan(_bcfg, _bc)
ok("watch error notice not repeated", not any("Watch error" in t for t, _ in _N))
_bad["min_price"] = 500
_scan(_bcfg, _bc)
ok("errors-cleared notice once fixed", any("cleared" in t for t, _ in _N))
ok("pa_baseline retired once every watch ran", m.meta_get(_bc, "pa_baseline_done") == "1")

print("== first real listing of a quiet watch alerts (seeded flag) ==")
_qc = _db("quiet")
_qw = {"name": "RARE", "require": ["020/141"], "grades": ["psa10"], "language": "any",
       "price_alerts": [{"grade": "psa10", "below": 2700, "mention": "U"}]}
_qcfg = _cfg(_qw)
_noise = [L("z1", "$5.00", 5.0, title="Some other card 1/2")]
for _i in range(3):
    _scan(_qcfg, _qc, {"RARE": _noise})        # results, but nothing matches
_r = _scan(_qcfg, _qc, {"RARE": _noise + [L("r1", "$2,400.00", 2400.0, title="Morty Ninetales 020/141 PSA 10")]})
ok("first real listing after noise-only scans alerts with the @mention",
   [(x[1], x[2].get("mention")) for x in _r] == [("r1", "U")])
_bl = _db("blocked")
_scan(_cfg(dict(_qw)), _bl, {"RARE": []})       # blocked first scan (0 results)
ok("a blocked first scan doesn't use up the silent seed", m.meta_get(_bl, "seeded:RARE") != "1")

print("== price-target edits re-baseline from stored prices (no ping flood) ==")
_pc = _db("pasig")
_pw = {"name": "MEW", "require": ["232/091"], "grades": ["psa10"], "language": "any"}
_pcfg = _cfg(_pw)
_old = [_PL("p0", 2400), _PL("p1", 2500), _PL("p2", 2600), _PL("p3", 3100)]
_scan(_pcfg, _pc, {"MEW": _old})               # silent first-run seed, no rules yet
_pw["price_alerts"] = [{"grade": "psa10", "below": 2700, "mention": "U"}]
ok("adding a target doesn't ping listings already under it", _scan(_pcfg, _pc, {"MEW": _old}) == [])
_pw["price_alerts"] = [{"grade": "psa10", "below": 3200, "mention": "U"}]
ok("raising a target doesn't ping either", _scan(_pcfg, _pc, {"MEW": _old}) == [])
_r = _scan(_pcfg, _pc, {"MEW": _old + [_PL("fresh", 2900)]})
ok("a brand-new under-target listing still pings", [(x[1], x[2].get("mention")) for x in _r] == [("fresh", "U")])
_pc.execute("UPDATE seen SET price=3300 WHERE item_id='p3'"); _pc.commit()
_pw["price_alerts"] = [{"grade": "psa10", "below": 3250, "mention": "U"}]   # edit + real crossing, same pass
_r = _scan(_pcfg, _pc, {"MEW": [_PL("p3", 3150)]})
ok("a real crossing in the edit pass still pings once",
   [(x[0], x[1], x[2].get("mention")) for x in _r] == [("price_alert", "p3", "U")])

print("== prune tombstones: a resurfacing listing is restored, not re-alerted ==")
_tc = _db("tomb")
_tw = {"name": "GIR", "require": ["186/196"], "grades": ["psa10"], "language": "any",
       "price_alerts": [{"grade": "psa10", "below": 3200, "mention": "U"}]}
_tcfg = _cfg(_tw, prune_days=30)
_GL = lambda i, p: {**_PL(i, p), "title": "PSA 10 Giratina V Alt Art 186/196 Lost Origin"}
_scan(_tcfg, _tc, {"GIR": [_GL("old", 3500), _GL("same", 3400), _GL("keep", 3600)]})
_40d = (m.datetime.now(m.timezone.utc) - m.timedelta(days=40)).date().isoformat()   # > prune_days, < tombstone expiry
_tc.execute("UPDATE seen SET last_seen=? WHERE item_id IN ('old','same')", (_40d,)); _tc.commit()
_scan(_tcfg, _tc, {"GIR": [_GL("keep", 3600)]})                     # prunes old + same into gone
ok("pruned rows are tombstoned", _tc.execute("SELECT COUNT(*) FROM gone").fetchone()[0] == 2)
ok("resurfacing at the same price: no 'new' alert",
   _scan(_tcfg, _tc, {"GIR": [_GL("keep", 3600), _GL("same", 3400)]}) == [])
_r = _scan(_tcfg, _tc, {"GIR": [_GL("keep", 3600), _GL("same", 3400), _GL("old", 3000)]})
ok("resurfacing under target: one price_alert @mention",
   [(x[0], x[1], x[2].get("mention")) for x in _r] == [("price_alert", "old", "U")])
_ic = _db("idle")
_iw = {"name": "IDLE", "require": ["999/999"], "grades": ["psa10"]}
_decoy(_ic, "IDLE")
_ic.execute("UPDATE seen SET last_seen='2026-01-01'"); _ic.commit()
_scan(_cfg(_iw, prune_days=30), _ic, {"IDLE": []})
ok("a watch that matched nothing keeps its rows (outage can't erase dedup)",
   _ic.execute("SELECT COUNT(*) FROM seen WHERE watch='IDLE'").fetchone()[0] == 1)

print("== reprice below min_price of a known copy alerts as a drop ==")
_mc = _db("minp")
_mw = {"name": "ST26", "require": ["st26-005"], "grades": ["ungraded"], "min_price": 300}
_mcfg = _cfg(_mw)
_decoy(_mc, "ST26")
_ML = lambda p: L("s1", f"${p:.2f}", float(p), title="Luffy ST26-005 SP English")
_scan(_mcfg, _mc, {"ST26": [_ML(350)]})
_r = _scan(_mcfg, _mc, {"ST26": [_ML(250)]})
ok("markdown below the floor alerts as a drop", [(x[0], x[1]) for x in _r] == [("drop", "s1")])
ok("a NEW listing below the floor is still filtered",
   _scan(_mcfg, _mc, {"ST26": [_ML(250), L("s2", "$200.00", 200.0, title="Luffy ST26-005 SP English")]}) == [])

print("== asking reference uses only the alertable region; played copies aren't deals ==")
m.active_asking_reference = _REAL["active_asking_reference"]
_rc = _db("region")
_rw = {"name": "REF", "require": ["st10-006"], "grades": ["ungraded"], "language": "any"}
_decoy(_rc, "REF")
_jp = [{**L(f"j{i}", "$300.00", 300.0, title="Luffy ST10-006 Dallas"), "location": "Japan"} for i in range(10)]
_us = [L(f"u{i}", f"${550 + 10 * i}.00", 550.0 + 10 * i, title="Luffy ST10-006 Dallas") for i in range(8)]
_scan(_cfg(_rw), _rc, {"REF": _jp + _us})      # all seen now
_r = _scan(_cfg(_rw), _rc, {"REF": _jp + _us + [L("deal", "$450.00", 450.0, title="Luffy ST10-006 Dallas")]})
_d = [x for x in _r if x[1] == "deal"]
_want = round(m._percentile([550.0 + 10 * i for i in range(8)] + [450.0], 25), 2)   # the new ask is in the pool too
ok("reference = US/CA asks only (overseas item-only asks ignored)", _d and _d[0][2].get("market_price") == _want)
ok("...so a real US deal is flagged", _d and _d[0][2].get("is_deal") is True)
_r = _scan(_cfg(dict(_rw, reference_override={"ungraded": 100})), _rc,
           {"REF": [L("hp1", "$60.00", 60.0, title="Luffy ST10-006 Dallas HP"),
                    L("nm1", "$60.00", 60.0, title="Luffy ST10-006 Dallas NM")]})
ok("played copy alerts but is not tagged a deal", [x[2].get("is_deal") for x in _r if x[1] == "hp1"] == [False])
ok("clean copy at the same price is a deal", [x[2].get("is_deal") for x in _r if x[1] == "nm1"] == [True])
m.active_asking_reference = lambda *a, **k: {}

print("== query rotation + per-query silent baseline ==")
m.fetch_all = _REAL["fetch_all"]
_rotc = _db("rot")
_ROTP = {"A": [], "B": [], "C": []}
m.fetch_listings = lambda d, q, **k: [dict(x) for x in _ROTP.get(q, [])]
_rotw = {"name": "ROT", "queries": ["A", "B", "C"], "rotate_queries": True, "require": ["232/091"],
         "grades": ["psa10"], "language": "any"}
_rotcfg = _cfg(_rotw, max_queries_per_watch=2)
_decoy(_rotc, "ROT")                                          # existing watch -> migration: A,B already ran
_ROTP["A"] = [_PL("a1", 3000)]
_ROTP["B"] = [_PL("b1", 3000)]
_ROTP["C"] = [_PL("c_old1", 3000), _PL("c_old2", 3100)]       # C's backlog: never fetched before
m.meta_set(_rotc, "query_rot", "0")
ok("rot 0 [A,B]: legacy window, existing listings are new", sorted(x[1] for x in _scan(_rotcfg, _rotc)) == ["a1", "b1"])
ok("rot 1 [A,C]: C's first run seeds its backlog silently", _scan(_rotcfg, _rotc) == [])
_ROTP["B"].append(_PL("b2", 3000))
ok("rot 2 [A,B]: new on B alerts", [x[1] for x in _scan(_rotcfg, _rotc)] == ["b2"])
_ROTP["C"].append(_PL("c_new", 3000))
ok("rot 3 [A,C]: genuinely new on C now alerts", [x[1] for x in _scan(_rotcfg, _rotc)] == ["c_new"])
_rot2 = _db("rot2")
_rw2 = dict(_rotw, name="ROT2")
_decoy(_rot2, "ROT2")
_ROTP.update({"A": [], "B": [], "C": []})
m.meta_set(_rot2, "query_rot", "1")
_scan(_cfg(_rw2, max_queries_per_watch=2), _rot2)              # C's first run is BLOCKED ([])
_ROTP["C"] = [_PL("cb1", 3000), _PL("cb2", 3000)]
m.meta_set(_rot2, "query_rot", "1")
ok("a blocked first run keeps the query fresh (backlog still seeds silently)",
   _scan(_cfg(_rw2, max_queries_per_watch=2), _rot2) == [])
_fx = _db("fixed")
_fw = {"name": "FIX", "queries": ["A", "B", "C"], "require": ["232/091"], "grades": ["psa10"], "language": "any"}
_decoy(_fx, "FIX")
_ROTP.update({"A": [], "B": [], "C": [_PL("never", 3000)]})
for _i in range(3):
    _scan(_cfg(_fw, max_queries_per_watch=2), _fx)
ok("a watch without rotate_queries keeps the fixed window (C never searched)",
   _fx.execute("SELECT COUNT(*) FROM seen WHERE item_id='never'").fetchone()[0] == 0)
_ROTP.update({"A": [_PL("x_new", 3000)], "B": []})
_fw2 = dict(_fw, queries=["C", "A", "B"])                       # config reorder promotes C
ok("reordering queries seeds the promoted query's backlog, alerts only the truly new",
   [x[1] for x in _scan(_cfg(_fw2, max_queries_per_watch=2), _fx)] == ["x_new"])

_ne = _db("notify")
_ROTP.update({"A": [_PL("ne1", 3000)], "B": [_PL("ne2", 3000)], "C": []})
ok("--notify-existing still alerts a brand-new watch's existing listings",
   sorted(x[1] for x in _scan(_cfg(dict(_fw, name="NE"), max_queries_per_watch=2), _ne, notify_existing=True))
   == ["ne1", "ne2"])
_ROTP["A"].append(_PL("ne3", 3000))
ok("...and its next genuinely new listing alerts too",
   [x[1] for x in _scan(_cfg(dict(_fw, name="NE"), max_queries_per_watch=2), _ne)] == ["ne3"])

print("== off-query (soft-block) pages -> HEALTH DOWN on the first scan ==")
m.fetch_all = _REAL["fetch_all"]
m.fetch_listings = _REAL["fetch_listings"]
def _junk_page():
    lis = "".join(f'<li class="s-card"><a href="https://www.ebay.com/itm/{900000000000 + i}">'
                  f'<span class="s-card__title">Plants vs Zombies comic book issue {i}</span></a>'
                  f'<span class="s-card__price">$5.00</span><span>Located in United States</span></li>'
                  for i in range(20))
    return "<html><body><ul>" + lis + "</ul>" + ("x" * 70000) + "</body></html>"
class _JunkResp:
    status_code = 200
    text = _junk_page()
class _JunkSession:
    def get(self, *a, **k):
        return _JunkResp()
m.get_session = lambda d: _JunkSession()
_hc = _db("degraded")
_hws = [{"name": f"H{i}", "queries": [q], "require": [q.split()[0]], "grades": ["ungraded"]}
        for i, q in enumerate(["giratina 186/196", "rayquaza 194/203", "espeon 196", "lugia 9/111"])]
for _w in _hws:
    _decoy(_hc, _w["name"])
m.meta_set(_hc, "qdone:H0", "[]")        # H0's query has never run (not the migrated legacy window)
_scan(_cfg(*_hws), _hc)
ok("all-off-query scan -> HEALTH DOWN immediately", m.meta_get(_hc, "health") == "down")
ok("...and names the soft-block, not the filters", any("unrelated" in t for _, t in _N))
ok("off-query pages don't mark a query as run", m.meta_get(_hc, "qdone:H0") == "[]")

print("== validate_config catches silent misconfigurations ==")
_vw = lambda **k: {"scan_workers": 1, "watches": [{"name": "V", "queries": ["q"], "require": ["x"], "grades": ["ungraded"], **k}]}
_vc = lambda **k: " | ".join(m.validate_config(_vw(**k)))
ok("unknown language warned", "NO language filter" in _vc(language="englsh"))
ok("trailing-space language warned", "NO language filter" in _vc(language="English "))
ok("CJK-only require clause warned", "normalizes to ''" in _vc(require=["ゼニガメ"]))
ok("typo'd key warned", "unknown key 'exlude'" in _vc(exlude=["x"]))
ok("string min_price warned", "must be a number" in _vc(min_price="500"))
ok("exclude that kills the require warned", "contains an exclude term" in _vc(require=["dark dragonair"], exclude=["dark"]))
ok("price target under min_price warned",
   "can never fire" in _vc(min_price=500, price_alerts=[{"grade": "ungraded", "below": 400, "mention": "1"}]))
ok("missing name warned", any("missing 'name'" in w for w in m.validate_config(
    {"watches": [{"queries": ["q"], "require": ["x"], "grades": ["ungraded"]}]})))
ok("bad top-level number warned", any("top-level" in w for w in m.validate_config(
    {"scan_workers": 1, "price_drop_pct": "5%", "watches": [{"name": "V", "queries": ["q"], "require": ["x"], "grades": ["ungraded"]}]})))
ok("clean watch -> no warnings", m.validate_config(_vw()) == [])

for _k, _v in _sv.items():
    setattr(m, _k, _v)
m.time.sleep = _sv_sleep

print("== watchdog: cancelled/queued runs can't mask a crash or a stall ==")
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("watchdog", os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".github", "watchdog.py"))
_wd = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_wd)
_wd.DB = os.path.join(_TMPD, "no_such.db")
_wd_msgs = []
_wd.discord = lambda msg: _wd_msgs.append(msg)
def _ago(h):
    return (m.datetime.now(m.timezone.utc) - m.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
def _wdrun(runs):
    _wd.recent_runs = lambda: runs
    _wd_msgs.clear(); _wd.main(); return " ".join(_wd_msgs)
ok("failure behind a newer cancelled run is caught", "FAILED" in _wdrun([
    {"createdAt": _ago(0.1), "startedAt": _ago(0.1), "status": "queued", "conclusion": ""},
    {"createdAt": _ago(0.5), "startedAt": _ago(0.5), "status": "completed", "conclusion": "cancelled"},
    {"createdAt": _ago(1.0), "startedAt": _ago(1.0), "status": "completed", "conclusion": "failure"}]))
ok("a queued run that never starts doesn't count as alive", "No monitor run has been active" in _wdrun([
    {"createdAt": _ago(0.2), "startedAt": _ago(0.2), "status": "queued", "conclusion": ""},
    {"createdAt": _ago(8), "startedAt": _ago(8), "status": "completed", "conclusion": "success"}]))
ok("a long in-progress run is not stale", _wdrun([
    {"createdAt": _ago(5.5), "startedAt": _ago(5.5), "status": "in_progress", "conclusion": ""}]) == "")
ok("a run that waited in the queue then ran is judged by when it ENDED (no false stale)", _wdrun([
    {"createdAt": _ago(7), "startedAt": _ago(7), "updatedAt": _ago(0.1), "status": "completed",
     "conclusion": "success"}]) == "")
ok("a job that hit timeout-minutes (reported 'cancelled') is flagged as hung", "job timeout" in _wdrun([
    {"createdAt": _ago(5), "startedAt": _ago(5), "updatedAt": _ago(0.8), "status": "completed",
     "conclusion": "cancelled"}]))
ok("healthy -> no alert", _wdrun([
    {"createdAt": _ago(0.3), "startedAt": _ago(0.3), "status": "in_progress", "conclusion": ""},
    {"createdAt": _ago(4), "startedAt": _ago(4), "status": "completed", "conclusion": "success"}]) == "")

# ==========================================================================
# Runner geography (HEALTH DOWN from a mexicocentral runner) + critic fixes
# ==========================================================================
_sv2 = {k: getattr(m, k) for k in ("fetch_all", "get_market_prices", "active_asking_reference",
                                    "send_discord", "send_simple_discord")}
_sv2_sleep = m.time.sleep
m.time.sleep = lambda s: None
_X2, _N2 = [], []
m.send_discord = lambda url, name, lst, grade, **k: _X2.append((k.get("event", "new"), lst["item_id"], k))
m.send_simple_discord = lambda url, title, text, color: _N2.append((title, text))
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}

def _db2(tag, ask="2"):
    p = os.path.join(_TMPD, f"ebay_test2_{tag}.db")
    if os.path.exists(p):
        os.remove(p)
    m.DB_PATH = p
    c = m.db_connect()
    m.meta_set(c, "ask_baseline_done", ask)
    m.meta_set(c, "pa_baseline_done", "1"); m.meta_set(c, "cgc10_baseline_done", "1")
    m.meta_set(c, "health", "ok")
    return c

def _scan2(cfg, c, fixtures, **kw):
    m.fetch_all = lambda d, w, **k: [dict(x) for x in fixtures.get(w["name"], [])]
    _X2.clear(); _N2.clear()
    m.scan_once(cfg, c, **kw)
    return list(_X2)

def _cfg2(*watches, **top):
    return {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
            "min_request_interval_seconds": 0, "watches": list(watches), **top}

print("== a persistently failing watch can't hold the ask re-baseline open for everyone ==")
_ac = _db2("askbl", ask="1")                     # production state before the v2 bump
_abad = {"name": "BAD", "require": ["op05-119"], "grades": ["ungraded"], "min_price": "50"}
_agood = {"name": "GOOD", "require": ["op05-119"], "grades": ["ungraded"],
          "reference_override": {"ungraded": 90}}
_acfg = _cfg2(_abad, _agood)
_afx = {"BAD": [L("b1", "$60.00", 60.0)], "GOOD": [L("g1", "$85.00", 85.0)]}
_scan2(_acfg, _ac, _afx)                          # BAD raises; GOOD seeds g1 (85 vs 90: not a deal) + baselines
ok("the bad watch really errors", any("Watch error" in t for t, _ in _N2))
_agood["reference_override"] = {"ungraded": 100}  # same price, reference moves: 85 < 90 = a real crossing
_r = _scan2(_acfg, _ac, _afx)
ok("healthy watch still gets below-market pings while another watch errors",
   [(x[0], x[1]) for x in _r] == [("below_market", "g1")])
ok("global ask baseline stays pending while the bad watch errors", m.meta_get(_ac, "ask_baseline_done") == "1")
ok("...but GOOD's own baseline is done", m.meta_get(_ac, "ask_bl:GOOD") == m.ASK_BASELINE_VERSION)

print("== changing a watch's matching rules seeds the newly matching backlog silently ==")
_fc = _db2("fltsig")
_fw = {"name": "FLT", "require": ["op05-119"], "grades": ["ungraded"]}
_fcfg = _cfg2(_fw)
_decoy_t = L("d0", "$10.00", 10.0)
_scan2(_fcfg, _fc, {"FLT": [_decoy_t]})                           # first run: seeds, records the signature
_old_backlog = L("bk1", "$60.00", 60.0, title="Monkey D Luffy #119 Awakening of the New Era Manga")
ok("a listing the old rules don't match is not alerted", _scan2(_fcfg, _fc, {"FLT": [_decoy_t, _old_backlog]}) == [])
_fw.pop("require"); _fw["match_any"] = [["op05-119"], ["luffy", "119", "awakening of the new era"]]
ok("broadened rules: the already-listed backlog is seeded silently",
   _scan2(_fcfg, _fc, {"FLT": [_decoy_t, _old_backlog]}) == [])
_new_one = L("nw1", "$70.00", 70.0, title="Luffy 119 Awakening of the New Era Manga Alt Art")
ok("...and the next genuinely new listing alerts",
   [x[1] for x in _scan2(_fcfg, _fc, {"FLT": [_decoy_t, _old_backlog, _new_one]})] == ["nw1"])
_mc2 = _db2("fltmig")
_mw2 = {"name": "MIG", "require": ["op05-119"], "grades": ["ungraded"]}
_mc2.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted,price_alerted)"
             " VALUES('MIG','old','ungraded','2026-01-01T00:00:00',9,'$9','2026-09-01',0,0)"); _mc2.commit()
ok("first deploy (no stored signature) just records it: new listings still alert",
   [x[1] for x in _scan2(_cfg2(_mw2), _mc2, {"MIG": [L("m1", "$50.00", 50.0)]})] == ["m1"])

print("== a zero-match scan says WHY (runner geography vs filters) ==")
_gc = _db2("geo")
_gws = [{"name": f"G{i}", "require": ["op05-119"], "grades": ["ungraded"]} for i in range(3)]
_mx = {f"G{i}": [{**L(f"x{i}{j}", "MXN $1,000.00", 1000.0), "location": "Mexico", "currency": "MXN"}
                 for j in range(5)] for i in range(3)}
for _i in range(3):
    _scan2(_cfg2(*_gws), _gc, _mx)
_down = [t for tt, t in _N2 if "health" in tt.lower()]
ok("HEALTH DOWN after 3 zero-match scans", m.meta_get(_gc, "health") == "down" and _down)
ok("...and the alert names the region gate + the foreign locations/currency",
   _down and "region:OTHER 15" in _down[0] and "Mexico" in _down[0] and "MXN" in _down[0])
ok("LAST_SCAN marks the full scan broken", m.LAST_SCAN.get("broken") is True)
_scan2(_cfg2(*_gws), _gc, {"G0": [L("ok1", "$50.00", 50.0)]})
ok("a matching scan clears the broken verdict", m.LAST_SCAN.get("broken") is False)

print("== runner egress check ==")
class _TR:
    def __init__(self, t): self.text = t
_sv_get = m.requests.get
m.requests.get = lambda *a, **k: _TR("fl=1\nip=1.2.3.4\nloc=MX\ntls=TLSv1.3\n")
check("egress country parsed from Cloudflare trace", m.egress_country(), "MX")
def _boom(*a, **k):
    raise m.requests.ConnectionError("offline")
m.requests.get = _boom
check("egress check failure -> unknown (never blocks scanning)", m.egress_country(), None)
m.requests.get = _sv_get

print("== CI loop rerolls onto a fresh runner (bounded) ==")
_sv_main = {k: getattr(m, k) for k in ("load_config", "enable_file_logging", "validate_config",
                                        "egress_country", "scan_once")}
_sv_mono, _sv_argv = m.time.monotonic, sys.argv
_clock = [1000.0]
m.time.monotonic = lambda: _clock[0]
m.time.sleep = lambda s: _clock.__setitem__(0, _clock[0] + s)
m.enable_file_logging = lambda: None
m.validate_config = lambda cfg: []
m.load_config = lambda: {"poll_interval_seconds": 300, "priority_interval_seconds": 120, "watches": [
    {"name": "P", "require": ["x"], "grades": ["ungraded"], "priority": True}]}
_rdb = os.path.join(_TMPD, "ebay_test_reroll.db")
if os.path.exists(_rdb):
    os.remove(_rdb)
m.DB_PATH = _rdb
_scans = []
def _fake_scan(cfg, conn, broken=False, **k):
    _scans.append(k.get("full_scan", True))
    _clock[0] += 60
    if k.get("full_scan", True):
        m.LAST_SCAN.update(broken=_BROKEN[0], scraped=100, matched=0 if _BROKEN[0] else 5, diag="d")
    return 0
_BROKEN = [False]
m.scan_once = _fake_scan
def _run_main(egress):
    m.egress_country = lambda: egress
    sys.argv = ["ebay_monitor.py", "--loop-for-minutes", "30", "--reroll-exit"]
    _scans.clear()
    try:
        m.main()
        return 0
    except SystemExit as e:
        return e.code
def _streak():
    _c = m.db_connect()
    return json.loads(m.meta_get(_c, "reroll_state", "") or "{}").get("streak", 0)
check("non-US egress -> exit 75 before scanning", (_run_main("MX"), len(_scans)), (75, 0))
check("...and the reroll is recorded", _streak(), 1)
_run_main("MX"); _run_main("MX")
check("budget exhausted after 3 rerolls -> scans anyway (no endless requeue)", (_run_main("MX"), _scans[:1]), (0, [True]))
_BROKEN[0] = False
_run_main("US")
check("a healthy full scan resets the reroll budget", _streak(), 0)
_BROKEN[0] = True
_code = _run_main("US")
check("US egress but 2 consecutive broken full scans -> exit 75", (_code, _scans.count(True)), (75, 2))
_BROKEN[0] = False
check("unknown egress (check failed) scans normally", _run_main(None), 0)
for _k, _v in _sv_main.items():
    setattr(m, _k, _v)
m.time.monotonic, sys.argv = _sv_mono, _sv_argv
m.time.sleep = lambda s: None

print("== market notice tells the truth (deals fall back to asking prices) ==")
_nc = _db2("notice")
m.meta_set(_nc, "market_circuit", json.dumps({"fails": 3, "until": (m.datetime.now(m.timezone.utc)
                                                                     + m.timedelta(hours=5)).isoformat()}))
m.meta_set(_nc, "market_notice", "sent")         # a user who already got the old wording
_nw = {"name": "N", "require": ["op05-119"], "grades": ["ungraded"]}
_scan2(_cfg2(_nw), _nc, {"N": [L("n1", "$50.00", 50.0)]})
ok("old 'paused' notice is corrected once", [t for t, _ in _N2 if "Sold comps" in t] == ["ℹ️ Sold comps unavailable — deals use asking prices"])
_scan2(_cfg2(_nw), _nc, {"N": [L("n1", "$50.00", 50.0)]})
ok("...and not repeated", not any("Sold comps" in t for t, _ in _N2))

for _k, _v in _sv2.items():
    setattr(m, _k, _v)
m.time.sleep = _sv2_sleep

# ==========================================================================
# Diff-review fixes: blind scans can't use up one-time baselines, etc.
# ==========================================================================
print("== gold labels / raw wordings / plush ==")
check("BGS Gold Pristine 10 -> bgs10", m.classify_grade("Luffy ST26-005 SP OP15 BGS Gold Pristine 10"), "bgs10")
check("BGS Gold Label 9.5 -> bgs9.5", m.classify_grade("Luffy ST26-005 SP BGS Gold Label 9.5"), "bgs9.5")
check("CGC Gold Label Pristine 10 -> cgc10", m.classify_grade("Mew ex CGC Gold Label Pristine 10"), "cgc10")
check("BGS Gold Label 10 candidate -> ungraded", m.classify_grade("Mew ex raw BGS Gold Label 10 candidate"), "ungraded")
check("Gold Star BGS 9 stays other_graded", m.classify_grade("Rayquaza Gold Star BGS 9"), "other_graded")
for _t in ("Giratina V 186/196 NM Non Graded", "Charizard Not Yet Graded", "Charizard Pre Graded",
           "Worth Getting Graded", "Charizard Not Professionally Graded", "Mew ex Raw Gem Mint 10/10",
           "Giratina Holo Rare Gem Mint 10/127", "Charizard Gem Mint 10 centering"):
    check(f"raw wording stays ungraded: {_t[-26:]}", m.classify_grade(_t), "ungraded")
check("'Professionally Graded 9 Mint' is still a slab", m.classify_grade("Charizard Professionally Graded 9 Mint"),
      "other_graded")
ok("'plus hard case' is not a plush", m.matches_filters(
    "Rayquaza V Alt Art 194/203 Evolving Skies NM - penny sleeve plus hard case", ["rayquaza", "194/203"], []))
ok("a plush toy is excluded", not m.matches_filters("Mew ex 232/091 Plush toy", ["232/091"], []))
ok("a plushie is excluded", not m.matches_filters("Mew 232/091 plushie", ["232/091"], []))

_sv3 = {k: getattr(m, k) for k in ("fetch_all", "fetch_listings", "get_market_prices", "active_asking_reference",
                                    "send_discord", "send_simple_discord", "get_session")}
_sv3_sleep = m.time.sleep
m.time.sleep = lambda s: None
_X3, _N3 = [], []
m.send_discord = lambda url, name, lst, grade, **k: _X3.append((k.get("event", "new"), lst["item_id"], k))
m.send_simple_discord = lambda url, title, text, color: _N3.append((title, text))
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}

def _db3(tag, **meta):
    p = os.path.join(_TMPD, f"ebay_test3_{tag}.db")
    if os.path.exists(p):
        os.remove(p)
    m.DB_PATH = p
    c = m.db_connect()
    base = {"ask_baseline_done": m.ASK_BASELINE_VERSION, "pa_baseline_done": "1", "cgc10_baseline_done": "1",
            "health": "ok"}
    base.update(meta)
    for k, v in base.items():
        m.meta_set(c, k, v)
    return c

def _scan3(cfg, c, fixtures, **kw):
    m.fetch_all = lambda d, w, **k: [dict(x) for x in fixtures.get(w["name"], [])]
    _X3.clear(); _N3.clear()
    m.scan_once(cfg, c, **kw)
    return list(_X3)

def _cfg3(*watches, **top):
    return {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
            "min_request_interval_seconds": 0, "watches": list(watches), **top}

def _mxify(lsts):
    return [{**x, "location": "Mexico"} for x in lsts]

print("== a blind (foreign-runner) scan can't use up one-time baselines ==")
_W1 = {"name": "NEWW", "require": ["op05-119"], "grades": ["ungraded"]}
_W2 = {"name": "OTHER", "require": ["st26-005"], "grades": ["ungraded"]}
_backlog = [L(f"b{i}", "$50.00", 50.0) for i in range(6)]
_other = [L(f"o{i}", "$60.00", 60.0, title="Luffy ST26-005 SP") for i in range(3)]
_bc3 = _db3("blindseed")
_scan3(_cfg3(_W1, _W2), _bc3, {"NEWW": _mxify(_backlog), "OTHER": _mxify(_other)})   # blind first scan
ok("blind first scan leaves a new watch's first-run seed pending", m.meta_get(_bc3, "seeded:NEWW") != "1")
ok("...so the first healthy scan seeds its backlog silently (no flood)",
   _scan3(_cfg3(_W1, _W2), _bc3, {"NEWW": _backlog, "OTHER": _other}) == [])
ok("...and later genuinely new listings alert",
   [x[1] for x in _scan3(_cfg3(_W1, _W2), _bc3, {"NEWW": _backlog + [L("nn", "$55.00", 55.0)], "OTHER": _other})] == ["nn"])

def _seen_row(c, watch, iid, price, grade="ungraded"):
    c.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted,price_alerted)"
              " VALUES(?,?,?,'2026-01-01T00:00:00',?,?,?,0,0)",
              (watch, iid, grade, price, f"${price}", m.datetime.now(m.timezone.utc).date().isoformat()))
    c.commit()

_ab3 = _db3("blindask", ask_baseline_done="1")      # a DB that predates the v2 re-baseline
_A1 = {"name": "A1", "require": ["op05-119"], "grades": ["ungraded"], "reference_override": {"ungraded": 100}}
_A2 = {"name": "A2", "require": ["st26-005"], "grades": ["ungraded"]}
_seen_row(_ab3, "A1", "a1", 85.0)                   # 85 vs ref 100: a v2 "below asking" on an OLD listing
for _o in _other:
    _seen_row(_ab3, "A2", _o["item_id"], 60.0)
_afx3 = {"A1": [L("a1", "$85.00", 85.0)], "A2": _other}
_scan3(_cfg3(_A1, _A2), _ab3, {"A1": _mxify(_afx3["A1"]), "A2": _mxify(_other)})   # blind first deploy scan
ok("a blind scan doesn't retire the ask re-baseline", m.meta_get(_ab3, "ask_baseline_done") == "1")
ok("...so the first healthy scan records old crossings silently (no below-market flood)",
   _scan3(_cfg3(_A1, _A2), _ab3, _afx3) == [])
ok("...and then the global baseline retires", m.meta_get(_ab3, "ask_baseline_done") == m.ASK_BASELINE_VERSION)

print("== the ask re-baseline can't retire while one watch saw nothing ==")
_ae3 = _db3("askempty", ask_baseline_done="1")
_E1 = {"name": "E1", "require": ["op05-119"], "grades": ["ungraded"], "reference_override": {"ungraded": 90}}
_E2 = {"name": "E2", "require": ["st26-005"], "grades": ["ungraded"], "reference_override": {"ungraded": 70}}
_seen_row(_ae3, "E1", "e1", 85.0)
_seen_row(_ae3, "E2", "e2", 60.0)
_scan3(_cfg3(_E1, _E2), _ae3, {"E1": [L("e1", "$85.00", 85.0)], "E2": []})    # E2's searches came back empty
ok("global stays pending while E2 is unbaselined", m.meta_get(_ae3, "ask_baseline_done") == "1")
_E2["reference_override"] = {"ungraded": 100}
ok("E2's first real pass baselines silently (its old $60 under the new $100 ref doesn't ping)",
   _scan3(_cfg3(_E1, _E2), _ae3, {"E1": [L("e1", "$85.00", 85.0)],
                                   "E2": [L("e2", "$60.00", 60.0, title="Luffy ST26-005 SP")]}) == [])

print("== a top-level matching edit is a rules edit too (flt_sig uses effective values) ==")
_tl = _db3("toplevel")
_TW = {"name": "TL", "require": ["op05-119"], "grades": ["ungraded"]}
_auc = [{**L(f"au{i}", "$40.00", 40.0), "bids": "3 bids"} for i in range(4)]
_scan3(_cfg3(_TW), _tl, {"TL": [L("t0", "$50.00", 50.0)] + _auc})
_scan3(_cfg3(_TW), _tl, {"TL": [L("t0", "$50.00", 50.0)] + _auc})
ok("turning on top-level include_auctions seeds the auction backlog silently",
   _scan3(_cfg3(_TW, include_auctions=True), _tl, {"TL": [L("t0", "$50.00", 50.0)] + _auc}) == [])

print("== an empty-but-real fresh page marks its query as run ==")
m.fetch_all = _REAL["fetch_all"]
_PAGES = {}
def _fl_pages(d, q, **k):
    r = m._Results([dict(x) for x in _PAGES.get(q, [])])
    r.page_ok = q in _PAGES
    return r
m.fetch_listings = _fl_pages
_ec = _db3("emptyq")
_EQ = {"name": "EQ", "queries": ["A", "B", "C"], "rotate_queries": True, "require": ["232/091"],
       "grades": ["psa10"], "language": "any"}
_decoy(_ec, "EQ")
_PAGES.update({"A": [_PL("x1", 3000)], "B": [], "C": []})       # C is a real results page with 0 items
m.meta_set(_ec, "query_rot", "1")
_X3.clear(); m.scan_once(_cfg3(_EQ, max_queries_per_watch=2), _ec)       # window [A, C]
ok("C recorded as run although it returned nothing", "C" in json.loads(m.meta_get(_ec, "qdone:EQ") or "[]"))
_PAGES["C"] = [_PL("c_first", 3000)]
m.meta_set(_ec, "query_rot", "1")
_X3.clear(); m.scan_once(_cfg3(_EQ, max_queries_per_watch=2), _ec)
ok("...so the first listing C finds alerts (not silently seeded)", "c_first" in [x[1] for x in _X3])
_PAGES.clear(); _PAGES.update({"A": [], "C": []})               # EVERY page blank: layout break
_eb = _db3("emptyall")
_decoy(_eb, "EQ")
m.meta_set(_eb, "query_rot", "1")
_X3.clear(); m.scan_once(_cfg3(_EQ, max_queries_per_watch=2), _eb)
ok("a fetch where every page is blank credits no query", "C" not in json.loads(m.meta_get(_eb, "qdone:EQ") or "[]"))
m.fetch_listings = _sv3["fetch_listings"]

print("== an all-watches-errored scan blames the config, not eBay ==")
_ec2 = _db3("allerr")
_bw = [{"name": f"BW{i}", "require": ["op05-119"], "grades": ["ungraded"], "price_drop_pct": "5%"} for i in range(2)]
_scan3(_cfg3(*_bw), _ec2, {"BW0": [L("z", "$5.00", 5.0)], "BW1": [L("y", "$5.00", 5.0)]})
ok("not judged a broken (reroll-worthy) scan", m.LAST_SCAN.get("broken") is False and m.LAST_SCAN.get("errored"))
ok("no HEALTH DOWN blaming eBay", m.meta_get(_ec2, "health") == "ok" and not any("health" in t.lower() for t, _ in _N3))
ok("the watch-error notice still goes out", any("Watch error" in t for t, _ in _N3))

print("== validate_config never raises on malformed values ==")
for _bad in ({"exclude": 5}, {"match_any": True}, {"queries": 5}, {"grades": [10]},
             {"price_alerts": [{"below": 500, "grade": 10}]}, {"allowed_regions": [1]}):
    try:
        _w = m.validate_config({"scan_workers": 1, "max_queries_per_watch": 2, "watches": [
            {"name": "V", "queries": ["q"], "require": ["x"], "grades": ["ungraded"], **_bad}]})
        ok(f"no crash on {_bad}", True)
    except Exception as _e:
        ok(f"no crash on {_bad} (raised {_e!r})", False)
ok("rotate_queries with a cap of 1 is flagged", any("rotate_queries needs" in w for w in m.validate_config(
    {"scan_workers": 1, "max_queries_per_watch": 1, "watches": [
        {"name": "R", "queries": ["a", "b"], "require": ["x"], "grades": ["ungraded"], "rotate_queries": True}]})))
ok("a non-object watch is reported as ignored", any("ignored" in w for w in m.validate_config(
    {"scan_workers": 1, "watches": ["oops", {"name": "V", "queries": ["q"], "require": ["x"], "grades": ["ungraded"]}]})))

print("== tombstoned rows follow a price-target edit ==")
_tg = _db3("tombpa")
_tg.execute("INSERT INTO gone(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted,price_alerted)"
            " VALUES('TP','g1','psa10','2026-01-01',3000,'$3,000','2026-08-01',0,0)"); _tg.commit()
_decoy(_tg, "TP")
_TPW = {"name": "TP", "require": ["232/091"], "grades": ["psa10"], "language": "any",
        "price_alerts": [{"grade": "psa10", "below": 3200, "mention": "U"}]}
_scan3(_cfg3(_TPW), _tg, {"TP": [_PL("other", 5000)]})
ok("a gone row under the new target is flagged, so it can't ping on resurfacing",
   _tg.execute("SELECT price_alerted FROM gone WHERE item_id='g1'").fetchone()[0] == 1)

for _k, _v in _sv3.items():
    setattr(m, _k, _v)
m.time.sleep = _sv3_sleep

print("== an old listing first re-seen via a never-run query: no stale drop, target still pings ==")
_sv4 = {k: getattr(m, k) for k in ("fetch_all", "fetch_listings", "get_market_prices", "active_asking_reference",
                                    "send_discord", "send_simple_discord")}
_sv4_sleep = m.time.sleep
m.time.sleep = lambda s: None
_X4 = []
m.send_discord = lambda url, name, lst, grade, **k: _X4.append((k.get("event", "new"), lst["item_id"], k.get("mention")))
m.send_simple_discord = lambda *a, **k: None
m.get_market_prices = lambda *a, **k: {}
m.active_asking_reference = lambda *a, **k: {}
m.fetch_all = _REAL["fetch_all"]
_P4 = {}
m.fetch_listings = lambda d, q, **k: [dict(x) for x in _P4.get(q, [])]
_f4 = os.path.join(_TMPD, "ebay_test4_stale.db")
if os.path.exists(_f4):
    os.remove(_f4)
m.DB_PATH = _f4
_c4 = m.db_connect()
for _k, _v in (("ask_baseline_done", m.ASK_BASELINE_VERSION), ("pa_baseline_done", "1"),
               ("cgc10_baseline_done", "1"), ("health", "ok")):
    m.meta_set(_c4, _k, _v)
_W4 = {"name": "ST", "queries": ["A", "B", "C"], "rotate_queries": True, "require": ["232/091"],
       "grades": ["psa10"], "language": "any", "price_alerts": [{"grade": "psa10", "below": 2700, "mention": "U"}]}
for _iid, _pr in (("oldc", 3500.0), ("oldt", 3000.0)):
    _c4.execute("INSERT INTO seen(watch,item_id,grade,first_seen,price,price_str,last_seen,below_alerted,price_alerted)"
                " VALUES('ST',?,'psa10','2026-08-01T00:00:00',?,?,?,0,0)",
                (_iid, _pr, f"${_pr}", m.datetime.now(m.timezone.utc).date().isoformat()))
_c4.commit()
_P4.update({"A": [_PL("a1", 3100)], "B": [], "C": [_PL("oldc", 2900), _PL("oldt", 2500)]})
m.meta_set(_c4, "query_rot", "1")                               # window [A, C]; C never ran
m.scan_once({"discord_webhook_url": "https://x", "ebay_domain": "www.ebay.com", "min_request_interval_seconds": 0,
             "max_queries_per_watch": 2, "watches": [_W4]}, _c4)
_ev4 = {(e, i) for e, i, _ in _X4}
ok("a 17% cut seen for the first time via a fresh query sends no stale 'drop'", ("drop", "oldc") not in _ev4)
ok("...its stored price is re-baselined", _c4.execute("SELECT price FROM seen WHERE item_id='oldc'").fetchone()[0] == 2900)
ok("...but a listing now under the price target still @mentions", ("price_alert", "oldt") in _ev4)
for _k, _v in _sv4.items():
    setattr(m, _k, _v)
m.time.sleep = _sv4_sleep

print("\n==== RESULT ====")
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
print("ALL PASSED")
