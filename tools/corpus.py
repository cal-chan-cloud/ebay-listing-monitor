#!/usr/bin/env python3
"""Diagnostics: fetch every watch's searches ONCE (throttled) and dump the raw results to JSON.

Used to validate matching rules offline against real eBay titles (review / new-watch checks).
It never alerts and never touches seen.db. Run it from a US machine: eBay localizes results
by IP, so the script refuses to run when the egress country isn't the US.

    python tools/corpus.py corpus.json          # CORPUS_SPACING=3.0 seconds between requests
    CORPUS_LIMIT=4 CORPUS_RAW=4 python tools/corpus.py corpus.json   # + raw HTML of 4 pages in raw/
    CORPUS_QUERIES="magikarp wailord gx 161/181;mew ex 232/091 psa 10|_sop=15&_udhi=2700" \\
        python tools/corpus.py corpus.json      # ad-hoc searches instead of the watches'
                                                # ('|' adds/overrides URL params)
"""
import json
import os
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_monitor as m  # noqa: E402

FIELDS = ("item_id", "title", "price_str", "price_low", "currency", "shipping", "bids", "format",
          "location", "condition", "url")
DOMAIN = "www.ebay.com"


def with_params(url, extra):
    """url with the 'k=v&k2=v2' params in `extra` added or replacing existing ones."""
    if not extra:
        return url
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update(dict(parse_qsl(extra, keep_blank_values=True)))
    return urlunsplit(parts._replace(query=urlencode(params)))


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus.json"
    country = m.egress_country()
    print(f"egress country: {country}")
    if country and country != "US":
        print("non-US egress: eBay would serve a local-buyer page; refusing to build a corpus")
        return m.EXIT_REROLL
    m._MIN_REQUEST_INTERVAL = float(os.environ.get("CORPUS_SPACING", "3.0"))
    custom = [q.strip() for q in os.environ.get("CORPUS_QUERIES", "").split(";") if q.strip()]
    if custom:
        jobs = [("(ad hoc)", i, q) for i, q in enumerate(custom)]
    else:
        cfg = m.load_config()
        jobs = [(w["name"], i, q) for w in cfg["watches"] for i, q in enumerate(m.watch_queries(w))]
    limit = int(os.environ.get("CORPUS_LIMIT", "0") or 0)
    if limit > 0:
        jobs = jobs[:limit]
    raw_n = int(os.environ.get("CORPUS_RAW", "0") or 0)

    # Capture the page each search actually got (raw HTML for parser checks), and apply the
    # per-query URL extras, without changing fetch_listings itself.
    session = m.get_session(DOMAIN)
    real_get, last = session.get, {}

    def _get(*a, **k):
        r = real_get(*a, **k)
        last["code"], last["text"] = r.status_code, r.text
        return r
    session.get = _get
    real_url = m.build_search_url
    corpus, t0, saved = [], time.time(), 0
    for n, (name, qi, q) in enumerate(jobs, 1):
        query, _, extra = q.partition("|")
        m.build_search_url = lambda d, qq, **k: with_params(real_url(d, qq, **k), extra.strip())
        last.clear()
        try:
            items, err = m.fetch_listings(DOMAIN, query.strip(), max_attempts=4), None
        except Exception as e:  # keep going: one blocked query must not lose the rest
            items, err = [], repr(e)[:200]
        finally:
            m.build_search_url = real_url
        if saved < raw_n and last.get("code") == 200 and not err:
            saved += 1
            os.makedirs("raw", exist_ok=True)
            with open(os.path.join("raw", f"page{saved}.html"), "w", encoding="utf-8") as f:
                f.write(last["text"])
        corpus.append({"watch": name, "query_index": qi, "query": q, "error": err,
                       "page_ok": bool(getattr(items, "page_ok", False)),
                       "items": [{k: it.get(k) for k in FIELDS} for it in items]})
        print(f"[{n}/{len(jobs)}] {len(items):3d} items  {name[:38]:38s} q{qi}: {q[:70]}"
              + (f"  ERROR {err}" if err else ""), flush=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"built_at_unix": int(time.time()), "egress": country, "corpus": corpus}, f,
                  ensure_ascii=False)
    print(f"done in {time.time() - t0:.0f}s: {len(corpus)} searches -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
