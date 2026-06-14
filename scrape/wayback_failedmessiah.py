"""
Wayback Machine sweep of FailedMessiah.
1. Query CDX API for all archived snapshots of failedmessiah.typepad.com/*
2. Dedupe URLs (one snapshot per unique post URL).
3. For each post URL with 'chabad' or 'lubavitch' in path/snippet, fetch the wayback rendering and save.
4. Produce a search-result-style JSON so triage_v2 picks it up.
"""
import asyncio, json, hashlib, pathlib, httpx, re
from urllib.parse import quote_plus
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT = ROOT/"data/raw/searches/bucket_n_failedmessiah"; OUT.mkdir(parents=True, exist_ok=True)

CDX = "https://web.archive.org/cdx/search/cdx"

async def cdx_list():
    """Return list of (timestamp, original_url) for all archived FM posts, sharded by year."""
    all_rows = []
    async with httpx.AsyncClient(timeout=180) as c:
        for year in range(2004, 2017):
            params = {
                "url": "failedmessiah.typepad.com/*",
                "output": "json",
                "filter": "mimetype:text/html",
                "collapse": "urlkey",
                "fl": "timestamp,original",
                "from": f"{year}0101",
                "to":   f"{year}1231",
            }
            try:
                r = await c.get(CDX, params=params, timeout=180)
                r.raise_for_status()
                data = r.json()
                rows = data[1:] if data and data[0] == ["timestamp","original"] else data
                print(f"  {year}: {len(rows)} URLs")
                all_rows.extend(rows)
            except Exception as e:
                print(f"  {year}: failed ({type(e).__name__})")
    # dedupe by URL
    seen=set(); deduped=[]
    for ts, orig in all_rows:
        k = orig.split("?")[0].lower()
        if k in seen: continue
        seen.add(k); deduped.append((ts, orig))
    print(f"CDX total (deduped): {len(deduped)} URLs")
    return deduped

CHABAD_RE = re.compile(r"chabad|lubavitch|crown[_-]?heights|770", re.I)

def is_post_url(u):
    # Real post URLs look like .../failed_messiahcom/2008/05/aaron-rubashkin.html
    return ".html" in u and "/failed_messiahcom/" in u and "/page/" not in u

def is_chabad_relevant(u):
    return bool(CHABAD_RE.search(u))

async def main():
    rows = await cdx_list()
    # Filter: real post URLs, chabad-relevant by URL slug
    candidates = []
    seen = set()
    for ts, orig in rows:
        if not is_post_url(orig): continue
        # normalize
        key = orig.split("?")[0].lower()
        if key in seen: continue
        seen.add(key)
        if is_chabad_relevant(orig):
            wayback_url = f"https://web.archive.org/web/{ts}/{orig}"
            candidates.append({
                "url": wayback_url,
                "title": "FailedMessiah archived post",
                "snippet": orig.rsplit("/",1)[-1].replace(".html","").replace("_"," ").replace("-"," "),
            })
    print(f"chabad-slug filtered: {len(candidates)}")

    # If we got <50 by slug, broaden — pull all post URLs (the slug filter may miss chabad-related posts under generic slugs)
    if len(candidates) < 200:
        print("broadening: including all FM posts (chabad context inferred at triage)")
        candidates = []
        seen = set()
        for ts, orig in rows:
            if not is_post_url(orig): continue
            key = orig.split("?")[0].lower()
            if key in seen: continue
            seen.add(key)
            wayback_url = f"https://web.archive.org/web/{ts}/{orig}"
            candidates.append({
                "url": wayback_url,
                "title": "FailedMessiah archived post",
                "snippet": orig.rsplit("/",1)[-1].replace(".html","").replace("_"," ").replace("-"," "),
            })

    # cap to avoid blowing budget
    if len(candidates) > 3000:
        candidates = candidates[:3000]
        print(f"capped to {len(candidates)}")

    payload = {"query":"failedmessiah_wayback_crawl","engine":"wayback","results":candidates}
    (OUT/"index.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {len(candidates)} URLs to {OUT/'index.json'}")

asyncio.run(main())
