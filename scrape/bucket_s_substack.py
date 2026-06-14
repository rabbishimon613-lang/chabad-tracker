"""
Bucket S — Substack/Medium accountability newsletters + survivor-org sites.
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
    "substack.com",
    "medium.com",
    "snapnetwork.org",
    "zaakah.org",
    "sacredspaces.org",
    "survivorsforjustice.org",
    "thelilithfoundation.org",
    "jewishjournal.com",
    "thejewishstandard.com",
    "tabletmag.com",
    "thejewishchronicle.net",
    "thejc.com",
    "algemeiner.com",
    "jpost.com",
    "ynetnews.com",
]
TERMS = [
    "Chabad rabbi abuse",
    "Lubavitch coverup",
    "Chabad survivor story",
    "Hasidic abuse Chabad",
    "Lubavitch financial scandal",
    "Chabad rabbi pleaded guilty",
    "Chabad mosdos lawsuit",
    "credibly accused Chabad rabbi",
]

QUERIES = [f"{t} site:{s}" for s, t in itertools.product(SITES, TERMS)]
print(f"prepared {len(QUERIES)} queries")

async def fire(q, key, out):
    h = hashlib.sha256(q.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": q, "max_results": 6, "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":q,"engine":"tavily","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":q,"engine":"tavily","results":[],"error":str(e)}, indent=2))

async def main():
    out = ROOT/"data/raw/searches/bucket_s_substack"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%30==0: print(f"  {done}/{len(QUERIES)}")
    print("S done")

asyncio.run(main())
