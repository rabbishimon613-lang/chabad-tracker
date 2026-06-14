"""
Bucket DD — Full article fetches for high-value URLs identified in previous buckets.
Fetches actual article text instead of just snippets, for better extraction.
"""
import asyncio, json, os, pathlib, httpx, sys

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))

from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT_FILE = ROOT / "data/raw/triage/snippet_extracts.jsonl"

# Known high-value URLs we want full text extraction on
HIGH_VALUE_URLS = [
    "https://theawarenesscenter.org/index-3.html",
    "https://www.theawarenesscenter.org/chabad.html",
    "https://failedmessiah.typepad.com/failed_messiahcom/chabad/",
    "https://www.forward.com/tag/chabad/",
    "https://jewishweek.timesofisrael.com/tag/chabad/",
    "https://www.justice.gov/usao-edny/pr/brooklyn-rabbi-sentenced-103-years-prison-sexually-abusing-young-female-members-his",
    "https://www.justice.gov/usao-edny/pr/rabbi-sentenced-prison-sexually-abusing-girls-hasidic-community",
    "https://www.justice.gov/usao-sdny/pr/rabbi-convicted-extortion-charges-connection-plot-use-electric-cattle-prods-and-choke",
    "https://www.justice.gov/usao-nj/pr/lakewood-rabbi-sentenced-federal-prison-money-laundering",
    "https://www.justice.gov/usao-nj/pr/rabbi-zalmen-sorotzkin-lakewood-indicted-ppp-loan-fraud",
]

EXTRACT_PROMPT = """Extract ALL criminal/legal incidents from this article for a Chabad-Lubavitch wrongdoing database.

URL: {url}
CONTENT: {content}

Output one JSON object per line for each distinct incident. Schema:
{{"name":"Full Name","type":"financial_fraud|tax_evasion|money_laundering|sexual_abuse|child_pornography|assault|cover_up|drug_trafficking|immigration_fraud|insurance_fraud|welfare_fraud|other","severity":"allegation|investigation|charged|indicted|convicted|settled","year":YYYY_or_null,"location":"City, Country or null","entity":"Chabad/Lubavitch house or org name or null","summary":"one sentence ≤120 chars"}}

Rules:
- Only include if a named individual or named Chabad entity is clearly the perpetrator
- Chabad as VICTIM is excluded (e.g., attacks on synagogues)
- If no clear perpetrator: output {{"skip":true}}
- Output ONLY JSON lines, zero prose"""

async def fetch_and_extract(url, client, sem, providers):
    # Try Tavily content extraction
    keys = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]
    key = keys[0]
    async with sem:
        try:
            r = await client.post("https://api.tavily.com/search", json={
                "api_key": key,
                "query": url,
                "search_depth": "advanced",
                "max_results": 1,
                "include_raw_content": True,
            }, timeout=30)
            data = r.json()
            results = data.get("results", [])
            content = ""
            for res in results:
                content = res.get("raw_content") or res.get("content", "")
                if content: break
        except:
            content = ""

        if not content:
            # Fallback: direct HTTP fetch
            try:
                resp = await client.get(url, timeout=15, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"})
                content = resp.text[:4000]
            except:
                return []

        if not content or len(content) < 100:
            return []

        prompt = EXTRACT_PROMPT.format(url=url[:200], content=content[:3000])
        try:
            result = await dispatch_role("fast", prompt, 600, providers)
            resp_text = result.text if result and result.text else ""
            results = []
            for line in resp_text.strip().split("\n"):
                line = line.strip()
                if not line: continue
                try:
                    obj = json.loads(line)
                    if obj.get("skip"): continue
                    if not obj.get("name") and not obj.get("entity"): continue
                    obj["source_url"] = url
                    results.append(obj)
                except: pass
            return results
        except: return []

async def main():
    # Load already done URLs
    done_urls = set()
    if OUT_FILE.exists():
        for line in OUT_FILE.read_text().splitlines():
            try: done_urls.add(json.loads(line).get("source_url",""))
            except: pass

    remaining = [u for u in HIGH_VALUE_URLS if u not in done_urls]
    print(f"Fetching {len(remaining)} high-value URLs...")

    providers = build_providers()
    sem = asyncio.Semaphore(4)
    total = 0

    async with httpx.AsyncClient() as client:
        tasks = [fetch_and_extract(u, client, sem, providers) for u in remaining]
        with open(OUT_FILE, "a") as f:
            for coro in asyncio.as_completed(tasks):
                results = await coro
                for r in results:
                    f.write(json.dumps(r) + "\n")
                    total += 1

    print(f"Done. New extracts: {total}")

asyncio.run(main())
