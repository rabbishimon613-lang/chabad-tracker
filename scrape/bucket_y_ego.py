"""
Bucket Y — Ego-network searches on top 20 perpetrators.
Each known bad actor → search for co-defendants, associates, lawyers, yeshiva ties.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

TOP_PEOPLE = [
    ("David Cyprys", "Melbourne Chabad"),
    ("Sholom Rubashkin", "Agriprocessors"),
    ("Yisroel Goldstein", "Chabad of Poway"),
    ("David Kramer", "Chabad Melbourne"),
    ("Dan Hayman", "Chabad rabbi"),
    ("Yosef Feldman", "Chabad Sydney rabbi"),
    ("Baruch Mordechai Lebovits", "Brooklyn rabbi"),
    ("Nechemya Weberman", "Brooklyn Satmar"),
    ("Eliyahu Weinstein", "rabbi New Jersey"),
    ("Mendel Epstein", "rabbi New Jersey"),
    ("Moshe Zigelman", "Spinka rabbi"),
    ("Naftali Tzvi Weisz", "Spinka Grand Rabbi"),
    ("Jacob Harari", "rabbi fraud"),
    ("Velvel Serebryanski", "Chabad Melbourne"),
    ("Yisroel Telsner", "Chabad Melbourne"),
    ("Aaron Rubashkin", "Agriprocessors"),
    ("Boruch Cunin", "Chabad California"),
    ("Yosef Yitzchak Ahronov", "Chabad Israel"),
    ("Eliyahu Ezagui", "Chabad rabbi"),
    ("Charles Lesser", "Chabad rabbi"),
]

QUERY_TEMPLATES = [
    "{name} co-defendant accomplice",
    "{name} associate indicted",
    "{name} {ctx} accomplice",
    "{name} {ctx} co-conspirator",
    "{name} rabbi sentencing",
    "{name} court documents",
    "{name} plea deal agreement",
]

QUERIES = []
for name, ctx in TOP_PEOPLE:
    for tmpl in QUERY_TEMPLATES:
        QUERIES.append(tmpl.format(name=name, ctx=ctx))

# Additional targeted: look for entire organizations linked to fraud
QUERIES += [
    "Agriprocessors co-defendants full list convicted",
    "Agriprocessors Postville workers charged",
    "Agriprocessors Sholom Rubashkin family members charged",
    "Chabad of Poway Yisroel Goldstein co-defendants list",
    "Spinka rabbi fraud co-conspirators full list",
    "Mendel Epstein gang rabbis convicted",
    "Eliyahu Weinstein fraud co-defendants New Jersey",
    "Baruch Lebovits appeal accomplices Brooklyn",
    "Chabad Melbourne abuse enablers Yeshivah",
    "Yeshivah Centre Melbourne enablers Royal Commission",
    "Cyprys Kramer Chabad Melbourne network",
    "Crown Heights rabbinical court beit din ban excommunication",
    "Chabad rabbi cherem excommunication banned",
    "rabbinical court ordered get abuse",
    "ORA organization rabbi divorce coercion convicted",
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
    out = ROOT/"data/raw/searches/bucket_y_ego"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%20==0: print(f"  {done}/{len(QUERIES)}")
    print("Y done")

asyncio.run(main())
