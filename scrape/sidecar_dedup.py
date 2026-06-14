"""
sidecar_dedup.py
-----------------
Finds near-duplicate incidents and merges them.
Duplicates = same person + summary overlap > 80% OR same summary first 60 chars.

Keeps the incident with more sources/details, soft-deletes the rest
by setting review_status='merged' and notes the survivor id.

No API calls. Run any time.
"""
import sqlite3, pathlib, re
from difflib import SequenceMatcher

DB = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

def normalize(s):
    s = (s or "").lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^\w\s]', '', s)
    return s

def similarity(a, b):
    return SequenceMatcher(None, a[:200], b[:200]).ratio()

# Load all incidents with their person links and source counts
rows = con.execute("""
    SELECT i.id, i.summary, i.severity, i.type, i.review_status,
        GROUP_CONCAT(DISTINCT ip.person_id) as person_ids,
        COUNT(DISTINCT ins.source_id) as src_count,
        LENGTH(COALESCE(i.details,'')) as detail_len
    FROM incidents i
    LEFT JOIN incident_people ip ON ip.incident_id = i.id
    LEFT JOIN incident_sources ins ON ins.incident_id = i.id
    WHERE i.review_status != 'merged'
    GROUP BY i.id
""").fetchall()

print(f"Scanning {len(rows)} incidents for duplicates...")

# Group by first 60 chars of normalized summary
by_prefix = {}
for r in rows:
    key = normalize(r["summary"])[:60]
    by_prefix.setdefault(key, []).append(r)

SEV_RANK = {"convicted":6,"indicted":5,"charged":4,"settled":3,"investigation":2,"allegation":1}

merged = 0
merge_log = []

for key, group in by_prefix.items():
    if len(group) < 2: continue

    # Within group, find pairs with high similarity
    for i in range(len(group)):
        for j in range(i+1, len(group)):
            a, b = group[i], group[j]
            if a["review_status"] == "merged" or b["review_status"] == "merged":
                continue

            na = normalize(a["summary"])
            nb = normalize(b["summary"])
            sim = similarity(na, nb)

            if sim < 0.75: continue

            # Pick survivor: higher severity > more sources > more detail
            a_score = SEV_RANK.get(a["severity"],0)*100 + (a["src_count"] or 0)*10 + min(a["detail_len"],100)//10
            b_score = SEV_RANK.get(b["severity"],0)*100 + (b["src_count"] or 0)*10 + min(b["detail_len"],100)//10
            survivor, victim = (a, b) if a_score >= b_score else (b, a)

            # Merge: transfer sources and people from victim → survivor
            for src in con.execute("SELECT source_id FROM incident_sources WHERE incident_id=?", (victim["id"],)):
                con.execute("INSERT OR IGNORE INTO incident_sources (incident_id,source_id) VALUES (?,?)",
                    (survivor["id"], src[0]))
            for p in con.execute("SELECT person_id FROM incident_people WHERE incident_id=?", (victim["id"],)):
                con.execute("INSERT OR IGNORE INTO incident_people (incident_id,person_id) VALUES (?,?)",
                    (survivor["id"], p[0]))

            # Soft-delete victim
            con.execute("""
                UPDATE incidents SET review_status='merged', notes=COALESCE(notes,'')||' [merged into #'||?||']'
                WHERE id=?
            """, (survivor["id"], victim["id"]))

            merge_log.append(f"  #{victim['id']} → #{survivor['id']} (sim={sim:.2f}): {(a['summary'] or '')[:60]}")
            merged += 1

con.commit()

print(f"\nMerged {merged} duplicate incidents")
for line in merge_log[:20]:
    print(line)
if merged > 20:
    print(f"  ... and {merged-20} more")

print(f"\nActive incidents remaining: {con.execute('SELECT COUNT(*) FROM incidents WHERE review_status != ?',('merged',)).fetchone()[0]}")
