"""
Bucket J — site-targeted primary-source sweep. Hit court records, government press
releases, and Jewish news outlets directly via site: filters.
"""
import asyncio, json, hashlib, sys, pathlib, itertools
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet"); sys.path.insert(0, str(FLEET))
import os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from searchers import build_searchers

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")

SITES = [
    "courtlistener.com",
    "justice.gov",
    "ag.ny.gov", "oag.ca.gov", "myfloridalegal.com", "ag.state.il.us",
    "jta.org", "forward.com", "tabletmag.com",
    "vosizneias.com", "theyeshivaworld.com", "matzav.com",
    "timesofisrael.com", "haaretz.com", "ynetnews.com",
    "failedmessiah.com",
    "jewishcommunitywatch.org",
    "thejewishchronicle.net",
    "thejc.com",
    "archive.org",
]
KEYWORDS = [
    "Chabad rabbi convicted",
    "Lubavitch fraud indictment",
    "Chabad sexual abuse lawsuit",
    "Lubavitch yeshiva arrest",
    "Chabad embezzlement charged",
    "Lubavitch cover-up",
]

def build():
    qs = []
    for site, kw in itertools.product(SITES, KEYWORDS):
        qs.append(f"{kw} site:{site}")
    return list(dict.fromkeys(qs))

async def main():
    qs = build()
    out = ROOT/"data/raw/searches/bucket_j"; out.mkdir(parents=True, exist_ok=True)
    s = build_searchers()["tavily"]
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem:
            try:
                res = await s.search(q, max_results=8)
                d = res.as_dict() if hasattr(res,"as_dict") else res
            except Exception as e:
                d = {"results":[], "error":str(e)}
            h = hashlib.sha256(q.encode()).hexdigest()[:16]
            payload={"query":q,"engine":"tavily","results":d.get("results",[]) if isinstance(d,dict) else [],"error":d.get("error") if isinstance(d,dict) else None}
            (out/f"{h}.json").write_text(json.dumps(payload,indent=2))
    print(f"firing {len(qs)} site-targeted queries")
    tasks=[one(q) for q in qs]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%25==0: print(f"  {done}/{len(qs)}")
    print("done")

asyncio.run(main())
