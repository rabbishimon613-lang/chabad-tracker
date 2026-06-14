"""
Bucket BB — International expansion: Israel, UK, Canada, Australia deep-dives.
"""
import asyncio, json, os, pathlib, httpx, itertools

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]
OUT = ROOT / "data/raw/buckets"
OUT.mkdir(parents=True, exist_ok=True)

QUERIES = [
    # Israel
    'חב"ד רב הורשע הונאה',
    'חב"ד רב מעשים מגונים',
    'חב"ד רב נאשם הונאה',
    'חב"ד כת מרמה ישראל',
    "chabad rabbi Israel fraud convicted haaretz",
    "chabad rabbi Israel sex crimes convicted ynet",
    "chabad rabbi arrested Israel fraud 2020 2021 2022 2023",
    "lubavitch Israel money laundering convicted",
    '"כולל חב"ד" הונאה',
    # Haaretz English
    'site:haaretz.com chabad rabbi convicted fraud',
    'site:haaretz.com chabad rabbi arrested',
    'site:haaretz.com lubavitch fraud',
    'site:haaretz.com chabad sex abuse',
    # Times of Israel
    'site:timesofisrael.com chabad rabbi convicted fraud',
    'site:timesofisrael.com chabad rabbi arrested charged',
    'site:timesofisrael.com chabad rabbi sex abuse',
    'site:timesofisrael.com lubavitch fraud convicted',
    # Ynet
    'site:ynet.co.il chabad convicted',
    'site:ynetnews.com chabad rabbi arrested',
    # Australia
    'site:theage.com.au chabad rabbi convicted',
    'site:smh.com.au chabad rabbi convicted',
    'site:abc.net.au chabad rabbi abuse',
    '"Yeshivah Centre" Melbourne abuse conviction',
    '"Yeshivah Centre" Melbourne Cyprys conviction',
    'chabad Australia "sex abuse" conviction sentence',
    '"Adass Israel" Melbourne abuse',
    'site:heraldsun.com.au chabad rabbi',
    # UK
    'site:theguardian.com chabad rabbi convicted',
    'site:bbc.co.uk chabad rabbi fraud abuse',
    'site:jewishchronicle.co.uk chabad rabbi convicted',
    'chabad UK rabbi "Crown Prosecution" convicted',
    'lubavitch UK fraud convicted',
    # Canada
    'site:cbc.ca chabad rabbi convicted fraud abuse',
    'site:globeandmail.com chabad rabbi fraud convicted',
    'chabad Canada rabbi "sexual abuse" convicted',
    'lubavitch Canada fraud charges',
    '"Chabad of Montreal" fraud',
    '"Chabad of Toronto" fraud investigation',
    # South Africa
    '"David Kramer" rabbi South Africa charges',
    'chabad "South Africa" rabbi fraud convicted',
    'chabad South Africa sexual abuse rabbi',
    # Argentina
    '"Chabad" Argentina "estafa" "detenido"',
    '"Jabad" Argentina "fraude" "detenido" "condena"',
    '"Jabad" Buenos Aires "abuso" "condena"',
    # Brazil
    '"Chabad" Brasil "fraude" "preso" "condenado"',
    '"Chabad" São Paulo "abuso" "preso"',
    # France
    'site:lemonde.fr "Chabad" rabbin condamné',
    '"Loubavitch" France fraude condamné',
    '"Chabad" France "abus sexuel" rabbin',
    # Germany
    '"Chabad" Deutschland Rabbi verurteilt Betrug',
    # Russia
    'Хабад раввин мошенничество осужден',
    'Хабад раввин арестован обвинение',
    '"ФЕОР" скандал мошенничество',
]

key_cycle = itertools.cycle(KEYS)

async def tavily_search(query, client, semaphore):
    key = next(key_cycle)
    async with semaphore:
        try:
            r = await client.post("https://api.tavily.com/search", json={
                "api_key": key,
                "query": query,
                "search_depth": "basic",
                "max_results": 7,
                "include_answer": False,
            }, timeout=30)
            data = r.json()
            return query, data.get("results", [])
        except Exception as e:
            return query, []

async def main():
    out_file = OUT / "bucket_bb.jsonl"
    done_queries = set()
    if out_file.exists():
        for line in out_file.read_text().splitlines():
            try: done_queries.add(json.loads(line)["query"])
            except: pass
    print(f"Already done: {len(done_queries)}")

    remaining = [q for q in QUERIES if q not in done_queries]
    print(f"Running {len(remaining)} queries...")

    sem = asyncio.Semaphore(5)
    total = 0
    async with httpx.AsyncClient() as client:
        tasks = [tavily_search(q, client, sem) for q in remaining]
        done = 0
        with open(out_file, "a") as f:
            for coro in asyncio.as_completed(tasks):
                query, results = await coro
                done += 1
                total += len(results)
                f.write(json.dumps({"query": query, "results": results}) + "\n")
                if done % 10 == 0:
                    print(f"  [{done}/{len(remaining)}] results: {total}")

    print(f"\nDone. Total results: {total}")

asyncio.run(main())
