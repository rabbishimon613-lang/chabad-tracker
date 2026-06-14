"""
Bucket T — Royal Commission and government inquiry sources.
The Australian Royal Commission into Institutional Responses to Child Sexual Abuse
had specific Chabad Yeshivah Centre Melbourne testimony. Other countries too.
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
    # Royal Commission Australia
    "Royal Commission Yeshivah Centre testimony",
    "Royal Commission Chabad Melbourne findings",
    "Royal Commission Yeshivah Sydney testimony",
    "Manny Waks Royal Commission",
    "case study Yeshivah Centre Royal Commission",
    "AVL Yeshivah Centre testimony",
    # UK Hasidic abuse inquiries
    "UK IICSA Chabad",
    "Norwood Chabad abuse UK inquiry",
    "Stamford Hill Chabad investigation",
    # US Congressional / state investigations
    "Iowa Agriprocessors investigation Senate",
    "New York Catholic Conference Chabad",  # state legislative reports often group cases
    # Israeli state comptroller / press
    "מבקר המדינה חב\"ד",  # State Comptroller Chabad
    "ועדת חקירה חב\"ד",  # Inquiry committee Chabad
    "פרשת חב\"ד",  # Chabad affair (Hebrew investigative articles)
    # NSOPW + state sex offender names cross-check (search by surname patterns we have)
    "site:nsopw.gov Chabad rabbi",
    "site:meganslaw.ca.gov rabbi Chabad",
    "site:dps.state.tx.us rabbi Chabad",
    "site:criminaljustice.ny.gov rabbi Chabad",
    "site:dpsweb.state.nj.us rabbi Chabad",
    "site:fdle.state.fl.us rabbi Chabad",
    # Charity / nonprofit watchdogs
    "ProPublica Chabad nonprofit",
    "site:projects.propublica.org Chabad",
    "site:charitynavigator.org Chabad fraud",
    # OFAC / sanctions
    "site:treasury.gov Chabad sanctions",
    "site:state.gov Chabad rabbi",
    # SEC / wire fraud
    "site:sec.gov Chabad rabbi",
    # Specialized blogs / forums
    "site:vosizneias.com Chabad arrest",
    "site:vinnews.com Chabad rabbi",
    "site:yeshivanews.com Chabad rabbi",
    "site:thedailywire.com Chabad rabbi",
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
        fp.write_text(json.dumps({"query":q,"engine":"tavily","results":[],"error":str(e)}, indent=2))

async def main():
    out = ROOT/"data/raw/searches/bucket_t_royal"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%15==0: print(f"  {done}/{len(QUERIES)}")
    print("T done")

asyncio.run(main())
