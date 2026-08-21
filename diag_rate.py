"""Temporary: find a SAFE faster scan rate. Sustains a steady request rate from
the runner for ~8 min and reports whether eBay keeps serving REAL results over
time (by time-thirds). If the last third degrades, the block triggered at this
rate -> too aggressive. Known reference: ~8 req/min works, ~38 req/min blocked.
"""
import itertools
import json
import time

import ebay_monitor as m

DOMAIN = "www.ebay.com"
TARGET_INTERVAL = 2.2   # ~27 requests/min
DURATION = 480          # 8 minutes

cfg = json.load(open("config.json", encoding="utf-8"))
queries = []
for w in cfg["watches"]:
    for q in (w.get("queries") or [])[:2]:
        queries.append(q)
print(f"{len(queries)} queries in rotation; target ~{60/TARGET_INTERVAL:.0f} req/min for {DURATION//60} min")

start = time.time()
cyc = itertools.cycle(queries)
log = []  # (elapsed, real_bool)
while time.time() - start < DURATION:
    t0 = time.time()
    q = next(cyc)
    try:
        items = m.fetch_listings(DOMAIN, q)
    except Exception:
        items = []
    tok = q.split()[0].lower()
    rel = sum(1 for x in items if tok in (x.get("title") or "").lower())
    log.append((time.time() - start, rel >= 3))
    time.sleep(max(0.0, TARGET_INTERVAL - (time.time() - t0)))

elapsed = log[-1][0] if log else 1
print(f"made {len(log)} requests over {elapsed:.0f}s = {len(log)/(elapsed/60):.1f} req/min")
for name, lo, hi in [("first", 0, DURATION/3), ("mid", DURATION/3, 2*DURATION/3), ("last", 2*DURATION/3, DURATION+1)]:
    seg = [ok for (el, ok) in log if lo <= el < hi]
    if seg:
        print(f"{name:>5} third: {sum(seg)}/{len(seg)} real ({100*sum(seg)/len(seg):.0f}%)")
print("VERDICT: all thirds ~100% -> this rate held (safe). last third drops -> block triggered (too fast).")
