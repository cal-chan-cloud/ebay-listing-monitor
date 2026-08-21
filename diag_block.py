"""Temporary diagnostic: is eBay blocking the GitHub Actions IP *range*, or only
throttling us for scanning too often? Makes a few WELL-SPACED single requests
(20s apart, no concurrency) from the runner. A rate/volume block would NOT trip
at this gentle pace; a GitHub-IP-range block fails even these.

Verdict per request: REAL = results actually contain the query term (not blocked);
BLOCKED/GENERIC = 0 results or a generic page that matched nothing.
"""
import time
import ebay_monitor as m

DOMAIN = "www.ebay.com"
QUERIES = [
    "oshawott 105/086 white flare",
    "giratina 10/127 platinum holo",
    "lugia neo genesis holo rare",
    "charizard 100/97 ex dragon",
    "squirtle 132/165 expedition",
]

ok = 0
for i, q in enumerate(QUERIES):
    if i:
        time.sleep(20)  # gentle, spaced -> a rate-based block would not trigger here
    try:
        items = m.fetch_listings(DOMAIN, q)
    except Exception as e:
        print(f"[{i+1}] {q!r} ERROR {e!r} -> BLOCKED")
        continue
    tok = q.split()[0].lower()
    rel = sum(1 for it in items if tok in (it.get("title") or "").lower())
    verdict = "REAL" if rel >= 3 else "BLOCKED/GENERIC"
    if rel >= 3:
        ok += 1
    print(f"[{i+1}] {q!r} parsed={len(items)} relevant={rel} -> {verdict}")
    for it in items[:2]:
        print("      sample:", (it.get("title") or "")[:72])

print(f"\nSUMMARY: {ok}/{len(QUERIES)} gentle low-rate requests returned REAL results.")
print("Most REAL  -> block is RATE/VOLUME based (scan less often / fewer requests).")
print("Most BLOCK -> eBay is blocking GitHub's IP range (needs proxy / API / local).")
