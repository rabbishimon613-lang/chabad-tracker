"""
Bucket Z — Civil courts, insurance fraud, welfare fraud, bankruptcy,
elder abuse, immigration violations, rabbinical bans, and case-type gaps.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

QUERIES = [
    # Civil lawsuits
    "Chabad rabbi lawsuit civil settlement abuse",
    "Chabad rabbi sued civil court sexual abuse",
    "Chabad organization lawsuit negligence abuse",
    "Lubavitch lawsuit settlement molest",
    "Chabad rabbi civil judgment",
    "Yeshivah Centre Melbourne civil lawsuit",
    "Chabad house sued negligence",
    # Insurance fraud
    "Chabad rabbi insurance fraud convicted",
    "rabbi Chabad arson insurance fraud",
    "rabbi Lubavitch insurance scheme",
    "Orthodox rabbi insurance fraud arrested",
    "Chabad community insurance fraud New Jersey",
    "rabbi insurance fraud Brooklyn convicted",
    # Welfare / benefits fraud
    "Chabad rabbi welfare fraud arrested",
    "rabbi Chabad medicaid fraud convicted",
    "rabbi Chabad food stamps fraud",
    "Orthodox rabbi benefits fraud Brooklyn",
    "Chabad community welfare fraud scheme",
    "rabbi Lubavitch public assistance fraud",
    # Immigration violations
    "Agriprocessors immigration violations workers",
    "Chabad rabbi visa fraud",
    "rabbi Lubavitch immigration fraud",
    "Chabad organization illegal workers",
    # Bankruptcy / financial misconduct
    "Agriprocessors bankruptcy fraud creditors",
    "Chabad nonprofit bankruptcy fraud",
    "rabbi Chabad bankruptcy fraud",
    # Elder financial abuse
    "rabbi Chabad elder financial abuse",
    "rabbi Lubavitch elderly fraud",
    "Chabad rabbi estate theft elderly",
    # Domestic violence / get refusal
    "rabbi Chabad get refusal coercion convicted",
    "rabbi Lubavitch domestic violence arrested",
    "ORA rabbis convicted get refusal",
    "rabbi forced divorce coercion arrested",
    # Weapons
    "rabbi Chabad weapons charge arrested",
    "rabbi Lubavitch illegal firearms",
    # Drugs
    "rabbi Chabad drug trafficking arrested",
    "rabbi Lubavitch narcotics convicted",
    # Money laundering
    "Chabad rabbi money laundering convicted",
    "Lubavitch money laundering network",
    "rabbi Chabad hawala money laundering",
    # Child labour / exploitation
    "Agriprocessors child labour violations",
    "Chabad yeshiva child labour violations",
    # Specific civil cases from CourtListener
    'site:courtlistener.com Chabad rabbi',
    'site:courtlistener.com "Lubavitch" fraud',
    'site:law.justia.com Chabad rabbi fraud convicted',
    'site:law.justia.com "Lubavitch" rabbi abuse',
    'site:casetext.com Chabad rabbi convicted',
    # FINRA / SEC
    'site:finra.org Chabad rabbi',
    'site:sec.gov/litigation "Chabad" rabbi',
    'site:sec.gov/litigation rabbi fraud sentenced',
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
    out = ROOT/"data/raw/searches/bucket_z_civil"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%15==0: print(f"  {done}/{len(QUERIES)}")
    print("Z done")

asyncio.run(main())
