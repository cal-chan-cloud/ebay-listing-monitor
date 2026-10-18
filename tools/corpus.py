#!/usr/bin/env python3
"""Diagnostics: fetch every watch's searches ONCE (throttled) and dump the raw results to JSON.

Used to validate matching rules offline against real eBay titles (review / new-watch checks).
It never alerts and never touches seen.db. Run it from a US machine: eBay localizes results
by IP, so the script refuses to run when the egress country isn't the US.

    python tools/corpus.py corpus.json          # CORPUS_SPACING=3.0 seconds between requests
    CORPUS_LIMIT=4 CORPUS_RAW=4 python tools/corpus.py corpus.json   # + raw HTML of 4 pages in raw/
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_monitor as m  # noqa: E402

FIELDS = ("item_id", "title", "price_str", "price_low", "currency", "shipping", "bids", "format",
          "location", "condition", "url")


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus.json"
    country = m.egress_country()
    print(f"egress country: {country}")
    if country and country != "US":
        print("non-US egress: eBay would serve a local-buyer page; refusing to build a corpus")
        return m.EXIT_REROLL
    m._MIN_REQUEST_INTERVAL = float(os.environ.get("CORPUS_SPACING", "3.0"))
    cfg = m.load_config()
    jobs = [(w["name"], i, q) for w in cfg["watches"] for i, q in enumerate(m.watch_queries(w))]
    limit = int(os.environ.get("CORPUS_LIMIT", "0") or 0)
    if limit > 0:
        jobs = jobs[:limit]
    raw_n = int(os.environ.get("CORPUS_RAW", "0") or 0)
    if raw_n > 0:   # raw pages (for parser checks): one extra plain GET per saved page
        os.makedirs("raw", exist_ok=True)
        session = m.get_session("www.ebay.com")
        for n, (name, qi, q) in enumerate(jobs[:raw_n], 1):
            m._throttle_request()
            resp = session.get(m.build_search_url("www.ebay.com", q), headers={"Referer": "https://www.ebay.com/"},
                               timeout=25)
            with open(os.path.join("raw", f"page{n}.html"), "w", encoding="utf-8") as f:
                f.write(resp.text)
            print(f"raw page {n}: HTTP {resp.status_code}, {len(resp.text)} chars ({q})")
    corpus, t0 = [], time.time()
    for n, (name, qi, q) in enumerate(jobs, 1):
        try:
            items, err = m.fetch_listings("www.ebay.com", q, max_attempts=2), None
        except Exception as e:  # keep going: one blocked query must not lose the rest
            items, err = [], repr(e)[:200]
        corpus.append({"watch": name, "query_index": qi, "query": q, "error": err,
                       "page_ok": bool(getattr(items, "page_ok", False)),
                       "items": [{k: it.get(k) for k in FIELDS} for it in items]})
        print(f"[{n}/{len(jobs)}] {len(items):3d} items  {name[:38]:38s} q{qi}: {q[:48]}"
              + (f"  ERROR {err}" if err else ""), flush=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"built_at_unix": int(time.time()), "egress": country, "corpus": corpus}, f,
                  ensure_ascii=False)
    print(f"done in {time.time() - t0:.0f}s: {len(corpus)} searches -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
