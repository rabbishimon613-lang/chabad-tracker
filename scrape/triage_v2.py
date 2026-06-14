"""
Multi-bucket triage. Reads every data/raw/searches/bucket_*/ directory,
plus JCW profiles, dedupes URLs against prior triage, fleet-classifies the rest.
Appends to data/raw/triage/triage.jsonl.
"""
import asyncio, json, pathlib, sys, glob

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
import os as _os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); _os.environ.setdefault(k,v.strip('"').strip("'"))
from providers import build_providers
from roles import dispatch_role

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
- Chabad as PERPETRATOR only. If Chabad is the victim of an outside attack (e.g. Holtzberg Mumbai, Kogan UAE, Poway shooting victim), set is_chabad_related=false.
- If the article isn't about Chabad/Lubavitch at all, set is_chabad_related=false.
- Be conservative. If the snippet is too thin to judge, use "unclear" and confidence "low".
- Return ONLY the JSON object, nothing else."""


def load_already_triaged():
    seen = set()
    if OUT_FILE.exists():
        for line in OUT_FILE.open():
            try:
                seen.add(json.loads(line)["url"])
            except Exception:
                pass
    return seen


def load_urls(already):
    items, seen = [], set(already)
    # Search buckets
    for f in sorted(glob.glob(str(ROOT / "data/raw/searches/bucket_*/*.json"))):
        try:
            d = json.loads(open(f).read())
        except Exception:
            continue
        results = d.get("results") or []
        if not isinstance(results, list):
            continue
        for r in results:
            if not isinstance(r, dict): continue
            u = (r.get("url") or "").strip()
            if not u or u in seen: continue
            seen.add(u)
            items.append({
                "url": u,
                "title": (r.get("title") or "")[:200],
                "snippet": (r.get("snippet") or r.get("raw_content") or "")[:600],
                "_source": pathlib.Path(f).parent.name,
            })
    # JCW profiles as pseudo-search-results
    for f in sorted(glob.glob(str(ROOT / "data/raw/jcw/profiles/*.json"))):
        try:
            d = json.loads(open(f).read())
        except Exception:
            continue
        u = d.get("url","").strip()
        if not u or u in seen: continue
        seen.add(u)
        items.append({
            "url": u,
            "title": d.get("title","")[:200],
            "snippet": (d.get("text") or "")[:600],
            "_source": "jcw",
        })
    return items


async def main():
    providers = build_providers()
    already = load_already_triaged()
    items = load_urls(already)
    print(f"already triaged: {len(already)} | new URLs to triage: {len(items)}")
    if not items:
        return

    sem = asyncio.Semaphore(10)
    counts = {"ok":0, "err":0, "chabad":0, "perps":0}
    out_f = OUT_FILE.open("a")

    async def one(it):
        async with sem:
            p = PROMPT.format(title=it["title"], url=it["url"], snippet=it["snippet"])
            r = await dispatch_role("uncensored", p, max_tokens=400, providers=providers)
        rec = dict(it)
        if not r.ok or not r.text:
            counts["err"] += 1
            rec["error"] = r.error or "empty_response"
            return rec
        txt = r.text.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            if txt.lower().startswith("json"): txt = txt[4:]
            txt = txt.strip()
        # Some models prepend stuff; try to find first { ... last }
        try:
            parsed = json.loads(txt)
        except Exception:
            try:
                s = txt.index("{"); e = txt.rindex("}")
                parsed = json.loads(txt[s:e+1])
            except Exception as e:
                rec["error"] = f"parse:{e}"; rec["raw"] = txt[:300]
                counts["err"] += 1
                return rec
        rec.update(parsed)
        counts["ok"] += 1
        if parsed.get("is_chabad_related"):
            counts["chabad"] += 1
            counts["perps"] += len(parsed.get("perpetrator_names") or [])
        return rec

    done = 0
    tasks = [one(it) for it in items]
    for coro in asyncio.as_completed(tasks):
        r = await coro
        out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
        out_f.flush()
        done += 1
        if done % 50 == 0:
            print(f"  [{done}/{len(items)}] ok={counts['ok']} chabad={counts['chabad']} err={counts['err']}")

    print(f"\ndone. ok={counts['ok']} err={counts['err']} chabad-related={counts['chabad']} perp-mentions={counts['perps']}")

asyncio.run(main())
