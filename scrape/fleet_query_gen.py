"""
Use the fleet to GENERATE new search queries by reading the current incident list
and asking 'what cases haven't we covered yet?'. Outputs to data/raw/fleet_queries.json
"""
import asyncio, json, sqlite3, sys, pathlib
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet"); sys.path.insert(0, str(FLEET))
import os
for line in open(FLEET / ".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")

def covered_summary():
    conn = sqlite3.connect(ROOT/"data/chabad.db")
    rows = conn.execute("""SELECT p.full_name, i.type, i.occurred_on, i.location
                           FROM incidents i
                           LEFT JOIN incident_people ip ON ip.incident_id=i.id
                           LEFT JOIN people p ON p.id=ip.person_id
                           ORDER BY i.occurred_on DESC LIMIT 200""").fetchall()
    return "\n".join(f"- {r[0]} | {r[1]} | {r[2]} | {r[3]}" for r in rows)

PROMPT = """You are helping enrich a database of Chabad-Lubavitch misdeeds (the network as PERPETRATOR — crimes, abuse, fraud, cover-ups, settler violence). Chabad as VICTIM is out of scope.

These are cases we ALREADY have:
{covered}

Generate 80 NEW, SPECIFIC search queries (one per line, no numbering, no quotes around the whole line) likely to surface cases we DON'T have. Mix:
- specific Chabad rabbis you know were involved in legal trouble (full names)
- specific Chabad institutions (yeshivas, camps, summer programs, kollels) with abuse/fraud history
- specific years × jurisdictions where Chabad litigation was filed
- secondary characters mentioned by name in known cases
- mosdos board members named in financial scandals
- internal Chabad civil suits (shlichus disputes, mosdos infighting)
- settler violence by Chabad-affiliated individuals in West Bank
- specific historical incidents (any decade 1980s-2020s)

Each query should be ~6-12 words, mixing a NAME or INSTITUTION with crime/legal keywords (lawsuit, arrested, indicted, convicted, abuse, fraud, etc).

Output: just the queries, one per line. No preamble, no markdown."""

async def main():
    providers = build_providers()
    covered = covered_summary()
    p = PROMPT.format(covered=covered)
    # Try uncensored chain first; fall back to fast
    for role in ("uncensored","reasoning","fast"):
        r = await dispatch_role(role, p, max_tokens=4000, providers=providers)
        if r.ok and (r.text or "").strip():
            print(f"used role: {role}")
            break
    if not r.ok:
        print("all roles failed:", r.error); return
    queries = [l.strip().strip("-•").strip() for l in r.text.splitlines() if l.strip() and len(l.strip())>10]
    queries = [q for q in queries if not q.startswith(("Here","Output","#","```","Note"))]
    print(f"generated {len(queries)} queries")
    out = ROOT/"data/raw/fleet_queries.json"
    out.write_text(json.dumps(queries, indent=2))
    print(out)

asyncio.run(main())
