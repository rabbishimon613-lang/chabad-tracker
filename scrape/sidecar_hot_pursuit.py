"""
sidecar_hot_pursuit.py
-----------------------
After each dragnet cycle, finds newly discovered people/institutions
and injects them at the FRONT of the dragnet queue for immediate searching.

"Hot pursuit" — new leads don't wait 33 cycles, they get searched next cycle.

Reads:  data/dragnet_next_queries.json  (from dragnet_expand_sources.py)
        data/dragnet_state.json
        data/dragnet_people.tsv
Writes: data/dragnet_hot_queue.json  (injected at front of next cycle)
"""
import json, pathlib, sqlite3, datetime

ROOT  = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB    = ROOT / "data/chabad.db"
STATE = ROOT / "data/dragnet_state.json"
HOT   = ROOT / "data/dragnet_hot_queue.json"
NEXT  = ROOT / "data/dragnet_next_queries.json"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = datetime.datetime.utcnow().isoformat()

hot_queue = json.loads(HOT.read_text()) if HOT.exists() else []
next_q    = json.loads(NEXT.read_text()) if NEXT.exists() else {}

new_hot = []

# From newly found co-conspirators
for name in (next_q.get("new_people") or []):
    if not name or len(name.split()) < 2: continue
    # Check if already in people table with incidents
    row = con.execute(
        "SELECT p.id, p.full_name, GROUP_CONCAT(DISTINCT i.type) as types FROM people p "
        "LEFT JOIN incident_people ip ON ip.person_id=p.id "
        "LEFT JOIN incidents i ON i.id=ip.incident_id "
        "WHERE p.full_name LIKE ? GROUP BY p.id LIMIT 1",
        (f"%{name.split()[-1]}%",)
    ).fetchone()

    entry = {
        "id": row["id"] if row else None,
        "name": row["full_name"] if row else name,
        "types": row["types"] if row else "other",
        "hot": True,
        "reason": f"co-conspirator discovered {now[:10]}",
        "query": f'"{name}" Chabad Lubavitch crime fraud convicted',
    }
    if entry not in hot_queue:
        new_hot.append(entry)
        print(f"  HOT: {name} (co-conspirator)")

# From newly found institutions
for inst in (next_q.get("new_institutions") or []):
    if not inst: continue
    # Find people at this institution
    people_at_inst = con.execute("""
        SELECT p.id, p.full_name, GROUP_CONCAT(DISTINCT i.type) as types
        FROM people p
        JOIN house_roles hr ON hr.person_id=p.id
        JOIN houses h ON h.id=hr.house_id
        LEFT JOIN incident_people ip ON ip.person_id=p.id
        LEFT JOIN incidents i ON i.id=ip.incident_id
        WHERE h.name LIKE ?
        GROUP BY p.id
        HAVING COUNT(DISTINCT i.id) > 0
        LIMIT 5
    """, (f"%{inst[:30]}%",)).fetchall()

    for p in people_at_inst:
        entry = {
            "id": p["id"],
            "name": p["full_name"],
            "types": p["types"] or "other",
            "hot": True,
            "reason": f"institution {inst} flagged {now[:10]}",
            "query": f'"{p["full_name"]}" "{inst}" crime fraud convicted',
        }
        if entry not in hot_queue:
            new_hot.append(entry)
            print(f"  HOT: {p['full_name']} (at flagged institution: {inst})")

# From high-severity recent incidents that have few sources
sparse_high = con.execute("""
    SELECT p.id, p.full_name, GROUP_CONCAT(DISTINCT i.type) as types
    FROM people p
    JOIN incident_people ip ON ip.person_id=p.id
    JOIN incidents i ON i.id=ip.incident_id
    WHERE i.severity IN ('convicted','indicted')
      AND i.id NOT IN (SELECT incident_id FROM incident_sources)
      AND i.enriched_at IS NULL
    GROUP BY p.id
    LIMIT 10
""").fetchall()

for p in sparse_high:
    entry = {
        "id": p["id"],
        "name": p["full_name"],
        "types": p["types"] or "other",
        "hot": True,
        "reason": "high severity but no sources",
        "query": f'"{p["full_name"]}" Chabad convicted sentenced court documents',
    }
    if entry not in hot_queue:
        new_hot.append(entry)
        print(f"  HOT: {p['full_name']} (high severity, no sources)")

# Prepend new hot entries to queue
hot_queue = new_hot + [h for h in hot_queue if h not in new_hot]
hot_queue = hot_queue[:50]  # cap at 50

HOT.write_text(json.dumps(hot_queue, indent=2, ensure_ascii=False))
print(f"\nHot queue: {len(hot_queue)} entries ({len(new_hot)} new)")
print(f"Next cycle will prioritize: {[h['name'] for h in hot_queue[:3]]}")
