#!/usr/bin/env python3
"""Diagnostics: A/B the HTTP client against eBay search from a CI runner.

Sends the same searches, interleaved and on the same IP, through (a) the monitor's
requests session and (b) a curl_cffi session that impersonates Chrome's TLS/HTTP-2
fingerprint, one throttled request at a time, with no retries. Then it reports each
client's first-attempt OK / 403 / soft-block rates and checks that the pages parse
alike. It never alerts and never touches seen.db.

    pip install curl_cffi && AB_N=50 python tools/http_ab.py ab.json   # AB_SPACING=2.0 s

AB_MODE=retry instead compares what to do after a 403, interleaved over N searches with one
session per policy: retry at once ("plain"), re-prime the homepage first ("prime", the
monitor's current behaviour minus its sleeps) or start a fresh primed session ("fresh").
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_monitor as m  # noqa: E402
from curl_cffi import requests as creq  # noqa: E402

DOMAIN = "www.ebay.com"


class _Canned:
    """Feeds one fetched page through the monitor's own parser (fetch_listings)."""
    def __init__(self, text):
        self.status_code, self.text = 200, text

    def get(self, *a, **k):
        return self


def parse(text, query):
    real = m.get_session, m._throttle_request
    m.get_session, m._throttle_request = (lambda d: _Canned(text)), (lambda: None)   # no extra wait
    try:
        return m.fetch_listings(DOMAIN, query, max_attempts=1)
    finally:
        m.get_session, m._throttle_request = real


def _primed(stats):
    s = m._build_session()
    m._throttle_request()
    try:
        stats["prime_" + str(s.get(f"https://{DOMAIN}/", timeout=25).status_code)] += 1
    except Exception as e:
        stats["prime_" + type(e).__name__] += 1
    return s


def retry_experiment(queries, attempts=4):
    """-> per-policy outcomes. Each search makes up to `attempts` tries under one policy."""
    policies = ("plain", "prime", "fresh")
    stats = {p: Counter() for p in policies}
    sessions = {p: _primed(stats[p]) for p in policies}
    rows = []
    for i, q in enumerate(queries):
        pol = policies[i % len(policies)]
        st, codes, t0 = stats[pol], [], time.time()
        url = m.build_search_url(DOMAIN, q)
        for attempt in range(1, attempts + 1):
            m._throttle_request()
            st["requests"] += 1
            try:
                r = sessions[pol].get(url, headers={"Referer": f"https://{DOMAIN}/"}, timeout=25)
                kind = "403" if r.status_code == 403 else ("soft" if m._looks_blocked(r.text) else str(r.status_code))
            except Exception as e:
                kind = type(e).__name__
            codes.append(kind)
            if kind == "200":
                break
            if attempt < attempts:
                st["after_" + kind] += 1
                if pol == "prime":
                    m._throttle_request()
                    st["requests"] += 1
                    try:
                        st["prime_" + str(sessions[pol].get(f"https://{DOMAIN}/", timeout=25).status_code)] += 1
                    except Exception as e:
                        st["prime_" + type(e).__name__] += 1
                elif pol == "fresh":
                    st["requests"] += 1
                    sessions[pol] = _primed(st)
        st["searches"] += 1
        st["ok"] += codes[-1] == "200"
        st["secs"] += time.time() - t0
        for a, b in zip(codes, codes[1:]):
            st[f"retry_{a}_then_{'ok' if b == '200' else b}"] += 1
        rows.append({"query": q, "policy": pol, "codes": codes})
        print(f"[{i + 1}/{len(queries)}] {pol:5s} {' '.join(codes):24s} {q[:48]}", flush=True)
    for pol, st in stats.items():
        n = st["searches"] or 1
        print(f"  {pol:5s} ok {st['ok'] / n:6.1%}  requests/search {st['requests'] / n:4.2f}  "
              f"secs/search {st['secs'] / n:5.1f}  {dict(st)}")
    return {p: dict(v) for p, v in stats.items()}, rows


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "ab.json"
    country = m.egress_country()
    print(f"egress country: {country}")
    if country and country != "US":
        print("non-US egress: eBay would serve a local-buyer page; refusing to run")
        return m.EXIT_REROLL
    m._MIN_REQUEST_INTERVAL = float(os.environ.get("AB_SPACING", "2.0"))
    n = int(os.environ.get("AB_N", "50") or 50)
    raw_n = int(os.environ.get("AB_RAW", "4") or 0)
    cfg = m.load_config()
    queries = [q for w in cfg["watches"] for q in m.watch_queries(w)]
    queries = queries[::max(1, len(queries) // n)][:n]   # spread over every watch
    if os.environ.get("AB_MODE") == "retry":
        t0 = time.time()
        summary, rows = retry_experiment(queries)
        print(f"done in {time.time() - t0:.0f}s")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"built_at_unix": int(time.time()), "egress": country, "mode": "retry",
                       "summary": summary, "rows": rows}, f, ensure_ascii=False)
        return 0

    clients = {"requests": m.get_session(DOMAIN)}        # built + primed like production
    cs = creq.Session(impersonate="chrome")
    m._throttle_request()
    print(f"curl_cffi prime: HTTP {cs.get(f'https://{DOMAIN}/', timeout=25).status_code}")
    clients["curl_cffi"] = cs

    tally = {k: Counter() for k in clients}
    rows, saved, t0 = [], 0, time.time()
    for i, q in enumerate(queries):
        order = list(clients) if i % 2 == 0 else list(reversed(list(clients)))
        row = {"query": q}
        for name in order:
            m._throttle_request()
            items = None
            try:
                r = clients[name].get(m.build_search_url(DOMAIN, q), headers={"Referer": f"https://{DOMAIN}/"},
                                      timeout=25)
                if r.status_code == 403:
                    kind = "403"
                elif m._looks_blocked(r.text):
                    kind = "softblock"
                elif r.status_code == 200:
                    kind = "ok"
                    items = [x["item_id"] for x in parse(r.text, q)]
                    if name == "curl_cffi" and saved < raw_n:
                        saved += 1
                        os.makedirs("raw", exist_ok=True)
                        with open(os.path.join("raw", f"cffi{saved}.html"), "w", encoding="utf-8") as f:
                            f.write(r.text)
                else:
                    kind = f"http{r.status_code}"
            except Exception as e:   # keep going: one failure must not end the experiment
                kind = f"error:{type(e).__name__}"
            tally[name][kind] += 1
            row[name] = {"kind": kind, "items": items}
            print(f"[{i + 1}/{len(queries)}] {name:9s} {kind:9s} {len(items) if items is not None else '-':>3}  {q[:50]}",
                  flush=True)
        rows.append(row)

    both_ok = [r for r in rows if r["requests"]["items"] is not None and r["curl_cffi"]["items"] is not None]
    same = sum(1 for r in both_ok if r["requests"]["items"] == r["curl_cffi"]["items"])
    summary = {k: dict(v) for k, v in tally.items()}
    print(f"done in {time.time() - t0:.0f}s over {len(queries)} searches per client")
    for k, v in tally.items():
        tot = sum(v.values()) or 1
        print(f"  {k:9s} ok {v['ok'] / tot:6.1%}  403 {v['403'] / tot:6.1%}  soft {v['softblock'] / tot:6.1%}  {dict(v)}")
    print(f"  pages both clients fetched: {len(both_ok)}, identical item lists: {same} "
          "(new listings between the two requests can differ)")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"built_at_unix": int(time.time()), "egress": country, "summary": summary,
                   "rows": rows}, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
