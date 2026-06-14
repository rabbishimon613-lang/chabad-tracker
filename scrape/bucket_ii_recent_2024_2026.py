"""
Bucket II — Recent 2024-2026 cases found via Exa semantic search.
Fetch full content + extract directly.
"""
import asyncio, json, pathlib, sys, os

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
for line in open(FLEET / ".env"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k, v.strip('"').strip("'"))

from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
OUT_FILE = ROOT / "data/raw/triage/snippet_extracts.jsonl"

# High-value URLs from Exa search — recent cases 2024-2026
URLS_WITH_CONTEXT = [
    # Australia Chabad 2025 conviction
    ("https://www.timesofisrael.com/son-of-chabad-rabbi-in-australia-convicted-of-child-sex-abuse-in-long-running-scandal/",
     "Member of prominent Chabad family in Australia convicted of child sex abuse in long-running scandal, December 2025"),
    # Serebryanski March 2026
    ("https://www.news.com.au/national/victoria/courts-law/zev-serebryanski-avoids-further-jail-over-child-sexual-abuse-of-manny-waks-in-a-melbourne-synagogue-almost-four-decades-ago/news-story/aa9a78e3ab706c37008fb85ed44afc61",
     "Zev Serebryanski avoids further jail over child sexual abuse of Manny Waks, March 2026"),
    # Florida rabbi Sep 2025
    ("https://www.wpbf.com/article/florida-delray-beach-rabbi-arrested-charges-exploitation-of-a-minor/67999531",
     "Florida Delray Beach rabbi arrested on charges exploitation of minor, September 2025"),
    # Dallas rabbi April 2025
    ("https://www.timesofisrael.com/israeli-born-rabbi-at-dallas-jewish-school-arrested-for-molesting-a-student/",
     "Israeli-born rabbi at Dallas Jewish school arrested for molesting a student, April 2025"),
    # Chabad tunnel 2024
    ("https://www.jpost.com/diaspora/article-796675",
     "13 rabbinical students charged for fracas over Chabad synagogue tunnel, April 2024"),
    # Cleveland rabbi convicted 2023
    ("https://www.clevelandjewishnews.com/news/local_news/rabbi-weiss-sentenced-to-six-months-in-prison/article_d80276f8-b6b0-11ed-b972-03fff2f6abcc.html",
     "Rabbi Weiss sentenced to six months in prison for soliciting underage sex, Cleveland 2023"),
    # JTA Cleveland 2023
    ("https://www.jta.org/2023/03/01/united-states/cleveland-rabbi-sentenced-to-prison-for-soliciting-underage-sex-had-a-prominent-conservative-rabbi-as-his-character-witness",
     "Cleveland rabbi sentenced to prison for soliciting underage sex 2023"),
    # SA Jewish Report Australia Chabad 2015
    ("https://www.sajr.co.za/chabads-aus-child-sex-abuse-scandal-grows",
     "Chabad Australia child sex abuse scandal grows - multiple convictions"),
    # More recent Exa leads
    ("https://forward.com/news/505621/yisroel-goldstein-chabad-of-poway-rabbi-out-of-prison/",
     "Yisroel Goldstein Chabad Poway rabbi out of prison early 2022"),
    ("https://www.shorenewsnetwork.com/2022/08/20/san-diego-attorney-sentenced-for-500000-tax-fraud-with-former-chabad-of-poway-rabbi-goldstein/",
     "San Diego attorney sentenced for tax fraud with Chabad Poway Rabbi Goldstein 2022"),
    ("https://www.jpost.com/diaspora/article-715327",
     "Challah tefillin were code words in Poway Chabad tax fraud scheme"),
    # VINnews 2026 recent
    ("https://vinnews.com/2026/04/30/israeli-yeshiva-administrator-who-fled-israel-arrested-in-u-s-over-alleged-sex-offenses-against-minors/",
     "Israeli yeshiva administrator fled Israel arrested in US for sex offenses against minors, April 2026"),
]

EXTRACT_PROMPT = """Extract ALL criminal/legal incidents from this article for a Chabad-Lubavitch wrongdoing database.

CONTEXT: {context}
URL: {url}

Fetch the page at the URL and extract all incidents.

Output one JSON object per line for each distinct incident. Schema:
{{"name":"Full Name","type":"financial_fraud|tax_evasion|money_laundering|sexual_abuse|child_pornography|assault|cover_up|drug_trafficking|immigration_fraud|insurance_fraud|welfare_fraud|other","severity":"allegation|investigation|charged|indicted|convicted|settled","year":YYYY_or_null,"location":"City, Country or null","entity":"Chabad/Lubavitch house or org name or null","summary":"one sentence ≤120 chars","source_url":"{url}"}}

Rules:
- Only include if Chabad person/entity is clearly the PERPETRATOR
- Chabad as victim (attacks on synagogues etc.) = SKIP
- If no clear perpetrator: output {{"skip":true}}
- Output ONLY JSON lines, zero prose"""

async def extract_one(url, context, sem, providers, tavily_key):
    import httpx
    # Fetch via Tavily
    async with sem:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post("https://api.tavily.com/search", json={
                    "api_key": tavily_key,
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

        if not content or len(content) < 100:
            # Direct fetch fallback
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=15, follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0"})
                    content = resp.text[:5000]
            except:
                return []

        prompt = f"""Extract criminal/legal incidents for a Chabad-Lubavitch wrongdoing database.

CONTEXT: {context}
URL: {url}
CONTENT: {content[:3000]}

Output one JSON object per line per incident:
{{"name":"Full Name","type":"financial_fraud|tax_evasion|money_laundering|sexual_abuse|child_pornography|assault|cover_up|drug_trafficking|immigration_fraud|insurance_fraud|welfare_fraud|other","severity":"allegation|investigation|charged|indicted|convicted|settled","year":YYYY_or_null,"location":"City, Country","entity":"Chabad org name or null","summary":"one sentence ≤120 chars"}}

Only Chabad perpetrators. Chabad as victim = skip. Output ONLY JSON."""

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
    # Load done URLs
    done_urls = set()
    if OUT_FILE.exists():
        for line in OUT_FILE.read_text().splitlines():
            try: done_urls.add(json.loads(line).get("source_url",""))
            except: pass

    remaining = [(url, ctx) for url, ctx in URLS_WITH_CONTEXT if url not in done_urls]
    print(f"Fetching {len(remaining)} URLs...")

    providers = build_providers()
    keys = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]
    sem = asyncio.Semaphore(4)
    total = 0

    tasks = [extract_one(url, ctx, sem, providers, keys[i % len(keys)])
             for i, (url, ctx) in enumerate(remaining)]

    with open(OUT_FILE, "a") as f:
        for coro in asyncio.as_completed(tasks):
            results = await coro
            for r in results:
                f.write(json.dumps(r) + "\n")
                total += 1
                print(f"  + {r.get('name','?')}: {r.get('summary','')[:80]}")

    print(f"\nDone. New raw extracts: {total}")

asyncio.run(main())
