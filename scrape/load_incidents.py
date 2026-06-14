"""
Load canonical incidents into SQLite.

For each canonical incident:
  - INSERT incidents row (review_status='auto')
  - INSERT sources rows (one per source URL) + incident_sources links
  - Match perpetrator_name against people table (surname + given-name fuzz):
      hit → INSERT incident_people (role='perpetrator')
      miss → INSERT new people row (no shliach_aid) + incident_people
  - Attempt house match via chabad_affiliation → INSERT incident_houses if matched
"""
import sqlite3, json, pathlib, datetime, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB   = ROOT / "data" / "chabad.db"
SRC  = ROOT / "data" / "raw" / "canonical" / "incidents.json"

TITLES = {"rabbi","rebbe","mrs","mr","ms","miss","dr","prof","reb","r"}

def norm_name(s):
    if not s: return ""
    n = s.lower().strip()
    n = re.sub(r"[^\w\s\-]", "", n)
    parts = [p for p in n.split() if p not in TITLES]
    return " ".join(parts).strip()

def split_name(s):
    parts = [p for p in re.sub(r"[^\w\s\-]","", s.lower()).split() if p not in TITLES]
    if not parts: return ("","")
    return (parts[0], parts[-1])

def find_person(con, full):
    """Return person_id ONLY if surname AND given-name match.

    Requiring given-name agreement even when the surname is unique avoids
    false matches like Mendel Duchman (Irvine fraud) being attached to the
    different Mendel Duchman who is the UAE shliach. Better to create a new
    person row than to wrongly merge two distinct people.
    """
    first, last = split_name(full)
    if not last or len(last) < 3: return None
    if not first: return None        # surname-only is too risky
    rows = con.execute("""
        SELECT id, given_name FROM people
        WHERE LOWER(surname) = ? AND surname != ''
    """, (last,)).fetchall()
    for pid, gn in rows:
        if gn and gn.lower().startswith(first[:3]):
            return pid
    return None

def insert_person(con, full, role_text):
    first, last = split_name(full)
    cur = con.execute("""
        INSERT INTO people (full_name, given_name, surname, notes)
        VALUES (?, ?, ?, ?)
        RETURNING id
    """, (full, first.title() if first else "", last.title() if last else "",
          f"created from incident extraction (role: {role_text})"))
    return cur.fetchone()[0]

def find_house(con, affiliation):
    if not affiliation: return None
    a = affiliation.lower()
    # Try matching "Chabad of X" pattern → houses.name LIKE
    m = re.search(r"chabad\s+(?:of|in)\s+([\w\s,]+)", a)
    if m:
        loc = m.group(1).strip()[:40]
        rows = con.execute(
            "SELECT id FROM houses WHERE LOWER(name) LIKE ? LIMIT 2",
            (f"%{loc}%",)
        ).fetchall()
        if len(rows) == 1: return rows[0][0]
    return None

def insert_source(con, url, title, accessed):
    cur = con.execute("""
        INSERT INTO sources (url, type, title, accessed_at)
        VALUES (?, 'news', ?, ?)
        ON CONFLICT(url) DO UPDATE SET title=excluded.title
        RETURNING id
    """, (url, title, accessed)).fetchone()
    if cur: return cur[0]
    # No UNIQUE on sources.url? fall back to lookup
    row = con.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
    return row[0] if row else None


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    # The schema doesn't have UNIQUE on sources.url; add it transparently via index
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_url_uniq ON sources(url)")
    now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    canonicals = json.loads(SRC.read_text())
    print(f"loading {len(canonicals)} canonical incidents...")

    counts = {"incidents":0, "ip":0, "ih":0, "src":0, "new_person":0, "matched_person":0, "matched_house":0}

    for c in canonicals:
        # Insert the incident (idempotent: skip if exact (date,type,summary) already exists)
        date = c.get("date") or (str(c["year"]) if c.get("year") else None)
        summary = c.get("summary")
        existing = con.execute(
            "SELECT id FROM incidents WHERE COALESCE(occurred_on,'')=COALESCE(?,'') "
            "AND COALESCE(type,'')=COALESCE(?,'') AND COALESCE(summary,'')=COALESCE(?,'')",
            (date, c.get("incident_type"), summary)).fetchone()
        if existing:
            incident_id = existing[0]
        else:
            cur = con.execute("""
                INSERT INTO incidents (occurred_on, type, severity, location, summary, notes, review_status)
                VALUES (?, ?, ?, ?, ?, ?, 'auto')
                RETURNING id
            """, (date, c.get("incident_type"), c.get("severity"),
                  c.get("location"),
                  summary,
                  json.dumps({
                      "chabad_affiliation": c.get("chabad_affiliation"),
                      "victims_count": c.get("victims_count"),
                      "international_law_flag": c.get("international_law_flag"),
                      "cluster_size": c.get("cluster_size"),
                      "incident_type_raw": c.get("incident_type_raw"),
                  })))
            incident_id = cur.fetchone()[0]
            counts["incidents"] += 1

        # Sources
        for s in (c.get("sources") or []):
            sid = insert_source(con, s["url"], s.get("title",""), now)
            if sid:
                con.execute("INSERT OR IGNORE INTO incident_sources (incident_id, source_id) VALUES (?,?)",
                            (incident_id, sid))
                counts["src"] += 1

        # Perpetrator → person link
        perp = (c.get("perpetrator_name") or "").strip()
        if perp:
            pid = find_person(con, perp)
            if pid:
                counts["matched_person"] += 1
            else:
                pid = insert_person(con, perp, c.get("perpetrator_role") or "perpetrator")
                counts["new_person"] += 1
            con.execute("""
                INSERT OR IGNORE INTO incident_people (incident_id, person_id, role)
                VALUES (?, ?, 'perpetrator')
            """, (incident_id, pid))
            counts["ip"] += 1

        # House link via affiliation
        hid = find_house(con, c.get("chabad_affiliation"))
        if hid:
            con.execute("""
                INSERT OR IGNORE INTO incident_houses (incident_id, house_id, relation)
                VALUES (?, ?, 'affiliated')
            """, (incident_id, hid))
            counts["ih"] += 1
            counts["matched_house"] += 1

    con.commit()
    print(f"done. {counts}")
    distinct_perps = con.execute("SELECT COUNT(DISTINCT person_id) FROM incident_people").fetchone()[0]
    print(f"distinct perpetrators (people rows): {distinct_perps}")
    con.close()

if __name__ == "__main__":
    main()
