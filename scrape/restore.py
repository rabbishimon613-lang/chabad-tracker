"""
Restore over-removed incidents from canonical file.
Targets: Rubashkin financial fraud, David Cyprys Melbourne.
"""
import sqlite3, json, pathlib, datetime, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB   = ROOT / "data" / "chabad.db"
SRC  = ROOT / "data" / "raw" / "canonical" / "incidents.json"

TITLES = {"rabbi","rebbe","mrs","mr","ms","miss","dr","prof","reb","r"}
def split_name(s):
    parts = [p for p in re.sub(r"[^\w\s\-]","", s.lower()).split() if p not in TITLES]
    if not parts: return ("","")
    return (parts[0], parts[-1])

def find_person(con, full):
    first, last = split_name(full)
    if not last: return None
    rows = con.execute(
        "SELECT id FROM people WHERE LOWER(surname)=? AND surname!=''",(last,)).fetchall()
    if len(rows)==1: return rows[0][0]
    for (pid,) in rows:
        gn = con.execute("SELECT given_name FROM people WHERE id=?",(pid,)).fetchone()[0] or ""
        if first and gn.lower().startswith(first[:3]): return pid
    return None

def insert_person(con, full, role):
    f,l = split_name(full)
    return con.execute("""
        INSERT INTO people (full_name, given_name, surname, notes)
        VALUES (?, ?, ?, ?) RETURNING id
    """,(full, f.title(), l.title(), f"restored: role {role}")).fetchone()[0]

def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    canonicals = json.loads(SRC.read_text())
    targets = []
    for c in canonicals:
        perp = (c.get("perpetrator_name") or "").lower()
        itype = (c.get("incident_type") or "").lower()
        if "cyprys" in perp:
            targets.append(c)
        elif "rubashkin" in perp and itype in ("financial_fraud","embezzlement","money_laundering","tax_evasion"):
            targets.append(c)

    print(f"restoring {len(targets)} incidents")
    for c in targets:
        # skip if already present (idempotent on summary match)
        already = con.execute("""
            SELECT id FROM incidents
            WHERE type=? AND severity=? AND substr(summary,1,80)=substr(?,1,80)
        """,(c.get("incident_type"), c.get("severity"), c.get("summary") or "")).fetchone()
        if already:
            print(f"  already present (id={already[0]}): {c.get('perpetrator_name')} / {c.get('incident_type')}")
            continue

        date = c.get("date") or (str(c["year"]) if c.get("year") else None)
        iid = con.execute("""
            INSERT INTO incidents (occurred_on, type, severity, location, summary, notes, review_status)
            VALUES (?,?,?,?,?,?,'auto-restored') RETURNING id
        """,(date, c.get("incident_type"), c.get("severity"),
             c.get("location"), c.get("summary"),
             json.dumps({"chabad_affiliation": c.get("chabad_affiliation"),
                         "restored_from_canonical": True}))).fetchone()[0]

        for s in (c.get("sources") or []):
            sid = con.execute("""
                INSERT INTO sources (url, type, title, accessed_at)
                VALUES (?, 'news', ?, ?)
                ON CONFLICT(url) DO UPDATE SET title=excluded.title
                RETURNING id
            """,(s["url"], s.get("title",""), now)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO incident_sources VALUES (?,?)",(iid,sid))

        perp = (c.get("perpetrator_name") or "").strip()
        if perp:
            pid = find_person(con, perp) or insert_person(con, perp, c.get("perpetrator_role") or "perpetrator")
            con.execute("INSERT INTO incident_people (incident_id, person_id, role) VALUES (?, ?, 'perpetrator')",
                        (iid, pid))
        print(f"  restored id={iid}: {perp} / {c.get('incident_type')} ({c.get('severity')})")

    con.commit()
    print(f"\ntotal incidents now: {con.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]}")
    con.close()

if __name__ == "__main__":
    main()
