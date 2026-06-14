"""
Layer 3a: compute house badness from incidents.

Two paths an incident reaches a house:
  (1) DIRECT      — incident_houses.house_id
  (2) INDIRECT    — incident_people.person_id  →  house_roles.house_id  (the person currently/historically holds a role at that house)

We dedupe (incident_id, house_id) pairs across both paths so a single
incident only counts once per house.

Severity weights:
  allegation     = 1
  investigation  = 2
  settled        = 4
  charged        = 5
  indicted       = 6
  convicted      = 10
  acquitted      = 0
  dismissed      = 0
  unclear/other  = 1

Color bands (for the future map):
  0            = black   (no incidents)
  1–4          = yellow  (allegation-grade signal)
  5–14         = orange  (formal charges / one conviction)
  15+          = red     (heavy / multiple)
"""
import sqlite3, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB   = ROOT / "data" / "chabad.db"

SEV_WEIGHTS = {
    "allegation":    1,
    "investigation": 2,
    "settled":       4,
    "charged":       5,
    "indicted":      6,
    "convicted":     10,
    "acquitted":     0,
    "dismissed":     0,
}

def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")

    # Add columns if missing (idempotent)
    cols = {r[1] for r in con.execute("PRAGMA table_info(houses)").fetchall()}
    if "severity_score" not in cols:
        con.execute("ALTER TABLE houses ADD COLUMN severity_score INTEGER DEFAULT 0")
    if "incident_count" not in cols:
        con.execute("ALTER TABLE houses ADD COLUMN incident_count INTEGER DEFAULT 0")
    if "color_band" not in cols:
        con.execute("ALTER TABLE houses ADD COLUMN color_band TEXT DEFAULT 'black'")

    # Build the unified (incident, house) pair set in a temp table
    con.execute("DROP TABLE IF EXISTS _ih_pairs")
    con.execute("""
        CREATE TEMP TABLE _ih_pairs AS
        -- Path 1: direct
        SELECT DISTINCT incident_id, house_id
          FROM incident_houses
        UNION
        -- Path 2: via personnel
        SELECT DISTINCT ip.incident_id, hr.house_id
          FROM incident_people ip
          JOIN house_roles hr ON hr.person_id = ip.person_id
    """)

    # Aggregate weighted score per house
    sev_case = " ".join(f"WHEN '{k}' THEN {v}" for k, v in SEV_WEIGHTS.items())
    con.execute(f"""
        UPDATE houses
        SET severity_score = COALESCE((
              SELECT SUM(
                CASE i.severity {sev_case} ELSE 1 END
              )
              FROM _ih_pairs p
              JOIN incidents i ON i.id = p.incident_id
              WHERE p.house_id = houses.id
            ), 0),
            incident_count = COALESCE((
              SELECT COUNT(*) FROM _ih_pairs p WHERE p.house_id = houses.id
            ), 0)
    """)

    # Color bands
    con.execute("""
        UPDATE houses SET color_band = CASE
            WHEN severity_score = 0 THEN 'black'
            WHEN severity_score < 5 THEN 'yellow'
            WHEN severity_score < 15 THEN 'orange'
            ELSE 'red'
        END
    """)

    con.commit()

    # Report
    print("color_band distribution:")
    for band, n in con.execute(
        "SELECT color_band, COUNT(*) FROM houses GROUP BY color_band ORDER BY "
        "CASE color_band WHEN 'black' THEN 0 WHEN 'yellow' THEN 1 WHEN 'orange' THEN 2 ELSE 3 END"
    ):
        print(f"  {band:7s}  {n:5d}")

    print("\ntop 20 houses by severity:")
    rows = con.execute("""
        SELECT id, name, city, state, country, incident_count, severity_score, color_band
        FROM houses WHERE severity_score > 0
        ORDER BY severity_score DESC, incident_count DESC LIMIT 20
    """).fetchall()
    for r in rows:
        print(f"  [{r[7]:6s}] score={r[6]:3d}  inc={r[5]:2d}  | {r[1][:50]:50s} {r[2] or ''}, {r[3] or ''}, {r[4] or ''}")

    con.close()

if __name__ == "__main__":
    main()
