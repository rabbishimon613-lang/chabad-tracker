"""
Sweep existing incidents and remove any where Chabad is the VICTIM (not perpetrator).

For each incident summary → worker_uncensored returns {is_chabad_perpetrator: bool, reason: str}.
If false, delete the incident + linked rows.

Doctrine reference: project_chabad_tracker_doctrine.md
"""
import asyncio, json, pathlib, sqlite3, sys

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
from dotenv import load_dotenv
load_dotenv(FLEET / ".env")
from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB   = ROOT / "data" / "chabad.db"

PROMPT = """You are checking whether an incident belongs in a database tracking Chabad-Lubavitch as the PERPETRATOR of crimes / abuse / fraud / cover-ups / settler violence.

INCIDENT:
  Type: {type}
  Severity: {severity}
  Location: {location}
  Perpetrator (extracted): {perp}
  Summary: {summary}

RULES:
- KEEP if the named Chabad-affiliated person/institution is the actor (abuser, fraudster, cover-up artist, attacker).
- REMOVE if Chabad is the victim — attacked, robbed, kidnapped, or murdered by outside parties; antisemitic violence; Chabad as plaintiff suing for harm done TO them.
- KEEP cover-ups even if the underlying actor differs (institutional shielding = Chabad as perpetrator of obstruction).
- KEEP shlichus disputes (internal civil suits where both sides are Chabad — both perpetrators of escalation).
- If ambiguous, prefer REMOVE.

Output ONLY this JSON, no preamble:
{{"keep": true|false, "reason": "one short sentence"}}"""


async def main():
    providers = build_providers()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    rows = con.execute("""
        SELECT i.id, i.type, i.severity, i.location, i.summary,
               (SELECT p.full_name FROM incident_people ip JOIN people p ON p.id=ip.person_id
                WHERE ip.incident_id=i.id AND ip.role='perpetrator' LIMIT 1) AS perp
        FROM incidents i
    """).fetchall()
    print(f"reviewing {len(rows)} incidents...")

    sem = asyncio.Semaphore(6)
    decisions = []

    async def one(r):
        p = PROMPT.format(type=r["type"] or "", severity=r["severity"] or "",
                          location=r["location"] or "", perp=r["perp"] or "unknown",
                          summary=r["summary"] or "")
        async with sem:
            res = await dispatch_role("uncensored", p, max_tokens=200, providers=providers)
        if not res.ok or not (res.text or "").strip():
            decisions.append((r["id"], True, f"keep (no decision: {res.error})"))
            return
        txt = res.text.strip()
        if txt.startswith("```"):
            import re
            txt = re.sub(r"^```(?:json)?\s*","",txt); txt = re.sub(r"\s*```\s*$","",txt)
        try:
            d = json.loads(txt)
            decisions.append((r["id"], bool(d.get("keep", True)), d.get("reason","")))
        except Exception as e:
            decisions.append((r["id"], True, f"keep (parse error: {e})"))

    await asyncio.gather(*[one(r) for r in rows])

    to_remove = [(i,reason) for i,keep,reason in decisions if not keep]
    print(f"removing {len(to_remove)} incidents (Chabad-as-victim):")
    for iid, reason in to_remove:
        # show what we're removing for verification
        row = con.execute(
            "SELECT type, severity, location, substr(summary,1,120) AS s FROM incidents WHERE id=?",
            (iid,)
        ).fetchone()
        print(f"  [{iid}] {row['type']:15s} {row['location'] or '':30s} | {reason}")
        print(f"        \"{row['s']}\"")
        con.execute("DELETE FROM incident_people   WHERE incident_id=?", (iid,))
        con.execute("DELETE FROM incident_houses   WHERE incident_id=?", (iid,))
        con.execute("DELETE FROM incident_sources  WHERE incident_id=?", (iid,))
        con.execute("DELETE FROM incidents         WHERE id=?",          (iid,))

    con.commit()
    remaining = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    print(f"\nincidents remaining: {remaining}")
    con.close()

asyncio.run(main())
