"""
Bucket M — multilingual news mode (Hebrew, Russian, French, Spanish, Portuguese).
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
    # Hebrew
    'חב״ד רב הואשם',
    'חב״ד רב הורשע',
    'חב״ד רב נעצר',
    'חב״ד שערוריה התעללות',
    'חב״ד הונאה כספית',
    'רב חב״ד פדופיל',
    'שלוחי חב״ד פלילי',
    'חב״ד כפר חב״ד תקיפה',
    'בית דין חב״ד טיוח',
    'חב״ד ישיבה התעללות',
    # Russian
    'Хабад раввин арестован',
    'Хабад мошенничество',
    'Любавич скандал',
    'ФЕОР Берл Лазар коррупция',
    'Хабад раввин осужден',
    'Хабад растление',
    'Любавич педофил рав',
    'Хабад уклонение от налогов',
    # French
    'Loubavitch rabbin arrêté',
    'Loubavitch rabbin condamné',
    'Habad scandale abus',
    'Loubavitch fraude fiscale',
    'Beth Loubavitch enquête',
    'rabbin Habad pédophile',
    'Loubavitch France procès',
    # Spanish
    'Jabad rabino arrestado',
    'Lubavitch fraude rabino',
    'Jabad abuso sexual',
    'Lubavitch escándalo Argentina',
    'rabino Jabad condenado',
    # Portuguese
    'Chabad rabino preso',
    'Lubavitch fraude Brasil',
    'rabino Chabad abuso',
    # German
    'Chabad Rabbi verhaftet',
    'Lubawitsch Skandal',
    'Chabad Missbrauch',
    # Yiddish-ish via transliteration (Tavily handles)
    'Chabad gevalt arrested rabbi',
    'Lubavitcher rabbi misnagid scandal',
]

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
    out = ROOT/"data/raw/searches/bucket_m"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    print(f"firing {len(QUERIES)} multilingual queries")
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%15==0: print(f"  {done}/{len(QUERIES)}")
    print("M done")

asyncio.run(main())
