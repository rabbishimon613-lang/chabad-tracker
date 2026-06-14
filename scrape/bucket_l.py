"""
Bucket L — second news-mode wave. Named-perp focus + new keyword angles.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, sqlite3
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

# Pull named perps already in corpus — search for more cases tied to each
conn = sqlite3.connect(ROOT/"data/chabad.db")
perps = [r[0] for r in conn.execute("""
  SELECT DISTINCT p.full_name FROM incident_people ip
  JOIN people p ON p.id=ip.person_id
  JOIN incidents i ON i.id=ip.incident_id
  WHERE ip.role='perpetrator' AND p.full_name NOT LIKE 'Unnamed%' AND p.full_name NOT LIKE 'Unknown%'
    AND p.full_name NOT LIKE 'unknown%' AND length(p.full_name) > 6 AND p.full_name NOT LIKE '%,%'
""")]
conn.close()

NAMED_PERP_QUERIES = []
for name in perps[:60]:
    # strip "Rabbi", "Mrs.", honorifics for cleaner queries
    base = name.replace("Rabbi ","").replace("Mrs. ","").replace("Mr. ","").strip()
    NAMED_PERP_QUERIES.append(f"\"{base}\" Chabad lawsuit")
    NAMED_PERP_QUERIES.append(f"\"{base}\" arrested OR convicted")

NEW_ANGLES = [
    # Specific yeshivas / camps not previously hit hard
    "Camp Gan Israel abuse lawsuit",
    "Camp Emunah Lubavitch abuse",
    "Beth Rivkah school abuse",
    "Oholei Torah abuse claims",
    "Hadar Hatorah Crown Heights scandal",
    "Machne Israel Chabad fraud",
    "Merkos L'Inyonei Chinuch lawsuit",
    "Aleph Institute Chabad scandal",
    "Friendship Circle Chabad lawsuit",
    # Russian / FSU chabad
    "Berel Lazar Russia rabbi corruption",
    "FJC Russia Chabad investigation",
    "Kazakhstan Chabad rabbi",
    "Ukraine Chabad rabbi arrested",
    "Kiev Chabad fraud",
    # Israeli / Hebrew context
    "Chabad rabbi Israel indictment",
    "Kfar Chabad violence arrest",
    "Chabad school Israel abuse",
    "Mosdot Chinuch Chabad lawsuit Israel",
    # Family network angles
    "Krinsky family Chabad scandal",
    "Lazar family Chabad controversy",
    "Cunin family Chabad lawsuit",
    "Shemtov rabbi controversy",
    "Telsner Melbourne abuse",
    # Civil rights / discrimination
    "Chabad discrimination lawsuit",
    "Chabad religious exemption fraud",
    "Lubavitch zoning lawsuit",
    # Wire / mortgage / PPP
    "Chabad mortgage fraud",
    "Chabad PPP loan fraud rabbi",
    "Lubavitch wire fraud charges",
    # 2020s recent
    "Lubavitch rabbi sentenced 2024",
    "Chabad rabbi pleads guilty 2024",
    "Chabad rabbi pleads guilty 2025",
    "Hasidic rabbi sentenced 2024",
    # Drug / narcotics
    "Chabad rabbi drug charges",
    "Lubavitch ecstasy rabbi",
    # International press
    "Chabad rabbi Argentina arrested",
    "Chabad rabbi Brazil arrested",
    "Chabad rabbi Mexico investigation",
    "Chabad rabbi Thailand drug",
    "Chabad rabbi South Africa fraud",
]

QUERIES = list(dict.fromkeys(NAMED_PERP_QUERIES + NEW_ANGLES))
print(f"prepared {len(QUERIES)} queries ({len(NAMED_PERP_QUERIES)} named-perp + {len(NEW_ANGLES)} angles)")

async def fire(query, key, out):
    h = hashlib.sha256(query.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": query, "topic": "news",
                "max_results": 10, "days": 3650, "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":query,"engine":"tavily-news","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":query,"engine":"tavily-news","results":[],"error":str(e)}, indent=2))

async def main():
    out = ROOT/"data/raw/searches/bucket_l"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%25==0: print(f"  {done}/{len(QUERIES)}")
    print("done")

asyncio.run(main())
