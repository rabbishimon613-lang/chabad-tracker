#!/usr/bin/env python3
"""
Interactive review tool for person_match_candidates.
Usage: python3 scrape/review_candidates.py

Keys: y = confirm merge  |  n = reject  |  s = skip  |  q = quit
"""
import sqlite3, json, datetime, sys, os

DB   = "/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c    = conn.cursor()
now  = datetime.datetime.utcnow().isoformat()

def apply_merge(src, tgt):
    conn.execute("PRAGMA foreign_keys=OFF")
    # Move incident_people
    for (inc_id,) in c.execute("SELECT incident_id FROM incident_people WHERE person_id=?", (src,)).fetchall():
        if c.execute("SELECT 1 FROM incident_people WHERE person_id=? AND incident_id=?", (tgt, inc_id)).fetchone():
            c.execute("DELETE FROM incident_people WHERE person_id=? AND incident_id=?", (src, inc_id))
        else:
            c.execute("UPDATE incident_people SET person_id=? WHERE person_id=? AND incident_id=?", (tgt, src, inc_id))
    # Move person_relations
    for col_s, col_o in [("person_a","person_b"),("person_b","person_a")]:
        for row in c.execute(f"SELECT id, {col_o}, rel_type FROM person_relations WHERE {col_s}=?", (src,)).fetchall():
            a = (tgt if col_s=="person_a" else row[1])
            b = (row[1] if col_s=="person_a" else tgt)
            if a > b: a,b = b,a
            if a == b: c.execute("DELETE FROM person_relations WHERE id=?", (row[0],)); continue
            if c.execute("SELECT 1 FROM person_relations WHERE person_a=? AND person_b=? AND rel_type=?", (a,b,row[2])).fetchone():
                c.execute("DELETE FROM person_relations WHERE id=?", (row[0],))
            else:
                c.execute(f"UPDATE person_relations SET {col_s}=? WHERE id=?", (tgt, row[0]))
    # Move family_members
    for row in c.execute("SELECT id, family_id FROM family_members WHERE person_id=?", (src,)).fetchall():
        if c.execute("SELECT 1 FROM family_members WHERE person_id=? AND family_id=?", (tgt, row[1])).fetchone():
            c.execute("DELETE FROM family_members WHERE id=?", (row[0],))
        else:
            c.execute("UPDATE family_members SET person_id=? WHERE id=?", (tgt, row[0]))
    # Set canonical_id
    c.execute("UPDATE people SET canonical_id=? WHERE id=?", (tgt, src))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

def get_context(pid):
    p = c.execute("SELECT id, full_name, shliach_aid, given_name, surname FROM people WHERE id=?", (pid,)).fetchone()
    incs = c.execute("""
        SELECT i.type, i.severity, substr(i.occurred_on,1,4), i.location
        FROM incidents i JOIN incident_people ip ON ip.incident_id=i.id
        WHERE ip.person_id=?""", (pid,)).fetchall()
    houses = c.execute("""
        SELECT h.name, h.city, h.country FROM houses h
        JOIN house_roles hr ON hr.house_id=h.id WHERE hr.person_id=? LIMIT 3""", (pid,)).fetchall()
    return p, incs, houses

def fmt(p, incs, houses):
    lines = []
    lines.append(f"  Name    : {p['full_name']}")
    lines.append(f"  ID      : {p['id']}  {'[in directory]' if p['shliach_aid'] else '[incident-only]'}")
    if houses:
        for h in houses:
            lines.append(f"  House   : {h[0][:55]}  ({h[1]}, {h[2]})")
    else:
        lines.append(f"  House   : (none)")
    if incs:
        for i in incs[:4]:
            lines.append(f"  Incident: {i[0]:<22s} {i[1]:<15s} {i[2] or '?':4s}  {(i[3] or '')[:30]}")
    else:
        lines.append(f"  Incident: (none)")
    return "\n".join(lines)

# ── main loop ──────────────────────────────────────────────────────────────────
pending = c.execute("""
    SELECT id, person_a, person_b, score, signals
    FROM person_match_candidates
    WHERE status='pending'
    ORDER BY score DESC, person_a
""").fetchall()

total   = len(pending)
done    = {"confirmed": 0, "rejected": 0, "skipped": 0}
seen    = set()   # dedupe pairs sharing same perp (e.g. 4x Levi Shemtov)

print(f"\n{'='*65}")
print(f"  CHABAD TRACKER — Person Match Review  ({total} pending)")
print(f"  y = confirm merge  |  n = reject  |  s = skip  |  q = quit")
print(f"{'='*65}\n")

for idx, row in enumerate(pending):
    mc_id, pa_id, pb_id, score, signals_raw = row
    signals = json.loads(signals_raw or "[]")

    # Determine which is the perp and which is the shliach master
    pa = c.execute("SELECT shliach_aid FROM people WHERE id=?", (pa_id,)).fetchone()[0]
    pb = c.execute("SELECT shliach_aid FROM people WHERE id=?", (pb_id,)).fetchone()[0]
    if pa is None and pb is not None:
        perp_id, master_id = pa_id, pb_id
    elif pb is None and pa is not None:
        perp_id, master_id = pb_id, pa_id
    else:
        perp_id, master_id = pa_id, pb_id   # both or neither in directory — lower id = master

    # Skip if we already confirmed/rejected a merge for this perp
    if perp_id in seen:
        c.execute("UPDATE person_match_candidates SET status='skipped', reviewed_at=? WHERE id=?", (now, mc_id))
        conn.commit()
        done["skipped"] += 1
        continue

    p_perp,   incs_perp,   houses_perp   = get_context(perp_id)
    p_master, incs_master, houses_master = get_context(master_id)

    if p_perp is None or p_master is None:
        continue

    print(f"[{idx+1}/{total}]  score={score:.2f}  signals={signals}")
    print(f"\n── INCIDENT ROW {'(no incidents)' if not incs_perp else ''}")
    print(fmt(p_perp, incs_perp, houses_perp))
    print(f"\n── DIRECTORY ROW")
    print(fmt(p_master, incs_master, houses_master))
    print()

    while True:
        try:
            key = input("  Same person? [y/n/s/q] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            key = "q"

        if key == "q":
            print(f"\nQuitting. Confirmed={done['confirmed']} Rejected={done['rejected']} Skipped={done['skipped']}")
            sys.exit(0)
        elif key == "y":
            apply_merge(perp_id, master_id)
            c.execute("UPDATE person_match_candidates SET status='confirmed', reviewed_at=?, reviewer='manual' WHERE id=?", (now, mc_id))
            conn.commit()
            done["confirmed"] += 1
            seen.add(perp_id)
            print(f"  ✓ Merged {perp_id} → {master_id}\n")
            break
        elif key == "n":
            c.execute("UPDATE person_match_candidates SET status='rejected', reviewed_at=?, reviewer='manual' WHERE id=?", (now, mc_id))
            conn.commit()
            done["rejected"] += 1
            seen.add(perp_id)
            print(f"  ✗ Rejected\n")
            break
        elif key == "s":
            done["skipped"] += 1
            print(f"  → Skipped\n")
            break
        else:
            print("  Please enter y, n, s, or q")

print(f"\n{'='*65}")
print(f"  DONE — Confirmed={done['confirmed']}  Rejected={done['rejected']}  Skipped={done['skipped']}")
print(f"{'='*65}\n")
