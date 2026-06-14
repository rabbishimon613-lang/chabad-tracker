"""
Re-triage rows that errored in the first pass, using the uncensored role.
Reads:  data/raw/triage/triage.jsonl
Writes: data/raw/triage/triage.jsonl (rewritten in place with retried rows updated)
"""
import asyncio, json, pathlib, sys

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
import os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from providers import build_providers           # noqa: E402
from roles import dispatch_role                 # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
F    = ROOT / "data" / "raw" / "triage" / "triage.jsonl"

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


async def main():
    providers = build_providers()
    rows = [json.loads(l) for l in open(F)]
    err_idx = [i for i,r in enumerate(rows) if "error" in r]
    print(f"total rows: {len(rows)} | retrying: {len(err_idx)}")

    sem = asyncio.Semaphore(6)
    counts = {"recovered":0, "still_err":0, "chabad":0, "perps":0}

    async def one(i):
        it = rows[i]
        async with sem:
            p = PROMPT.format(title=it.get("title",""), url=it["url"], snippet=it.get("snippet",""))
            r = await dispatch_role("fast", p, max_tokens=400, providers=providers)
        if not r.ok or not (r.text or "").strip():
            counts["still_err"] += 1
            rows[i] = {**it, "error": r.error or "empty_response"}
            return
        txt = r.text.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            if txt.lower().startswith("json"): txt = txt[4:]
            txt = txt.strip()
        try:
            parsed = json.loads(txt)
            new = {k:v for k,v in it.items() if k not in ("error","raw")}
            new.update(parsed)
            rows[i] = new
            counts["recovered"] += 1
            if parsed.get("is_chabad_related"):
                counts["chabad"] += 1
                counts["perps"] += len(parsed.get("perpetrator_names") or [])
        except Exception as e:
            rows[i] = {**it, "error": f"parse:{e}", "raw": txt[:500]}
            counts["still_err"] += 1

    await asyncio.gather(*[one(i) for i in err_idx])
    with F.open("w") as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"recovered={counts['recovered']} still_err={counts['still_err']} "
          f"new-chabad={counts['chabad']} new-perp-mentions={counts['perps']}")

asyncio.run(main())
