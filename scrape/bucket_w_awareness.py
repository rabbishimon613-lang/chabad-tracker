"""
Bucket W — The Awareness Center + JTA wire + Forward investigative.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, itertools
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

# Awareness Center case files
AWARENESS_QUERIES = [
    'site:theawarenesscenter.org Chabad rabbi',
    'site:theawarenesscenter.org Lubavitch',
    'site:theawarenesscenter.org "Chabad" case file',
    'site:theawarenesscenter.org rabbi convicted sexual abuse',
    'site:theawarenesscenter.org rabbi arrested molest',
]

# JTA wire
JTA_TERMS = [
    "Chabad rabbi arrested", "Chabad rabbi convicted", "Chabad rabbi fraud",
    "Lubavitch rabbi charged", "Chabad sexual abuse rabbi", "Chabad indicted",
    "Chabad rabbi pleaded guilty", "Chabad rabbi sentenced",
]
JTA_QUERIES = [f"site:jta.org {t}" for t in JTA_TERMS]

# The Forward investigative
FORWARD_TERMS = [
    "Chabad rabbi abuse", "Chabad fraud convicted", "Lubavitch scandal",
    "Chabad rabbi arrested", "Chabad cover-up", "Agriprocessors Chabad",
    "Chabad rabbi sex abuse", "Chabad money laundering",
]
FORWARD_QUERIES = [f"site:forward.com {t}" for t in FORWARD_TERMS]

# Jewish Week / New York Jewish Week
JWEEK_QUERIES = [
    'site:jewishweek.timesofisrael.com Chabad rabbi arrested',
    'site:jewishweek.timesofisrael.com Chabad rabbi convicted',
    'site:jewishweek.timesofisrael.com Chabad fraud',
    'site:jewishweek.timesofisrael.com Chabad abuse',
    'site:thejewishweek.com Chabad rabbi arrested',
    'site:thejewishweek.com Chabad fraud',
]

# Tablet Magazine
TABLET_QUERIES = [
    'site:tabletmag.com Chabad rabbi arrested',
    'site:tabletmag.com Chabad abuse scandal',
    'site:tabletmag.com Lubavitch fraud',
    'site:tabletmag.com Chabad convicted',
]

QUERIES = AWARENESS_QUERIES + JTA_QUERIES + FORWARD_QUERIES + JWEEK_QUERIES + TABLET_QUERIES
print(f"prepared {len(QUERIES)} queries")

async def fire(q, key, out):
    h = hashlib.sha256(q.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": q, "max_results": 10, "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":q,"engine":"tavily","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":q,"engine":"tavily","results":[],"error":str(e)}))

async def main():
    out = ROOT/"data/raw/searches/bucket_w_awareness"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%10==0: print(f"  {done}/{len(QUERIES)}")
    print("W done")

asyncio.run(main())
