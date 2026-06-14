"""
Bucket AA — Court records deep-dive: CourtListener, PACER, DOJ, named defendants.
"""
import asyncio, json, hashlib, os, pathlib, httpx, itertools

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
    # CourtListener
    'site:courtlistener.com chabad rabbi fraud',
    'site:courtlistener.com chabad rabbi sexual abuse',
    'site:courtlistener.com lubavitch rabbi convicted',
    'site:courtlistener.com chabad money laundering',
    'site:courtlistener.com "chabad" "guilty"',
    # Justia
    'site:law.justia.com chabad rabbi convicted',
    'site:law.justia.com lubavitch rabbi fraud',
    'site:law.justia.com chabad sexual abuse conviction',
    # Named defendants deep-dive
    '"David Cyprys" Yeshivah Centre conviction sentence',
    '"David Cyprys" Melbourne sexual abuse plea',
    '"Sholom Rubashkin" AgriProcessors sentence 2018',
    '"Yisroel Goldstein" Poway fraud plea deal sentence',
    '"David Kramer" rabbi St Louis South Africa extradition',
    '"Mendel Epstein" torture conviction sentence 2015',
    '"Nechemya Weberman" sentenced Brooklyn 103 years',
    '"Baruch Lebovits" convicted sex abuse Brooklyn appeal',
    '"Eliyahu Weinstein" Ponzi scheme fraud rabbi NJ',
    '"Moshe Zigelman" Chabad tax fraud conviction',
    '"Naftali Tzvi Weisz" Spinka rabbi tax fraud plea',
    '"Abraham Rubin" rabbi extortion conviction',
    '"Gershon Kranczer" rabbi fugitive Israel sex crimes',
    '"Eliezer Berland" rabbi sex crimes conviction Israel',
    '"Motti Elon" rabbi sexual abuse conviction Israel',
    '"Chaim Walder" rabbi suicide allegations',
    '"Yosef Feldman" rabbi Sydney misconduct',
    '"Dan Hayman" rabbi fraud conviction',
    '"Yehuda Hadjadj" rabbi arrested charged',
    '"Velvel Serebryanski" rabbi convicted Australia',
    '"Schmuel Fogelman" rabbi fraud conviction',
    # New financial fraud leads
    'chabad rabbi "wire fraud" convicted sentenced site:justice.gov',
    'chabad rabbi "bank fraud" convicted sentenced site:justice.gov',
    'chabad "health care fraud" convicted sentenced',
    'chabad rabbi "mortgage fraud" convicted',
    'chabad rabbi "PPP loan fraud" arrested',
    'chabad rabbi "COVID fraud" arrested charged',
    # Sexual abuse new leads
    'chabad rabbi "sexual assault" convicted sentenced',
    'chabad yeshiva "sexual abuse" covered up lawsuit settlement',
    'chabad camp "sexual abuse" lawsuit',
    '"chabad" rabbi "child abuse" arrested charged indicted',
    # Civil suits
    'chabad house "civil lawsuit" fraud settlement',
    'chabad organization "lawsuit" "sexual abuse" settlement',
    'chabad rabbi "civil rights" lawsuit judgment',
    # Get refusal / coercion
    'rabbi "get refusal" chabad convicted coercion',
    'rabbinical court "extortion" chabad convicted',
    '"forced get" rabbi convicted sentenced',
    # Money laundering / terror finance
    'chabad rabbi "money laundering" convicted sentenced',
    'chabad "terror financing" investigation FBI',
    'lubavitch "money laundering" bank fraud convicted',
    # Drug trafficking
    'chabad rabbi "drug trafficking" arrested convicted',
    'lubavitch "drug dealer" rabbi arrested',
    # Immigration fraud
    'chabad rabbi "immigration fraud" convicted sentenced',
    'chabad "visa fraud" rabbi arrested',
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
            results = data.get("results", [])
            return query, results
        except Exception as e:
            return query, []

async def main():
    out_file = OUT / "bucket_aa.jsonl"
    done_queries = set()
    if out_file.exists():
        for line in out_file.read_text().splitlines():
            try:
                done_queries.add(json.loads(line)["query"])
            except: pass
    print(f"Already done: {len(done_queries)} queries")

    remaining = [q for q in QUERIES if q not in done_queries]
    print(f"Running {len(remaining)} queries...")

    sem = asyncio.Semaphore(5)
    total_results = 0

    async with httpx.AsyncClient() as client:
        tasks = [tavily_search(q, client, sem) for q in remaining]
        done = 0
        with open(out_file, "a") as f:
            for coro in asyncio.as_completed(tasks):
                query, results = await coro
                done += 1
                total_results += len(results)
                f.write(json.dumps({"query": query, "results": results}) + "\n")
                if done % 10 == 0:
                    print(f"  [{done}/{len(remaining)}] total results: {total_results}")

    print(f"\nDone. Total results: {total_results}")

asyncio.run(main())
