"""
Direct incident extraction from new bucket snippets using fleet workers.
Bypasses triage → fetch → extract pipeline, goes straight to fleet LLM extraction.
"""
import asyncio, json, pathlib, sys, os, re

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
for line in open(FLEET / ".env"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k, v.strip('"').strip("'"))

from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
CANDIDATES = json.loads((ROOT / "data/raw/triage/new_snippets.json").read_text())
OUT_FILE = ROOT / "data/raw/triage/snippet_extracts.jsonl"

PROMPT_TMPL = """Extract criminal/legal incidents for a Chabad-Lubavitch wrongdoing database.

TITLE: {title}
URL: {url}
SNIPPET: {snippet}

Output one JSON object per line for each distinct incident. Schema:
{{"name":"Full Name","type":"financial_fraud|tax_evasion|money_laundering|sexual_abuse|child_pornography|assault|cover_up|drug_trafficking|immigration_fraud|insurance_fraud|welfare_fraud|other","severity":"allegation|investigation|charged|indicted|convicted|settled","year":YYYY_or_null,"location":"City, Country or null","entity":"Chabad/Lubavitch house or org name or null","summary":"one sentence ≤120 chars"}}

Rules:
- Only include if a named individual or named Chabad entity is clearly the perpetrator
- If no clear perpetrator: output {{"skip":true}}
- Output ONLY JSON lines, zero prose"""

async def extract_one(c, sem, providers, done_urls):
    url = c["url"]
    if url in done_urls:
        return []
    prompt = PROMPT_TMPL.format(
        title=c["title"][:200],
        url=url[:200],
        snippet=c["snippet"][:600]
    )
    async with sem:
        try:
            result = await dispatch_role("fast", prompt, 400, providers)
            resp = result.text if result and result.text else ""
            lines = resp.strip().split("\n")
            results = []
            for line in lines:
                line = line.strip()
                if not line: continue
                try:
                    obj = json.loads(line)
                    if obj.get("skip"): continue
                    if not obj.get("name") and not obj.get("entity"): continue
                    obj["source_url"] = url
                    obj["source_title"] = c["title"]
                    results.append(obj)
                except: pass
            return results
        except Exception as e:
            return []

async def main():
    # Load already done URLs
    done_urls = set()
    existing = []
    if OUT_FILE.exists():
        for line in OUT_FILE.read_text().splitlines():
            try:
                obj = json.loads(line)
                done_urls.add(obj.get("source_url",""))
                existing.append(obj)
            except: pass
    print(f"Already extracted: {len(existing)} incidents from {len(done_urls)} URLs")

    providers = build_providers()
    sem = asyncio.Semaphore(6)
    tasks = [extract_one(c, sem, providers, done_urls) for c in CANDIDATES]

    all_results = existing[:]
    done = 0
    new_count = 0
    with open(OUT_FILE, "a") as f:
        for coro in asyncio.as_completed(tasks):
            results = await coro
            done += 1
            for r in results:
                f.write(json.dumps(r) + "\n")
                all_results.append(r)
                new_count += 1
            if done % 50 == 0:
                print(f"  [{done}/{len(tasks)}] new incidents so far: {new_count}")

    print(f"\nDone. Total new incidents extracted: {new_count}")
    print(f"Total in file: {len(all_results)}")

    # Summary by perpetrator
    from collections import Counter
    names = Counter(r.get("name","?") for r in all_results if not r.get("skip"))
    print("\nTop perpetrators found:")
    for name, n in names.most_common(20):
        print(f"  {n:3d}x  {name}")

asyncio.run(main())
