"""
Bucket H — fleet-generated queries + FailedMessiah blog archive crawl.
"""
import asyncio, json, hashlib, sys, pathlib, re
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet"); sys.path.insert(0, str(FLEET))
import os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from searchers import build_searchers

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")


async def fire_h1():
    qs = json.load(open(ROOT/"data/raw/fleet_queries.json"))
    out = ROOT/"data/raw/searches/bucket_h1"; out.mkdir(parents=True, exist_ok=True)
    s = build_searchers()["tavily"]
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem:
            try:
                res = await s.search(q, max_results=10)
                d = res.as_dict() if hasattr(res,"as_dict") else res
            except Exception as e:
                d = {"results":[], "error":str(e)}
            h = hashlib.sha256(q.encode()).hexdigest()[:16]
            payload={"query":q,"engine":"tavily","results":d.get("results",[]) if isinstance(d,dict) else [],"error":d.get("error") if isinstance(d,dict) else None}
            (out/f"{h}.json").write_text(json.dumps(payload,indent=2))
    done=0
    tasks=[one(q) for q in qs]
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%25==0: print(f"  [h1] {done}/{len(qs)}")
    print(f"H1 done. {len(qs)} queries fired")


async def fire_h2_failedmessiah():
    """Scrape failedmessiah.com archives for Chabad-tagged posts."""
    out_idx = ROOT/"data/raw/searches/bucket_h2_failedmessiah"
    out_idx.mkdir(parents=True, exist_ok=True)
    SEEDS = [
        "https://failedmessiah.typepad.com/failed_messiahcom/chabad/",
        "https://failedmessiah.typepad.com/failed_messiahcom/lubavitch/",
        "https://failedmessiah.typepad.com/failed_messiahcom/haredim_crime/",
        "https://failedmessiah.typepad.com/failed_messiahcom/haredim_and_sexual_abuse/",
    ]
    async with AsyncSession() as s:
        all_posts = set()
        for seed in SEEDS:
            for page in range(1, 11):
                u = seed if page == 1 else seed.rstrip("/") + f"/page/{page}/"
                try:
                    r = await s.get(u, impersonate="chrome", timeout=25)
                except Exception:
                    continue
                if r.status_code != 200: continue
                soup = BeautifulSoup(r.text, "html.parser")
                # entry permalinks
                for a in soup.find_all("a", href=True):
                    h = a["href"]
                    if "failedmessiah" in h and (".html" in h or "/2" in h):
                        all_posts.add(h.split("#")[0])
                if "Next" not in r.text and "next" not in r.text.lower():
                    break
        print(f"FailedMessiah: {len(all_posts)} candidate post URLs")
        # Save as a single "results" file so triage picks them up
        payload = {
            "query": "failedmessiah_archive_crawl",
            "engine": "scrape",
            "results": [{"url": u, "title": "failedmessiah post", "snippet": ""} for u in sorted(all_posts)],
        }
        (out_idx/"index.json").write_text(json.dumps(payload, indent=2))


async def main():
    await fire_h1()
    await fire_h2_failedmessiah()

if __name__ == "__main__":
    asyncio.run(main())
