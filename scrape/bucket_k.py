"""
Bucket K — Tavily news mode (topic="news"). Casts a wide net across general news
outlets rather than site:-filtered. Broad keyword queries.
"""
import asyncio, json, hashlib, sys, pathlib, os, httpx, itertools, random

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ.get("TAVILY_API_KEYS","").split(",") if k.strip()]
assert KEYS, "no TAVILY_API_KEYS in env"

# Broad keyword set — no site: filters, no year qualifiers (let news index decide recency)
QUERIES = [
    # Direct accusations
    "Chabad rabbi arrested",
    "Chabad rabbi indicted",
    "Chabad rabbi convicted",
    "Chabad rabbi charged sexual abuse",
    "Chabad rabbi child abuse",
    "Chabad rabbi fraud charges",
    "Chabad rabbi embezzlement",
    "Chabad rabbi money laundering",
    "Chabad rabbi tax evasion",
    "Lubavitch rabbi arrested",
    "Lubavitch rabbi convicted",
    "Lubavitch yeshiva abuse lawsuit",
    "Lubavitch school sexual abuse",
    "Lubavitch summer camp abuse",
    # Institutional
    "Chabad House lawsuit",
    "Chabad center scandal",
    "Chabad Lubavitch headquarters lawsuit",
    "Agudath Israel Chabad scandal",
    "Crown Heights Chabad arrest",
    "Crown Heights rabbi arrested",
    # Country / region terms
    "Chabad Israel arrested",
    "Chabad Australia abuse",
    "Yeshivah Centre Melbourne",
    "Chabad UK fraud",
    "Chabad France investigation",
    "Chabad Russia oligarch",
    "Berel Lazar controversy",
    # Famous case keywords
    "Sholom Rubashkin",
    "Rubashkin Agriprocessors",
    "Manis Friedman controversy",
    "Yisroel Goldstein Poway fraud",
    "Aron Tendler abuse",
    "Yosef Goldstein abuse rabbi",
    "Mendel Levy Chabad",
    "David Cyprys Chabad",
    "Daniel Hayut Chabad abuse",
    "Sholom Friedman Chabad",
    "Chaim Cunin Chabad lawsuit",
    "Boruch Lesches Sydney",
    "Velvel Serebryanski",
    "Jonathan Mandel rabbi convicted",
    # Crime keywords with religion contextual hits
    "Hasidic rabbi arrested abuse",
    "Hasidic rabbi fraud guilty",
    "Orthodox rabbi child sexual abuse plea",
    "ultra-Orthodox cover-up abuse",
    # Settler / West Bank
    "Chabad settler West Bank attack",
    "Lubavitch settler violence",
    # Yeshiva-specific
    "Oholei Torah Chabad abuse",
    "Beth Rivkah Chabad scandal",
    "Hadar Hatorah scandal",
    "Tomchei Tmimim abuse",
    # Cover-up framing
    "Chabad abuse cover up",
    "Lubavitch silenced victims",
    "beis din shielded abuser Chabad",
    # Financial
    "Chabad nonprofit fraud audit",
    "Chabad PPP loan fraud",
    "Lubavitch charity scandal",
    "Chabad real estate fraud",
    # Civil suits
    "Chabad civil lawsuit settlement",
    "Lubavitch defamation suit",
    # Trafficking / exploitation
    "Chabad labor trafficking",
    "Chabad immigration fraud",
    # Recent decade catch-all
    "Chabad scandal 2023",
    "Chabad scandal 2024",
    "Chabad scandal 2025",
    "Lubavitch scandal 2024",
    "Lubavitch scandal 2025",
]

async def fire(query, key, out):
    h = hashlib.sha256(query.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key,
                "query": query,
                "topic": "news",
                "max_results": 10,
                "days": 3650,   # ~10y window for news topic
                "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":query,"engine":"tavily-news","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":query,"engine":"tavily-news","results":[],"error":str(e)}, indent=2))

async def main():
    out = ROOT/"data/raw/searches/bucket_k"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem:
            await fire(q, random.choice(KEYS), out)
    print(f"firing {len(QUERIES)} news-mode queries across {len(KEYS)} keys")
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%15==0: print(f"  {done}/{len(QUERIES)}")
    print("done")

asyncio.run(main())
