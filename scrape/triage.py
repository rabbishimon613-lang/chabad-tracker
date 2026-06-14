"""
Triage pass: for each unique URL in Bucket A, fleet_fast classifies whether it's
Chabad-related and extracts perpetrator name(s), incident type, severity.

Input:  data/raw/searches/bucket_a/*.json
Output: data/raw/triage/triage.jsonl  (one JSON object per URL)
"""
import asyncio, json, pathlib, sys, glob

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
from dotenv import load_dotenv
load_dotenv(FLEET / ".env")
from providers import build_providers           # noqa: E402
from roles import dispatch_role                 # noqa: E402

ROOT  = pathlib.Path(__file__).resolve().parent.parent
OUT   = ROOT / "data" / "raw" / "triage"
OUT.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT / "triage.jsonl"

PROMPT = """You triage one search result for a database tracking Chabad-Lubavitch misdeeds (crimes, lawsuits, abuse, fraud, cover-ups, settler violence, etc.). Output ONLY valid JSON, no preamble, no markdown fences.

Input:
TITLE: {title}
URL: {url}
SNIPPET: {snippet}

Output schema (all fields required):
{{
  "is_chabad_related": true|false,
  "confidence": "high"|"medium"|"low",
  "perpetrator_names": ["Full Name", ...],
  "incident_type": "csa"|"sexual_abuse"|"sexual_assault"|"financial_fraud"|"embezzlement"|"tax_evasion"|"deed_theft"|"real_estate_fraud"|"trafficking_persons"|"trafficking_drugs"|"murder"|"assault"|"domestic_violence"|"cover_up"|"obstruction"|"settler_violence"|"illegal_settlement"|"money_laundering"|"bribery"|"corruption"|"shlichus_dispute"|"other"|"unclear",
  "severity": "allegation"|"investigation"|"charged"|"indicted"|"convicted"|"settled"|"acquitted"|"dismissed"|"unclear",
  "year": YYYY integer or null,
  "location": "City, Region, Country" or null,
  "chabad_entity": "name of Chabad house, family, or institution if identifiable" or null,
  "notes": "one short sentence"
}}

Rules:
- perpetrator_names = people accused/convicted/sued. NOT victims, witnesses, lawyers, judges, or rabbis only quoted in response.
- If the article isn't about Chabad/Lubavitch at all, set is_chabad_related=false and leave other fields as "unclear"/null/[].
- Be conservative. If the snippet is too thin to judge, use "unclear" and confidence "low".
- Return ONLY the JSON object, nothing else."""


def load_urls():
    seen, items = set(), []
    for f in sorted(glob.glob(str(ROOT / "data/raw/searches/bucket_a/*.json"))):
        d = json.loads(open(f).read())
        for r in d.get("results", []):
            u = (r.get("url") or "").strip()
            if not u or u in seen: continue
            seen.add(u)
            items.append({
                "url": u,
                "title": (r.get("title") or "")[:200],
                "snippet": (r.get("snippet") or "")[:600],
            })
    return items


async def main():
    providers = build_providers()
    items = load_urls()
    print(f"unique URLs to triage: {len(items)}")

    sem = asyncio.Semaphore(8)
    counts = {"ok":0, "err":0, "chabad":0, "perps":0}

    async def one(it):
        async with sem:
            p = PROMPT.format(title=it["title"], url=it["url"], snippet=it["snippet"])
            # uncensored role: Kimi → GPT-OSS 120B → Nemotron. NO Llama
            # because Groq's safety filter empties out crime/abuse prompts.
            r = await dispatch_role("uncensored", p, max_tokens=400, providers=providers)
        rec = {**it}
        if not r.ok or not r.text:
            counts["err"] += 1
            rec["error"] = r.error or "empty_response"
            return rec
        # parse JSON from text (model may add fences despite the prompt)
        txt = r.text.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            if txt.lower().startswith("json"): txt = txt[4:]
            txt = txt.strip()
        try:
            parsed = json.loads(txt)
            rec.update(parsed)
            counts["ok"] += 1
            if parsed.get("is_chabad_related"):
                counts["chabad"] += 1
                counts["perps"] += len(parsed.get("perpetrator_names") or [])
        except Exception as e:
            rec["error"] = f"parse:{e}"
            rec["raw"]   = txt[:500]
            counts["err"] += 1
        return rec

    results = await asyncio.gather(*[one(it) for it in items])
    with OUT_FILE.open("w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\ndone. ok={counts['ok']} err={counts['err']} "
          f"chabad-related={counts['chabad']} perp-mentions={counts['perps']}")
    print(f"-> {OUT_FILE}")

asyncio.run(main())
