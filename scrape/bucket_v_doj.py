"""
Bucket V — DOJ/FBI press releases. Court-verified, highest confidence.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, itertools
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

QUERIES = [
    # DOJ USAO press releases
    'site:justice.gov "Chabad" rabbi fraud',
    'site:justice.gov "Chabad" rabbi convicted',
    'site:justice.gov "Chabad" rabbi indicted',
    'site:justice.gov "Chabad" rabbi sentenced',
    'site:justice.gov "Chabad" rabbi pleaded guilty',
    'site:justice.gov rabbi "Lubavitch" fraud',
    'site:justice.gov rabbi "Lubavitch" convicted',
    'site:justice.gov "Agriprocessors" indicted',
    'site:justice.gov "Agriprocessors" fraud convicted',
    'site:justice.gov rabbi "money laundering" Chabad',
    'site:justice.gov rabbi "wire fraud" Chabad',
    'site:justice.gov rabbi "tax evasion" Chabad',
    'site:justice.gov rabbi "sexual abuse" convicted',
    'site:justice.gov rabbi "child pornography" convicted',
    'site:justice.gov rabbi "securities fraud"',
    'site:justice.gov rabbi "Ponzi scheme"',
    'site:justice.gov rabbi "immigration fraud"',
    'site:justice.gov rabbi "bank fraud" sentenced',
    # FBI field offices
    'site:fbi.gov rabbi Chabad arrested',
    'site:fbi.gov rabbi fraud indicted',
    # Specific known names — get full court docs
    'site:justice.gov "Sholom Rubashkin"',
    'site:justice.gov "Yisroel Goldstein" rabbi',
    'site:justice.gov "Baruch Lebovits"',
    'site:justice.gov "Nechemya Weberman"',
    'site:justice.gov "Eliyahu Weinstein" rabbi',
    'site:justice.gov "Jacob Harari" rabbi',
    'site:justice.gov "Mendel Epstein" rabbi',
    'site:justice.gov "Abraham Rubin" rabbi',
    'site:justice.gov "Moshe Zigelman"',
    'site:justice.gov "Spinka" rabbi',
    # USAO districts with large Jewish/Chabad populations
    'site:justice.gov/usao-sdny rabbi fraud',
    'site:justice.gov/usao-edny rabbi fraud',
    'site:justice.gov/usao-nj rabbi fraud',
    'site:justice.gov/usao-edpa rabbi',
    'site:justice.gov/usao-sdca rabbi Chabad',
    'site:justice.gov/usao-cdca rabbi Chabad',
    'site:justice.gov/usao-dma rabbi fraud',
    'site:justice.gov/usao-ndil rabbi',
    'site:justice.gov/usao-ndfl rabbi',
    'site:justice.gov/usao-sdfl rabbi',
]
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
    out = ROOT/"data/raw/searches/bucket_v_doj"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%10==0: print(f"  {done}/{len(QUERIES)}")
    print("V done")

asyncio.run(main())
