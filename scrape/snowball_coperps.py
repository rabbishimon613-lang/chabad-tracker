"""
Snowball — query news for every person who's connected to a known perp by family
relation or house co-residence but doesn't yet have their own incident.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, sqlite3
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

conn = sqlite3.connect(ROOT/"data/chabad.db")
# 2nd-degree: family-related OR co-resident at a house with a known perp, but person has NO incident_people row
neighbors = [r[0] for r in conn.execute("""
WITH perps AS (
  SELECT DISTINCT person_id AS pid FROM incident_people WHERE role='perpetrator'
),
fam AS (
  SELECT CASE WHEN fr.person_a IN (SELECT pid FROM perps) THEN fr.person_b ELSE fr.person_a END AS other
  FROM family_relations fr
  WHERE fr.person_a IN (SELECT pid FROM perps) OR fr.person_b IN (SELECT pid FROM perps)
),
co AS (
  SELECT DISTINCT hr2.person_id AS other
  FROM house_roles hr1
  JOIN house_roles hr2 ON hr2.house_id = hr1.house_id AND hr2.person_id != hr1.person_id
  WHERE hr1.person_id IN (SELECT pid FROM perps)
),
candidates AS (
  SELECT other FROM fam UNION SELECT other FROM co
)
SELECT DISTINCT p.full_name
FROM candidates c JOIN people p ON p.id = c.other
WHERE p.id NOT IN (SELECT person_id FROM incident_people)
  AND p.full_name NOT LIKE 'Mrs.%' -- skip spouses (less likely to be named perps)
  AND length(p.full_name) > 10
LIMIT 200
""")]
conn.close()
print(f"snowball: {len(neighbors)} 2nd-degree candidates")

async def fire(name, key, out):
    base = name.replace("Rabbi ","").replace("Mr. ","").strip()
    q = f'"{base}" Chabad arrested OR convicted OR investigation OR lawsuit'
    h = hashlib.sha256(q.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": q, "topic": "news",
                "max_results": 6, "days": 3650, "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":q,"engine":"tavily-news","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":q,"engine":"tavily-news","results":[],"error":str(e)}, indent=2))

async def main():
    out = ROOT/"data/raw/searches/bucket_p_snowball"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(n):
        async with sem: await fire(n, random.choice(KEYS), out)
    tasks=[one(n) for n in neighbors]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%25==0: print(f"  {done}/{len(neighbors)}")
    print(f"P done: {len(neighbors)} names")

asyncio.run(main())
