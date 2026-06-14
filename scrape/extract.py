"""
Step B: deep-extract each article via worker_uncensored.
Multi-task prompt → incidents + all_entities + missing_info + follow_up_searches in one call.

Reads:  data/raw/articles/*.txt + *.meta.json
Writes: data/raw/extracted/{hash}.json
"""
import asyncio, json, pathlib, sys, re

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
from dotenv import load_dotenv
load_dotenv(FLEET / ".env")
from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path(__file__).resolve().parent.parent
ART  = ROOT / "data" / "raw" / "articles"
OUT  = ROOT / "data" / "raw" / "extracted"
OUT.mkdir(parents=True, exist_ok=True)

PROMPT = """Extract structured records from this article for a database tracking Chabad-Lubavitch as the PERPETRATOR of misdeeds (sex crimes, fraud, abuse, cover-ups, settler violence, etc.). Output ONLY valid JSON, no preamble, no markdown.

CRITICAL DOCTRINE — only include incidents where a Chabad-affiliated person or institution is the ACTOR/PERPETRATOR:
- Chabad-affiliated = shliach, shlucha, rabbi at a Chabad institution, director/staff of a Chabad organization, lay leader of Chabad, a known Chabad family member (e.g. Rubashkin family, Cunin family, Krinsky, Shemtov, Holtzberg, Lazar), donor materially tied to Chabad, employee of a Chabad institution (e.g. security guard, teacher at a Chabad yeshiva).
- EXCLUDE if the named Chabad person is the VICTIM — attacked, robbed, kidnapped, murdered by outsiders; antisemitic violence; Chabad as plaintiff suing for harm done TO Chabad. Examples to skip: Mumbai 2008 (Holtzberg killed), Poway 2019 shooting (Goldstein injured — but his earlier fraud IS in scope), UAE Tzvi Kogan murder 2024.
- INCLUDE cover-ups / institutional shielding by Chabad leadership (perpetration of obstruction even if the underlying actor is a different abuser).
- INCLUDE shlichus disputes (internal civil suits — both sides Chabad).
- When ambiguous, EXCLUDE.

ARTICLE URL: {url}
ARTICLE TITLE: {title}

ARTICLE TEXT:
{text}

OUTPUT SCHEMA:
{{
  "incidents": [
    {{
      "perpetrator_name": "Full Name as written in article",
      "perpetrator_role": "e.g. Rabbi, Shliach, Co-director, Donor, Family member of X, Lay leader",
      "chabad_affiliation": "Specific Chabad house / institution / family",
      "location": "City, Region, Country",
      "year": YYYY integer or null,
      "date": "YYYY-MM-DD or YYYY-MM or YYYY",
      "incident_type": "csa | sexual_abuse | sexual_assault | financial_fraud | embezzlement | tax_evasion | deed_theft | real_estate_fraud | trafficking_persons | trafficking_drugs | murder | assault | domestic_violence | cover_up | obstruction | settler_violence | illegal_settlement | money_laundering | bribery | corruption | shlichus_dispute | other",
      "severity": "allegation | investigation | charged | indicted | convicted | settled | acquitted | dismissed",
      "summary": "2-4 sentences, neutral wire-service tone, facts only",
      "victims_count": "number or 'unknown' or 'multiple'",
      "international_law_flag": true|false
    }}
  ],
  "all_entities": [
    {{"name": "Full Name", "role_in_article": "perpetrator|co_defendant|accomplice|victim|witness|family_member|institutional_responder|judge|lawyer|other", "chabad_link": "shliach|family_of_shliach|donor|community|none|unclear"}}
  ],
  "missing_info": ["specific factual questions left open by the article"],
  "follow_up_searches": ["specific search queries that would fill the gaps"]
}}

Rules:
- If the article is NOT about Chabad-Lubavitch in any way, return {{"incidents":[],"all_entities":[],"missing_info":[],"follow_up_searches":[]}}.
- One article may contain multiple distinct incidents — return them all.
- perpetrator_name is who did the act. Lay leaders, donors, family members count if they are the accused.
- ALL named persons relevant to the case go in all_entities, with their role and Chabad linkage.
- Neutral tone. Allegation ≠ conviction; flag severity accurately.
- Return ONLY the JSON object."""

MAX_CHARS = 14000   # ~3.5k tokens, well under any model's context

def load_articles():
    items = []
    for txt_path in sorted(ART.glob("*.txt")):
        h = txt_path.stem
        meta_path = ART / f"{h}.meta.json"
        if not meta_path.exists(): continue
        meta = json.loads(meta_path.read_text())
        if meta.get("status") != 200: continue
        text = txt_path.read_text()
        if len(text) < 200: continue
        items.append({
            "hash": h,
            "url": meta.get("url",""),
            "title": meta.get("title",""),
            "text": text[:MAX_CHARS],
        })
    return items


async def main():
    providers = build_providers()
    items = load_articles()
    todo = [it for it in items if not (OUT / f"{it['hash']}.json").exists()]
    print(f"articles: {len(items)} | to extract: {len(todo)}")

    sem = asyncio.Semaphore(6)
    counts = {"ok":0, "err":0, "incidents":0, "entities":0}

    async def one(it):
        async with sem:
            p = PROMPT.format(url=it["url"], title=it["title"], text=it["text"])
            r = await dispatch_role("uncensored", p, max_tokens=2500, providers=providers)
        out_file = OUT / f"{it['hash']}.json"
        if not r.ok or not (r.text or "").strip():
            counts["err"] += 1
            out_file.write_text(json.dumps({"_url": it["url"], "_error": r.error or "empty"}))
            return
        txt = r.text.strip()
        # strip fences if present
        if txt.startswith("```"):
            txt = re.sub(r"^```(?:json)?\s*", "", txt)
            txt = re.sub(r"\s*```\s*$", "", txt)
        try:
            parsed = json.loads(txt)
        except Exception as e:
            counts["err"] += 1
            out_file.write_text(json.dumps({"_url": it["url"], "_error": f"parse:{e}", "_raw": txt[:1000]}))
            return
        parsed["_url"]   = it["url"]
        parsed["_title"] = it["title"]
        parsed["_hash"]  = it["hash"]
        out_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
        counts["ok"] += 1
        counts["incidents"] += len(parsed.get("incidents") or [])
        counts["entities"]  += len(parsed.get("all_entities") or [])

    await asyncio.gather(*[one(it) for it in todo])
    print(f"\ndone. ok={counts['ok']} err={counts['err']} "
          f"incidents={counts['incidents']} entities={counts['entities']}")
    print(f"-> {OUT}")

asyncio.run(main())
