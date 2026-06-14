# Dragnet Agent Cycle — Self-Contained Instructions

You are running one autonomous dragnet cycle for the Chabad criminal tracker database.
ROOT = /Volumes/EOS_DIGITAL/chabad-tracker
All work happens there. NEVER read large files into context — always slice with python.

## HARD RULES
- Never read any file >200 lines into context directly
- Never read the SQLite DB into context
- Always slice search results with python (600 chars max per result)
- If any step fails, log the error, skip it, continue to next step
- Total goal: find and insert real named Chabad/Lubavitch perpetrators into the DB

## STEP 1 — Run prep phase (builds all queries)
```
cd /Volumes/EOS_DIGITAL/chabad-tracker
python3 scrape/dragnet_agent_cycle.py --phase prep --batch-size 20 --broad-per-cycle 10 --stub-per-cycle 8
```
This writes `data/agent_cycle_input.json`. Read ONLY the query list with:
```
python3 -c "
import json
d = json.load(open('data/agent_cycle_input.json'))
queries = [q['query'] for q in d['all_queries']]
print(f'Total queries: {len(queries)}')
print(json.dumps(queries))
"
```

## STEP 2 — Fire ALL queries in ONE search_batch call
Use the queries list from Step 1.
- Tier A (first 20): engine=exa, include_content=true, max_results=5
- Tier B+C (remaining): engine=tavily, include_content=true, max_results=5
Fire them ALL in a single search_batch call. The result will be saved to a file.
Save that file path for Step 3.

## STEP 3 — Slice results with Python (NEVER read full result file)
```python
python3 << 'PYEOF'
import json, pathlib

RESULT_FILE = "<path_from_step2>"
INPUT_FILE  = "data/agent_cycle_input.json"

data   = json.load(open(RESULT_FILE))["result"]
inp    = json.load(open(INPUT_FILE))
people = {p["id"]: p for p in inp["people_batch"]}
pmeta  = inp.get("people_meta", {})
queries = inp["all_queries"]

tier_a_prompts = []
tier_bc_prompts = []

for i, qr in enumerate(data):
    hits = qr.get("results", [])
    q_meta = queries[i] if i < len(queries) else {}
    tier = q_meta.get("tier","B")

    # Build 600-char snippet
    snippets = []
    for r in hits[:4]:
        url = r.get("url","")
        body = (r.get("text") or r.get("content") or r.get("snippet",""))[:300]
        snippets.append(f"URL:{url}\n{body}")
    combined = "\n---\n".join(snippets)[:600]

    if tier == "A":
        pid   = q_meta.get("person_id")
        name  = q_meta.get("person_name","")
        meta  = pmeta.get(str(pid), {})
        types = meta.get("types","other")
        loc   = meta.get("location","")
        known = "; ".join(f"{x['type']}({x['severity']})" for x in meta.get("known_incidents",[])[:2])
        prompt = f"""Person: {name}. Types: {types}. Location: {loc}. Known: {known}.
Search results:
{combined}

Return JSON only:
{{"details":"3-5 sentence narrative of their crimes/outcome","severity":"convicted|indicted|charged|settled|investigation|allegation","new_sources":["url"],"co_conspirators":["Full Name"],"new_cases":[{{"perpetrator_name":"Full Name","summary":"2-4 sentences","type":"financial_fraud|sexual_abuse|cover_up|money_laundering|tax_evasion|drug_trafficking|immigration_fraud|assault|other","severity":"convicted|indicted|charged|settled|investigation|allegation","year":2024,"location":"City, Country","entity":"institution","source_url":"url","amount_usd":null,"prison_years":null}}]}}
If no new info: {{"details":"","severity":"","new_sources":[],"co_conspirators":[],"new_cases":[]}}"""
        tier_a_prompts.append({"person_id": pid, "name": name, "prompt": prompt})
    else:
        label = q_meta.get("label","broad")
        if not combined.strip(): continue
        prompt = f"""Search results for: {q_meta.get('query','')}
{combined}

Extract Chabad/Lubavitch perpetrator cases. Return JSON only:
{{"new_cases":[{{"perpetrator_name":"Full Name (skip generics like 'a rabbi')","summary":"2-4 sentences","type":"financial_fraud|sexual_abuse|cover_up|money_laundering|tax_evasion|drug_trafficking|immigration_fraud|assault|other","severity":"convicted|indicted|charged|settled|investigation|allegation","year":2024,"location":"City, Country","entity":"institution","source_url":"url","amount_usd":null,"prison_years":null}}]}}
Skip: victims of antisemitism, people acquitted/cleared, non-Chabad, unnamed perpetrators.
If none: {{"new_cases":[]}}"""
        tier_bc_prompts.append({"label": label, "prompt": prompt})

all_prompts = [x["prompt"] for x in tier_a_prompts] + [x["prompt"] for x in tier_bc_prompts]
meta_order  = [{"tier":"A","person_id":x["person_id"],"name":x["name"]} for x in tier_a_prompts] + \
              [{"tier":"BC","label":x["label"]} for x in tier_bc_prompts]

pathlib.Path("data/agent_prompts_meta.json").write_text(json.dumps(meta_order, indent=2))
pathlib.Path("data/agent_prompts_list.json").write_text(json.dumps(all_prompts, indent=2))
print(f"Built {len(tier_a_prompts)} Tier-A + {len(tier_bc_prompts)} Tier-BC = {len(all_prompts)} fleet prompts")
PYEOF
```

## STEP 4 — Fire ALL fleet prompts in ONE fleet_batch call
Read the prompts list:
```
python3 -c "import json; p=json.load(open('data/agent_prompts_list.json')); print(f'{len(p)} prompts')"
```
Call fleet_batch with ALL prompts, role="fast", max_tokens=500.
The result will be large — save it to a file.

## STEP 5 — Parse fleet results and write to DB
```python
python3 << 'PYEOF'
import json, pathlib, re

FLEET_FILE = "<path_from_step4>"
META_FILE  = "data/agent_prompts_meta.json"

fleet_raw = json.load(open(FLEET_FILE))["result"]
meta      = json.load(open(META_FILE))

output = {"tier_a": [], "tier_bc": []}

for i, raw in enumerate(fleet_raw):
    m = meta[i] if i < len(meta) else {}
    # Parse JSON from fleet response (may have markdown fences)
    text = raw if isinstance(raw, str) else json.dumps(raw)
    text = re.sub(r'^```json\s*', '', text.strip())
    text = re.sub(r'```$', '', text.strip())
    try:
        parsed = json.loads(text)
    except:
        try:
            # Find first { to last }
            start = text.index('{')
            end   = text.rindex('}') + 1
            parsed = json.loads(text[start:end])
        except:
            parsed = {}

    if m.get("tier") == "A":
        output["tier_a"].append({"person_id": m["person_id"], "name": m["name"], "fleet_result": parsed})
    else:
        output["tier_bc"].append({"label": m.get("label",""), "fleet_result": parsed})

pathlib.Path("data/agent_fleet_results.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
print(f"Parsed: {len(output['tier_a'])} Tier-A, {len(output['tier_bc'])} Tier-BC")
PYEOF
```

## STEP 6 — Apply results to DB
```
python3 scrape/dragnet_agent_cycle.py --phase apply --results data/agent_fleet_results.json
```

## STEP 7 — Run post-phase sidecars
```
python3 scrape/sidecar_extract_numbers.py
python3 scrape/sidecar_stub_resolver.py --tier 1
python3 scrape/sidecar_doj_rss.py
```

## STEP 8 — Return summary (ONE LINE back to parent)
```
python3 scrape/dragnet_agent_cycle.py --phase summary
```
Return ONLY that one line to the parent session. Nothing else.
