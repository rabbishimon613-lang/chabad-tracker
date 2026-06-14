"""
generate_enrichment_queries.py
--------------------------------
Outputs a JSON list of {person_id, name, query, incident_ids, existing_summary}
for the top N unenriched people in the DB.
Used to feed fleet search_batch.

Usage:
  python3 scrape/generate_enrichment_queries.py --limit 50 > data/enrichment_queue.json
"""

import sqlite3, json, pathlib, argparse

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB   = ROOT / "data/chabad.db"

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=50)
ap.add_argument("--skip-enriched", action="store_true")
args = ap.parse_args()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

q = """
SELECT
    p.id           AS person_id,
    p.full_name    AS name,
    GROUP_CONCAT(DISTINCT i.id)         AS incident_ids,
    GROUP_CONCAT(DISTINCT i.type)       AS types,
    GROUP_CONCAT(DISTINCT i.location)   AS locations,
    MAX(i.summary)                      AS sample_summary,
    MIN(i.enriched_at)                  AS first_enriched
FROM people p
JOIN incident_people ip ON ip.person_id = p.id
JOIN incidents i ON i.id = ip.incident_id
WHERE length(p.full_name) > 4
  AND p.full_name NOT IN ('Unknown','Unnamed','rabbi (unnamed)')
"""
if args.skip_enriched:
    q += " AND i.enriched_at IS NULL"
q += """
GROUP BY p.id
ORDER BY first_enriched ASC NULLS FIRST, COUNT(DISTINCT i.id) DESC
LIMIT ?
"""

rows = con.execute(q, (args.limit,)).fetchall()

out = []
for r in rows:
    primary_type = (r["types"] or "crime").split(",")[0].replace("_", " ")
    out.append({
        "person_id":   r["person_id"],
        "name":        r["name"],
        "incident_ids": [int(x) for x in r["incident_ids"].split(",")],
        "types":       r["types"] or "",
        "locations":   r["locations"] or "",
        "summary":     (r["sample_summary"] or "")[:300],
        "query":       f'"{r["name"]}" Chabad Lubavitch {primary_type}',
    })

print(json.dumps(out, ensure_ascii=False, indent=2))
