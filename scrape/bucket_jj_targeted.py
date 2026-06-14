"""
Bucket JJ — targeted deep-fetch on newly discovered cases.
Fetches full content via Tavily advanced + direct HTTP, extracts via fleet.
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

URLS_WITH_CONTEXT = [
    # Australia - David Samuel Cyprys convicted 2013
    ("https://www.abc.net.au/news/2013-09-17/man-convicted-of-child-sexual-abuse-at-melbourne-jewish-school/4963208",
     "David Samuel Cyprys convicted of child sexual abuse at Melbourne Yeshivah College (Chabad), 2013"),
    # Aryeh Goodman - Chabad East Brunswick NJ federal sex trafficking
    ("https://njjewishnews.timesofisrael.com/chabad-rabbi-faces-new-sex-charges/",
     "Aryeh Goodman Chabad of East Brunswick NJ federal child sex trafficking charges, registered sex offender"),
    # JTA Aryeh Goodman
    ("https://www.jta.org/2018/02/20/ny/n-j-rabbi-again-faces-sex-charges",
     "Aryeh Goodman New Jersey rabbi sex charges 2018"),
    # David Kramer - American teacher at Chabad Melbourne
    ("https://forward.com/fast-forward/174741/st-louis-teacher-convicted-of-sex-abuse-at-chabad-school/",
     "David Kramer American teacher convicted sex abuse at Chabad Yeshivah College Melbourne, deported"),
    # Australian cover-up - Tzvi Telsner resigned
    ("https://www.theguardian.com/australia-news/2015/sep/02/senior-chabad-rabbi-tzvi-telsner-resigns-after-royal-commission-criticises-his-handling-of-abuse",
     "Rabbi Tzvi Telsner resigns as Melbourne Chabad head after Royal Commission criticizes handling of abuse"),
    # Australian cover-up - Meir Shlomo Kluwgant
    ("https://www.theguardian.com/australia-news/2015/sep/01/chabad-rabbi-who-called-sex-abuse-whistleblower-a-lunatic-resigns",
     "Chabad rabbi Meir Shlomo Kluwgant resigned after calling sex abuse whistleblower lunatic, Royal Commission"),
    # Boro Park Shomrim head sex trafficking
    ("https://www.justice.gov/usao-edny/pr/former-head-boro-park-shomrim-society-sentenced-more-17-years-transporting-minor-sex",
     "Former head of Boro Park Shomrim Society sentenced 17+ years for transporting minor for sex"),
    # North Shore rabbi $22M nursing home Ponzi scheme Illinois
    ("https://patch.com/illinois/skokie/north-shore-rabbi-ran-22-million-nursing-home-ponzi-scheme-feds",
     "North Shore rabbi ran $22M nursing home Ponzi scheme, Skokie Illinois 2020"),
    # Korf Florida - DOJ property seized, Ukraine money laundering
    ("https://forward.com/fast-forward/461418/florida-chabad-donors-property-seized-doj-launched-complaint-to-seize-florida-property-after-money-laundering/",
     "Florida Chabad donors Korf, property seized by DOJ, money laundering from Ukraine"),
    # Chabad Israel mass arrest fraud
    ("https://forward.com/news/12085/chabad-leaders-in-israel-arrested-on-fraud-charges/",
     "Chabad leaders in Israel arrested on fraud charges - mass raid on enclave"),
    # FBI Newark - divorce coercion ring 3 rabbis convicted
    ("https://www.fbi.gov/contact-us/field-offices/newark/news/press-releases/three-orthodox-jewish-rabbis-convicted-of-conpsiracy-to-kidnap-jewish-husbands-in-order-to-force-them-to-consent-to-religious-divorces",
     "Three Orthodox Jewish rabbis convicted of conspiracy to kidnap husbands to force religious divorces - NJ FBI"),
    # Mendel Epstein 10 years - AP
    ("https://apnews.com/2f92b5e0910649ec9022e77c76a63318",
     "Rabbi Mendel Epstein gets decade in prison for divorce coercion kidnapping ring"),
    # Shtetl.org - special ed executive defrauded Haredi children
    ("https://www.shtetl.org/article/special-ed-executive-defrauded-haredi-childrens-programs-sentenced-over-4-years-prison",
     "Special education executive defrauded Haredi children's programs, sentenced over 4 years prison"),
    # DOJ CAC 2009 - Chabad related case
    ("https://www.justice.gov/archive/usao/cac/Pressroom/pr2009/148.html",
     "DOJ Central District California 2009 press release - Chabad related criminal case"),
    # NJ DOJ - Mordchai Fish
    ("https://www.justice.gov/archive/usao/nj/Press/files/Fish,%20Mordchai%20News%20Release.html",
     "Mordchai Fish DOJ New Jersey press release - Orthodox Jewish criminal case"),
    # NJ DOJ - Lavel Schwartz
    ("https://www.justice.gov/archive/usao/nj/Press/files/Schwartz,%20Lavel%20Plea%20News%20Release.html",
     "Lavel Schwartz plea DOJ New Jersey press release"),
    # JFeed - hasidic fraudster faked heart attack
    ("https://www.jfeed.com/crime-and-justice/tdybtq",
     "Hasidic fraudster faked heart attack stunning downfall 2026"),
    # Waks Royal Commission testimony ABC
    ("https://www.abc.net.au/news/2015-02-04/manny-and-zephaniah-waks-tells-royal-commission-sex-abuse-ordeal/6070966",
     "Manny Waks Royal Commission testimony about Chabad Yeshivah Centre abuse, named perpetrators"),
    # ABC royal commission jewish cover-up
    ("https://www.abc.net.au/news/2017-03-23/jewish-leaders-thought-it-was-a-sin-to-report-child-abuse/8380574",
     "Australian Royal Commission Jewish child abuse cover-up - named Chabad leaders, perps"),
    # Wikipedia - Yeshivah Centre Melbourne named individuals
    ("https://en.wikipedia.org/wiki/Yeshivah_Centre,_Melbourne",
     "Yeshivah Centre Melbourne Wikipedia - named individuals convicted of abuse, cover-up rabbis"),
    # Wikipedia divorce coercion gang
    ("https://en.wikipedia.org/wiki/New_York_divorce_coercion_gang",
     "New York divorce coercion gang Wikipedia - named rabbis convicted of kidnapping conspiracy"),
    # Sholom Ber Levitin - Seattle Chabad 1989
    ("https://en.wikipedia.org/wiki/Chabad-Lubavitch_related_controversies",
     "Chabad-Lubavitch related controversies Wikipedia - comprehensive named list"),
]

EXTRACT_PROMPT = """Extract ALL criminal/legal incidents from this article for a Chabad-Lubavitch wrongdoing database.

CONTEXT: {context}
URL: {url}
CONTENT: {content}

Output one JSON object per line for each distinct incident:
{{"name":"Full Name","type":"financial_fraud|tax_evasion|money_laundering|sexual_abuse|child_pornography|assault|cover_up|drug_trafficking|immigration_fraud|insurance_fraud|welfare_fraud|other","severity":"allegation|investigation|charged|indicted|convicted|settled","year":YYYY_or_null,"location":"City, Country","entity":"Chabad org name or null","summary":"one sentence ≤120 chars","source_url":"{url}"}}

Rules:
- Only Chabad/Lubavitch-affiliated perpetrators
- Cover-up, obstruction, helping abusers flee = include (type: cover_up)
- Chabad as victim of outside attacks = SKIP
- If no clear perpetrator: {{"skip":true}}
- Output ONLY JSON lines"""

async def fetch_content(url, tavily_key):
    import httpx
    # Try Tavily advanced first
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
            for res in data.get("results", []):
                content = res.get("raw_content") or res.get("content", "")
                if content and len(content) > 200:
                    return content[:4000]
    except: pass
    # Direct HTTP fallback
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=15, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; research/1.0)"})
            return resp.text[:4000]
    except: return ""

async def extract_one(url, context, sem, providers, tavily_key):
    async with sem:
        content = await fetch_content(url, tavily_key)
        if not content or len(content) < 100:
            print(f"  ⚠ No content: {url[:60]}")
            return []
        prompt = EXTRACT_PROMPT.format(context=context, url=url, content=content[:3500])
        try:
            result = await dispatch_role("fast", prompt, 800, providers)
            resp_text = result.text if result and result.text else ""
            results = []
            for line in resp_text.strip().split("\n"):
                line = line.strip()
                if not line or not line.startswith("{"): continue
                try:
                    obj = json.loads(line)
                    if obj.get("skip"): continue
                    if not obj.get("name") and not obj.get("entity"): continue
                    obj["source_url"] = url
                    results.append(obj)
                except: pass
            return results
        except Exception as e:
            print(f"  ✗ Extract error {url[:60]}: {e}")
            return []

async def main():
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
