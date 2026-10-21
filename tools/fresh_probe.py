#!/usr/bin/env python3
"""Diagnostics: how fresh are eBay's newest-first search results? (corpus.yml ab_mode=fresh)

Polls several URL variants round-robin (shuffled each round) for FRESH_MINUTES and records,
per variant, when each listing was first seen next to eBay's listing time ('Oct-18 17:57',
minute precision). Listings that go live during the run give the listed -> searchable lag;
listings seen by two variants show whether a variant (no-cache flag, cache-busting param,
smaller page) is served fresher results. Also fetches a few RSS pages and item pages, and
records any second-precision timestamps they carry, to calibrate the minute-rounded times.
Never alerts, never touches seen.db. Writes ab.json (+ a few raw pages in raw/).

    FRESH_MINUTES=25 python tools/fresh_probe.py ab.json
"""
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_monitor as m  # noqa: E402

DOMAIN = "www.ebay.com"
SWEEP = "(giratina,mew,mewtwo,rayquaza,oshawott)"     # the monitor's priority sweep
VARIANTS = [
    ("sweep", SWEEP, {"_ipg": "240", "LH_BIN": "1"}),
    ("sweep_rtnc", SWEEP, {"_ipg": "240", "LH_BIN": "1", "rt": "nc"}),
    ("sweep_bust", SWEEP, {"_ipg": "240", "LH_BIN": "1", "_fp": None}),     # random value per fetch
    ("sweep_60", SWEEP, {"_ipg": "60", "LH_BIN": "1"}),
    ("firehose", "pokemon", {"_ipg": "240", "LH_BIN": "1", "_sacat": "183454"}),
    ("firehose_bust", "pokemon", {"_ipg": "240", "LH_BIN": "1", "_sacat": "183454", "_fp": None}),
]
STAMP_RES = [
    re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?"),
    re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, 20\d\d,? "
               r"\d{1,2}:\d\d:\d\d(?: ?[AP]M)?(?: [A-Z]{2,4})?"),
    re.compile(r"\"(?:startTime|start_time|itemCreationDate|listingStartDate|creationDate|"
               r"startDate|endTime)\"\s*:\s*\"?[^,}\]]{4,40}"),
]


def _get(url, attempts=4):
    """Raw GET with the monitor's session, spacing and 403 re-prime retries."""
    s = m.get_session(DOMAIN)
    r = None
    for i in range(attempts):
        m._throttle_request()
        r = s.get(url, headers={"Referer": f"https://{DOMAIN}/"}, timeout=25)
        if r.status_code != 403 and not m._looks_blocked(r.text):
            return r, i + 1
        m.prime_session(DOMAIN)
    return r, attempts


def _stamps(text):
    out = []
    for rx in STAMP_RES:
        for mt in rx.finditer(text):
            a = max(0, mt.start() - 70)
            out.append({"match": mt.group(0)[:60], "context": text[a:mt.end() + 30].replace("\n", " ")})
            if len(out) >= 40:
                return out
    return out


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "ab.json"
    country = m.egress_country()
    print(f"egress country: {country}")
    if country and country != "US":
        print("non-US egress: eBay would serve a local-buyer page; refusing to run")
        return m.EXIT_REROLL
    m._MIN_REQUEST_INTERVAL = float(os.environ.get("FRESH_SPACING", "2.0"))
    minutes = float(os.environ.get("FRESH_MINUTES", "25"))
    t0 = time.time()
    res = {"started": t0, "minutes": minutes, "fetches": [], "first_seen": {v[0]: {} for v in VARIANTS},
           "items": {}, "rss": [], "pages": {}}
    rnd = 0
    while time.time() - t0 < minutes * 60:
        order = list(VARIANTS)
        random.shuffle(order)
        for name, q, params in order:
            p = {k: (str(random.randrange(10**8)) if v is None else v) for k, v in params.items()}
            t_req = time.time()
            try:
                items, err = m.fetch_listings(DOMAIN, q, params=p), None
            except Exception as e:
                items, err = [], repr(e)[:120]
            t = time.time()
            res["fetches"].append({"v": name, "t_req": t_req, "t": t, "n": len(items), "err": err,
                                   "ok": bool(getattr(items, "page_ok", bool(items)))})
            fs = res["first_seen"][name]
            for rank, it in enumerate(items):
                iid = it["item_id"]
                fs.setdefault(iid, [t_req, rank])
                if iid not in res["items"]:
                    la = it.get("listed_at")
                    res["items"][iid] = {"listed_at": la.timestamp() if la else None,
                                         "title": it["title"][:90], "format": it.get("format"),
                                         "location": it.get("location"), "price": it.get("price_low")}
        if rnd % 6 == 0:
            url = m.build_search_url(DOMAIN, SWEEP, params={"_ipg": "60", "LH_BIN": "1", "_rss": "1"})
            try:
                r, n = _get(url)
                res["rss"].append({"t": time.time(), "status": r.status_code, "attempts": n,
                                   "ctype": r.headers.get("content-type"), "len": len(r.text),
                                   "head": r.text[:300], "pubdates": re.findall(r"<pubDate>([^<]+)</pubDate>", r.text)[:20],
                                   "links": re.findall(r"/itm/(\d{9,15})", r.text)[:20]})
            except Exception as e:
                res["rss"].append({"t": time.time(), "err": repr(e)[:120]})
        rnd += 1
        done = sum(1 for f in res["fetches"] if f["n"])
        print(f"round {rnd}: {len(res['fetches'])} fetches ({done} with items), {len(res['items'])} items")

    # Second-precision calibration: item pages of listings that went live during the run.
    fresh = sorted((iid for iid, it in res["items"].items()
                    if it["listed_at"] and it["listed_at"] > t0 + 120),
                   key=lambda i: -res["items"][i]["listed_at"])[:8]
    os.makedirs("raw", exist_ok=True)
    for k, iid in enumerate(fresh):
        try:
            r, n = _get(f"https://{DOMAIN}/itm/{iid}")
            res["pages"][iid] = {"t": time.time(), "status": r.status_code, "attempts": n,
                                 "stamps": _stamps(r.text)}
            if k < 3:
                with open(os.path.join("raw", f"itm_{iid}.html"), "w", encoding="utf-8") as fh:
                    fh.write(r.text)
        except Exception as e:
            res["pages"][iid] = {"err": repr(e)[:120]}
    json.dump(res, open(out, "w", encoding="utf-8"))
    print(f"wrote {out}: {len(res['fetches'])} fetches, {len(res['items'])} items, {len(fresh)} item pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
