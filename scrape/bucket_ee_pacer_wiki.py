"""
Bucket EE — Wikipedia, PACER case summaries, and academic sources.
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
    # Wikipedia — often has comprehensive crime summaries
    'site:en.wikipedia.org "chabad" rabbi convicted',
    'site:en.wikipedia.org "lubavitch" rabbi fraud',
    'site:en.wikipedia.org "chabad" "sexual abuse"',
    'site:en.wikipedia.org Sholom Rubashkin',
    'site:en.wikipedia.org Nechemya Weberman',
    'site:en.wikipedia.org "Mendel Epstein" rabbi',
    'site:en.wikipedia.org "Eliyahu Weinstein" rabbi',
    'site:en.wikipedia.org Moshe Zigelman chabad',
    'site:en.wikipedia.org AgriProcessors',
    'site:en.wikipedia.org "Yeshivah Centre" abuse',
    'site:en.wikipedia.org "David Cyprys"',
    # Academic
    'site:academiccommons.columbia.edu chabad',
    'chabad lubavitch sexual abuse academic study journal',
    'ultra orthodox jewish community sexual abuse cover up study',
    # PACER/court
    'site:pacer.gov chabad rabbi',
    'site:ecf.nysd.uscourts.gov chabad',
    'site:ecf.nyed.uscourts.gov chabad',
    # Law review
    'chabad rabbi fraud conviction law review',
    'orthodox jewish community abuse cover up law review',
    # Specific Wikipedia-worthy cases
    'en.wikipedia.org "Baruch Lebovits"',
    'en.wikipedia.org "Tevya Mordechai Rotberg"',
    'en.wikipedia.org "Gershon Burd"',
    '"Moishe Laufer" chabad convicted',
    '"David Mandel" rabbi fraud chabad',
    # More specific court case searches
    '"United States v." chabad rabbi guilty',
    '"People v." chabad rabbi convicted',
    '"State v." chabad rabbi convicted sexual',
    # State court news
    '"Brooklyn District Attorney" chabad rabbi',
    '"Manhattan DA" chabad rabbi',
    '"Queens DA" chabad rabbi',
    '"NJ attorney general" chabad rabbi',
    '"Los Angeles DA" chabad rabbi convicted',
    '"Chicago" chabad rabbi arrested convicted fraud',
    # Federal districts
    '"Eastern District of New York" chabad rabbi',
    '"Southern District of New York" chabad rabbi',
    '"District of New Jersey" chabad rabbi',
    '"Northern District of Illinois" chabad rabbi',
    '"Central District of California" chabad rabbi',
    # New specific people
    '"Levi Greenberg" chabad fraud',
    '"Shmaya Krinsky" chabad fraud',
    '"Mordechai Gutnick" chabad australia',
    '"Tzvi Hirsch Telsner" cover up conviction',
    '"Yitzchok Groner" chabad cover up',
    '"Pinchas Feldman" australia chabad',
    '"Moshe Gutnick" chabad australia controversy',
    '"Menachem Hartman" rabbi arrested',
    '"Ari Telerant" rabbi fraud',
    '"Shmuley Boteach" controversy fraud',
    '"Levi Shemtov" chabad DC fraud',
    '"Nochem Rosenberg" chabad blogger arrested',
    '"Yaakov Yitchak Biderman" chabad Vienna fraud',
    '"Moshe Kotlarsky" chabad controversy',
]

key_cycle = itertools.cycle(KEYS)

async def tavily_search(query, client, semaphore):
    key = next(key_cycle)
    async with semaphore:
        try:
            r = await client.post("https://api.tavily.com/search", json={
                "api_key": key, "query": query,
                "search_depth": "basic", "max_results": 7, "include_answer": False,
            }, timeout=30)
            return query, r.json().get("results", [])
        except: return query, []

async def main():
    out_file = OUT / "bucket_ee.jsonl"
    done_queries = set()
    if out_file.exists():
        for line in out_file.read_text().splitlines():
            try: done_queries.add(json.loads(line)["query"])
            except: pass
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
                done += 1; total += len(results)
                f.write(json.dumps({"query": query, "results": results}) + "\n")
                if done % 10 == 0:
                    print(f"  [{done}/{len(remaining)}] results: {total}")
    print(f"\nDone. Total results: {total}")

asyncio.run(main())
