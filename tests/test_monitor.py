#!/usr/bin/env python3
"""Offline regression tests for ebay_monitor (no network). Run: python tests/test_monitor.py

Covers grade classification, language, card/lot/auction/region filters, price
parsing, config validation, and the end-to-end new-listing + price-drop logic in
scan_once (with fetch/Discord mocked and a temp DB).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_monitor as m

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
check("PSA 10", m.classify_grade("PSA 10 Luffy ST26-005"), "psa10")
check("PSA 100 not PSA10", m.classify_grade("Lot of PSA 100 Luffy"), "other_graded")
check("BGS 9.5", m.classify_grade("Luffy BGS 9.5"), "bgs9.5")
check("BGS 10 not 9.5", m.classify_grade("Luffy BGS 10 Pristine"), "bgs10")
check("Beckett 9.5", m.classify_grade("Luffy Beckett 9.5"), "bgs9.5")
check("PSA 9 -> other", m.classify_grade("Luffy PSA 9"), "other_graded")
check("CGC 10 -> other", m.classify_grade("Luffy CGC 10"), "other_graded")
check("raw", m.classify_grade("Luffy ST26-005 SP Foil English"), "ungraded")
check("ACE 10 slab -> other", m.classify_grade("O-Nami ACE 10 OP06-101"), "other_graded")
check("TAG 10 slab -> other", m.classify_grade("Chopper TAG 10 ST01-006"), "other_graded")
check("ARS 10 slab -> other", m.classify_grade("Luffy ARS 10 ST26-005"), "other_graded")
check("Ace character raw", m.classify_grade("Portgas D. Ace OP01-002 NM"), "ungraded")
check("with tag raw", m.classify_grade("Nami OP06-101 mint with tag"), "ungraded")

print("== language ==")
check("japanese word", m.title_language("Luffy ST26-005 Japanese"), "japanese")
check("cjk", m.title_language("ルフィ ST26-005"), "cjk")
check("unknown", m.title_language("Luffy ST26-005 Foil"), "unknown")
ok("en keeps unknown", m.passes_language("Luffy ST26-005 Foil", "english"))
ok("en drops japanese", not m.passes_language("Luffy Japanese", "english"))
ok("any keeps japanese", m.passes_language("Luffy Japanese", "any"))

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

print("== parse_price / price_ok / clean_title ==")
check("price simple", m.parse_price("$949.99")[1], 949.99)
check("price thousands", m.parse_price("$2,600.00")[1], 2600.0)
check("price range low", m.parse_price("$10.00 to $20.00")[1], 10.0)
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

# --------------------------------------------------------------------------
print("== scan_once: new-listing + dedup + price-drop (mocked) ==")

def L(item_id, price_str, price_low, title="Luffy OP05-119 Manga English"):
    return {"item_id": item_id, "title": title, "price_str": price_str, "price_low": price_low,
            "url": f"https://www.ebay.com/itm/{item_id}", "image": None, "condition": None,
            "shipping": None, "bids": None, "format": None, "location": "United States"}

WATCH = {"name": "W", "require": ["op05-119"], "grades": ["ungraded"], "language": "english"}
CFG = {"discord_webhook_url": "https://discord.test/wh", "ebay_domain": "www.ebay.com",
       "price_drop_pct": 5, "price_drop_min": 1, "watches": [WATCH]}

tmp = os.path.join(tempfile.gettempdir(), "ebay_test_monitor.db")
if os.path.exists(tmp):
    os.remove(tmp)
m.DB_PATH = tmp
conn = m.db_connect()
sends = []
m.send_discord = lambda url, name, lst, grade, event="new", old_price_str=None, drop_pct=None, market_price=None: \
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

print("== health check + prune ==")
m.meta_set(conn, "health", "ok"); health.clear()
run([])                                   # 0 scraped across all watches -> down (scrape broken)
ok("health down on 0 scraped", any("scraped across" in txt for _, txt in health))
health.clear()
run([L("1", "$200.00", 200.0)])           # scraping + matching back -> recovered
ok("health recovered alerted", any("recover" in t.lower() for t, _ in health))
health.clear()
run([L("z", "$10.00", 10.0, "Unrelated Card XYZ")])   # scraped>0 but 0 matched -> down
ok("health down on 0 matched (filter wipeout)", any("0 matched" in txt for _, txt in health))

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
MKT = {"v": 100.0}
m.get_market_price = lambda conn_, domain, watch, **k: MKT["v"]
run([L("b2", "$98.00", 98.0)])            # market 100 -> 98 not below (needs <95); seeds below_alerted=0
MKT["v"] = 120.0                          # market rises -> 98 now below 120*0.95=114
s = run([L("b2", "$98.00", 98.0)])
ok("below-market crossing pings", any(r[0] == "below_market" and r[1] == "b2" for r in s))
ok("below-market not repeated", not any(r[0] == "below_market" for r in run([L("b2", "$98.00", 98.0)])))
below_flag = conn.execute("SELECT below_alerted FROM seen WHERE item_id='b2'").fetchone()[0]
ok("below_alerted persisted", below_flag == 1)

print("\n==== RESULT ====")
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
print("ALL PASSED")
