"""
Bucket R — Crown Heights community press + JCW news section.
These are the insider Chabad outlets that break stories before mainstream picks up.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, itertools
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

SITES = [
    "crownheights.info",
    "collive.com",
    "theyeshivaworld.com",
    "vinnews.com",
    "matzav.com",
    "jewishcommunitywatch.org",   # news section, not just wall-of-shame
    "lubavitch.com",              # official, sometimes mentions controversies
    "thelubavitcher.com",
    "shminoogle.com",
    "ynetnews.com",
    "kikar.co.il",
    "actualic.com",
]
TERMS = [
    "rabbi arrested", "rabbi indicted", "rabbi convicted",
    "rabbi pleads guilty", "rabbi sentenced", "rabbi charged with",
    "child abuse rabbi", "sexual abuse Chabad",
    "fraud Chabad rabbi", "embezzlement Chabad",
    "shliach arrested", "shluchim scandal",
    "mosdos lawsuit", "yeshiva abuse Chabad",
    "Crown Heights arrest rabbi", "Crown Heights scandal",
]

QUERIES = [f"{t} site:{s}" for s, t in itertools.product(SITES, TERMS)]
print(f"prepared {len(QUERIES)} site-targeted queries")

async def fire(q, key, out):
    h = hashlib.sha256(q.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": q, "max_results": 8, "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":q,"engine":"tavily","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":q,"engine":"tavily","results":[],"error":str(e)}, indent=2))

async def main():
    out = ROOT/"data/raw/searches/bucket_r_chs"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%30==0: print(f"  {done}/{len(QUERIES)}")
    print("R done")

asyncio.run(main())
