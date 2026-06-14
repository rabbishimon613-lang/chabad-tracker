"""
Layer 2 cleanup pass:
  1. Delete orphan incident_sources / incident_people / incident_houses rows
     pointing at deleted incident_ids.
  2. Backfill incident_houses from incident_people ⋈ house_roles
     (if a named perpetrator serves at a house, link that house to the incident).
  3. Report what's left.
"""
import sqlite3, pathlib
DB = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db")
c = sqlite3.connect(DB); c.execute("PRAGMA foreign_keys=OFF")

# 1. Orphan cleanup ---------------------------------------------------------
ORPHANS = [
    ("incident_sources", "incident_id"),
    ("incident_people",  "incident_id"),
    ("incident_houses",  "incident_id"),
    ("incident_people",  "person_id"),
    ("incident_houses",  "house_id"),
    ("incident_sources", "source_id"),
    ("house_roles",      "house_id"),
    ("house_roles",      "person_id"),
    ("family_relations", "person_a"),
    ("family_relations", "person_b"),
]
PARENTS = {
    "incident_id": ("incidents", "id"),
    "person_id":   ("people",    "id"),
    "person_a":    ("people",    "id"),
    "person_b":    ("people",    "id"),
    "house_id":    ("houses",    "id"),
    "source_id":   ("sources",   "id"),
}
print("--- orphan cleanup ---")
total_removed = 0
for tbl, col in ORPHANS:
    ptbl, pcol = PARENTS[col]
    try:
        before = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        c.execute(f"DELETE FROM {tbl} WHERE {col} NOT IN (SELECT {pcol} FROM {ptbl})")
        after  = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        removed = before - after
        total_removed += removed
        if removed:
            print(f"  {tbl}.{col}: removed {removed} ({before} -> {after})")
    except sqlite3.OperationalError as e:
        print(f"  {tbl}.{col}: skipped ({e})")
print(f"orphans removed: {total_removed}")

# 2. Backfill incident_houses from perp's house_roles ----------------------
print("\n--- backfill incident_houses ---")
before = c.execute("SELECT COUNT(*) FROM incident_houses").fetchone()[0]
c.execute("""
  INSERT OR IGNORE INTO incident_houses (incident_id, house_id, relation)
  SELECT DISTINCT ip.incident_id, hr.house_id, 'perpetrator_post'
  FROM incident_people ip
  JOIN house_roles hr ON hr.person_id = ip.person_id
  WHERE ip.role = 'perpetrator'
""")
after = c.execute("SELECT COUNT(*) FROM incident_houses").fetchone()[0]
print(f"  incident_houses: {before} -> {after} (+{after-before})")

# distinct houses now linked
linked = c.execute("SELECT COUNT(DISTINCT house_id) FROM incident_houses").fetchone()[0]
print(f"  distinct houses linked to incidents: {linked}")

# 3. Report --------------------------------------------------------------
print("\n--- final state ---")
rows = c.execute("""
  SELECT 'incidents', COUNT(*) FROM incidents
  UNION ALL SELECT 'sources',           COUNT(*) FROM sources
  UNION ALL SELECT 'incident_sources',  COUNT(*) FROM incident_sources
  UNION ALL SELECT 'incidents w/ ≥1 src', (SELECT COUNT(*) FROM (SELECT incident_id FROM incident_sources GROUP BY incident_id))
  UNION ALL SELECT 'incidents w/ ≥2 src', (SELECT COUNT(*) FROM (SELECT incident_id FROM incident_sources GROUP BY incident_id HAVING COUNT(*)>=2))
  UNION ALL SELECT 'incidents w/ 1 src',  (SELECT COUNT(*) FROM (SELECT incident_id FROM incident_sources GROUP BY incident_id HAVING COUNT(*)=1))
  UNION ALL SELECT 'incident_houses',    COUNT(*) FROM incident_houses
  UNION ALL SELECT 'incident_people',    COUNT(*) FROM incident_people
  UNION ALL SELECT 'family_relations',   COUNT(*) FROM family_relations
""").fetchall()
for k,v in rows:
    print(f"  {k:30s} {v}")

c.commit(); c.execute("VACUUM"); c.close()
print("\ndone")
