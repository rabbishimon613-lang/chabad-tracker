"""
Chart H — CourtListener REST v4 Sweep
--------------------------------------
RECAP federal court dockets + opinions mentioning Chabad / Lubavitch /
named perps. Free, no creds needed for read-only search.

Upgraded from v3 (deprecated) to v4. Expanded from top-50 perps to ALL
named perps in the DB. Captures docket IDs so a follow-up pass can
fetch RECAP document content for high-confidence hits.

Output: data/raw/searches/bucket_o_courtlistener/<hash>.json
Each file: {query, engine, results: [{title, url, snippet, docket_id, court}]}

Usage:
  python3 scrape/courtlistener_sweep.py                 # full sweep
  python3 scrape/courtlistener_sweep.py --limit 20      # smoke test
"""
import asyncio, json, hashlib, pathlib, sqlite3, argparse
from curl_cffi import requests as crequests

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT  = ROOT / "data/raw/searches/bucket_o_courtlistener"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://www.courtlistener.com/api/rest/v4/search/"

INSTITUTIONS = [
    "Chabad", "Lubavitch", "Agudas Chassidei Chabad",
    "Merkos L'Inyonei Chinuch", "Machne Israel",
    "Agriprocessors", "Aleph Institute",
    "Oholei Torah", "Beth Rivkah", "Hadar Hatorah",
    "Friendship Circle", "Chabad House",
]

def load_perps() -> list[str]:
    con = sqlite3.connect(ROOT / "data/chabad.db")
    perps = [r[0] for r in con.execute("""
      SELECT DISTINCT p.full_name FROM incident_people ip
      JOIN people p ON p.id=ip.person_id
      WHERE ip.role='perpetrator'
        AND p.full_name NOT LIKE 'Unnamed%'
        AND p.full_name NOT LIKE 'Unknown%'
        AND p.full_name NOT LIKE 'unknown%'
        AND length(p.full_name) > 8
        AND p.full_name NOT LIKE '%,%'
    """)]
    con.close()
    return perps

def clean_name(p: str) -> str:
    return (p.replace("Rabbi ","")
             .replace("Mrs. ","")
             .replace("Mr. ","")
             .replace("Dr. ","")
             .strip())

def _sync_search(qtype: str, q: str) -> dict:
    """v4 search call. qtype: 'r' (RECAP dockets) or 'o' (opinions).
    Pins to v4 (no redirect-follow); retries on 429 with backoff."""
    params = {"q": f'"{q}"', "type": qtype, "format": "json"}
    import time as _t
    for attempt in range(4):
        try:
            r = crequests.get(BASE, params=params, timeout=60,
                              impersonate="chrome", allow_redirects=False)
            if r.status_code == 429:
                _t.sleep(2 ** attempt * 2)  # 2, 4, 8, 16s
                continue
            if r.status_code in (301, 302, 303, 307, 308):
                # CL redirected v4 → v3 for this query pattern; v3 is gated.
                return {"error": "redirect_to_v3", "results": []}
            if r.status_code != 200:
                return {"error": f"http_{r.status_code}"}
            return r.json()
        except Exception as e:
            if attempt == 3:
                return {"error": str(e)}
            _t.sleep(2)
    return {"error": "rate_limited_after_retries"}

async def search(qtype: str, q: str):
    h = hashlib.sha256(f"v4|{qtype}|{q}".encode()).hexdigest()[:16]
    fp = OUT / f"{h}.json"
    if fp.exists():
        return "cached"
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _sync_search, qtype, q)
    if "error" in data:
        fp.write_text(json.dumps({
            "query": f"[{qtype}] {q}", "engine": "courtlistener_v4",
            "results": [], "error": data["error"]
        }, indent=2))
        return "err"
    results = []
    for item in data.get("results", [])[:20]:
        url = item.get("absolute_url")
        if url and not url.startswith("http"):
            url = "https://www.courtlistener.com" + url
        results.append({
            "title": (item.get("caseName") or item.get("case_name")
                      or item.get("citeName") or item.get("description") or "(no title)"),
            "url": url,
            "snippet": (item.get("snippet")
                        or (item.get("text") or "")[:300]),
            "docket_id":   item.get("docket_id") or item.get("docketId"),
            "court":       item.get("court") or item.get("court_id"),
            "date_filed":  item.get("dateFiled") or item.get("date_filed"),
            "nature_of_suit": item.get("suitNature") or item.get("nature_of_suit"),
        })
    fp.write_text(json.dumps({
        "query": f"[{qtype}] {q}",
        "engine": "courtlistener_v4",
        "result_count_total": data.get("count", 0),
        "results": results,
    }, indent=2))
    return f"ok_{len(results)}"

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Cap perp count (smoke test)")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    perps = load_perps()
    if args.limit:
        perps = perps[:args.limit]
    print(f"[chart-h] perps to query: {len(perps)} + {len(INSTITUTIONS)} institutions")

    queries: list[tuple[str,str]] = []
    for p in perps:
        base = clean_name(p)
        if len(base) < 6:
            continue
        queries.append(("o", base))   # opinions
        queries.append(("r", base))   # RECAP dockets
    for inst in INSTITUTIONS:
        queries.append(("r", inst))
        queries.append(("o", inst))
    print(f"[chart-h] total queries: {len(queries)}")

    sem = asyncio.Semaphore(args.concurrency)
    async def one(qt, q):
        async with sem:
            return await search(qt, q)

    counts = {"cached": 0, "err": 0, "ok": 0, "hits": 0}
    tasks = [one(qt, q) for qt, q in queries]
    done = 0
    for c in asyncio.as_completed(tasks):
        r = await c
        done += 1
        if r == "cached":
            counts["cached"] += 1
        elif r == "err":
            counts["err"] += 1
        elif r.startswith("ok_"):
            counts["ok"] += 1
            counts["hits"] += int(r.split("_")[1])
        if done % 50 == 0:
            print(f"  {done}/{len(queries)}  ok={counts['ok']} cached={counts['cached']} err={counts['err']} hits={counts['hits']}")

    print(f"[chart-h] done. ok={counts['ok']} cached={counts['cached']} err={counts['err']} total_hits={counts['hits']}")
    print(f"[chart-h] output dir: {OUT}")

if __name__ == "__main__":
    asyncio.run(main())
