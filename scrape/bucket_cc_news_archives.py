"""
Bucket CC — News archives, Jewish media, and awareness center deep-dive.
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
    # The Awareness Center archives
    'site:theawarenesscenter.org chabad',
    'site:theawarenesscenter.org lubavitch',
    'site:theawarenesscenter.org rabbi convicted',
    '"awareness center" chabad rabbi sexual abuse',
    # Jewish Week / Times of Israel
    'site:jewishweek.timesofisrael.com chabad rabbi fraud conviction',
    'site:jewishweek.timesofisrael.com chabad rabbi sex abuse arrest',
    'site:jewishweek.timesofisrael.com lubavitch scandal',
    # The Forward
    'site:forward.com chabad rabbi convicted',
    'site:forward.com chabad rabbi arrested charged',
    'site:forward.com lubavitch fraud',
    'site:forward.com chabad sex abuse',
    'site:forward.com chabad cover up',
    # Tablet Magazine
    'site:tabletmag.com chabad rabbi fraud abuse',
    'site:tabletmag.com lubavitch scandal',
    # JTA
    'site:jta.org chabad rabbi convicted sentenced',
    'site:jta.org chabad rabbi arrested charged',
    'site:jta.org lubavitch fraud convicted',
    'site:jta.org chabad sex abuse',
    # Algemeiner
    'site:algemeiner.com chabad rabbi convicted',
    'site:algemeiner.com chabad rabbi arrested fraud',
    # Jewish Press
    'site:jewishpress.com chabad rabbi convicted arrested',
    'site:jewishpress.com lubavitch fraud',
    # Yeshiva World News
    'site:theyeshivaworld.com chabad rabbi arrested convicted',
    'site:theyeshivaworld.com rabbi fraud convicted',
    # Crown Heights Info (community news)
    'site:crownheights.info rabbi arrested',
    'site:crownheights.info fraud conviction',
    # Vos Iz Neias
    'site:vosizneias.com chabad rabbi arrested fraud',
    'site:vosizneias.com rabbi convicted',
    # Jewish Telegraphic Agency historical
    '"chabad" rabbi fraud OR convicted OR arrested site:jta.org 2010..2020',
    # Haaretz English historical
    'chabad rabbi fraud OR convicted OR arrested site:haaretz.com 2010..2024',
    # Specific newer cases to check
    '"Zalmen Sorotzkin" fraud convicted',
    '"Zalmen Sorotzkin" Lakewood rabbi arrest',
    '"Mordechai Fish" rabbi arrested fraud',
    '"Aryeh Goodman" chabad rabbi convicted',
    '"Joseph Levitin" rabbi fraud',
    '"Eliyahu Ezagui" rabbi fraud conviction',
    '"Schmuel Fogelman" rabbi fraud Australia',
    '"Yochanan Levitansky" rabbi fraud',
    '"Charles Lesser" chabad fraud',
    '"Jimmy Gurary" chabad fraud conviction',
    '"Nechama Dina Krinsky" fraud',
    '"Aaron Rubashkin" fraud conviction',
    '"Boruch Cunin" chabad California lawsuit fraud',
    # Money / fraud in Orthodox world
    'chabad "PPP loan fraud" rabbi 2021 2022',
    'chabad rabbi "covid relief fraud" arrested',
    'chabad rabbi "SBA loan" fraud arrested',
    # Sexual abuse new leads
    'chabad rabbi "statutory rape" convicted',
    'chabad rabbi "indecent assault" convicted',
    '"chabad" rabbi "sex offender" registered',
    'chabad yeshiva teacher "sexual abuse" conviction',
    # Institutional failures
    'chabad "mandatory reporter" failure lawsuit',
    'chabad "cover up" abuse lawsuit settlement',
    'chabad "failure to report" abuse',
    # Orthodox crime blogs
    'site:failedmessiah.com chabad convicted',
    'site:failedmessiah.com chabad fraud',
    'site:failedmessiah.com chabad arrested',
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
    out_file = OUT / "bucket_cc.jsonl"
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
