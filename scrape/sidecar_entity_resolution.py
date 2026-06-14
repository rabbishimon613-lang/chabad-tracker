"""
sidecar_entity_resolution.py
------------------------------
Finds duplicate people entries using fuzzy name matching.
Merges duplicates: transfers all incident/house links to canonical entry,
marks duplicates with review_status, logs aliases.

Pure python — no API calls.
"""
import sqlite3, pathlib, re
from difflib import SequenceMatcher

DB = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

def normalize_name(n):
    n = (n or "").strip().lower()
    n = re.sub(r'^(rabbi|mrs?\.|dr\.|rev\.)\s+', '', n)
    n = re.sub(r'\s+', ' ', n)
    # Common transliteration variants
    n = n.replace('yitzchok','yitzchak').replace('mordechai','mordecai')
    n = n.replace('sholom','shalom').replace('menachem','menachem')
    n = n.replace('zvi','tzvi').replace('tz','z')
    return n.strip()

def name_similarity(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if na == nb: return 1.0
    # Check if surnames match AND first name starts with same letter
    pa, pb = na.split(), nb.split()
    if len(pa) >= 2 and len(pb) >= 2:
        if pa[-1] == pb[-1] and pa[0][0] == pb[0][0]:
            return SequenceMatcher(None, na, nb).ratio()
    return SequenceMatcher(None, na, nb).ratio()

# Load all people with incident counts
people = con.execute("""
    SELECT p.id, p.full_name,
        COUNT(DISTINCT ip.incident_id) as n_inc,
        COUNT(DISTINCT hr.house_id) as n_houses
    FROM people p
    LEFT JOIN incident_people ip ON ip.person_id=p.id
    LEFT JOIN house_roles hr ON hr.person_id=p.id
    GROUP BY p.id
    ORDER BY n_inc DESC, n_houses DESC
""").fetchall()

print(f"Scanning {len(people)} people for duplicates...")

# Group by normalized surname for efficiency
by_surname = {}
for p in people:
    parts = normalize_name(p["full_name"]).split()
    surname = parts[-1] if parts else ""
    by_surname.setdefault(surname, []).append(p)

merged = 0
alias_pairs = []

for surname, group in by_surname.items():
    if len(group) < 2 or not surname: continue
    for i in range(len(group)):
        for j in range(i+1, len(group)):
            a, b = group[i], group[j]
            sim = name_similarity(a["full_name"], b["full_name"])
            if sim < 0.82: continue

            # Pick canonical: more incidents > more houses > lower id
            if a["n_inc"] >= b["n_inc"]:
                canon, dupe = a, b
            else:
                canon, dupe = b, a

            print(f"  MERGE: '{dupe['full_name']}' → '{canon['full_name']}' (sim={sim:.2f})")

            # Transfer incident links
            for r in con.execute("SELECT incident_id FROM incident_people WHERE person_id=?", (dupe["id"],)):
                con.execute("INSERT OR IGNORE INTO incident_people (incident_id,person_id) VALUES (?,?)",
                    (r[0], canon["id"]))

            # Transfer house links
            for r in con.execute("SELECT house_id FROM house_roles WHERE person_id=?", (dupe["id"],)):
                con.execute("INSERT OR IGNORE INTO house_roles (person_id,house_id) VALUES (?,?)",
                    (canon["id"], r[0]))

            # Transfer person_relations
            for r in con.execute("SELECT person_a, person_b, rel_type, rel_detail FROM person_relations WHERE person_a=? OR person_b=?", (dupe["id"], dupe["id"])):
                new_a = canon["id"] if r[0] == dupe["id"] else r[0]
                new_b = canon["id"] if r[1] == dupe["id"] else r[1]
                if new_a != new_b:
                    con.execute("INSERT OR IGNORE INTO person_relations (person_a,person_b,rel_type,rel_detail) VALUES (?,?,?,?)",
                        (min(new_a,new_b), max(new_a,new_b), r[2], r[3]))

            # Add alias to canonical
            existing_aliases = con.execute("SELECT aliases FROM people WHERE id=?", (canon["id"],)).fetchone()["aliases"] or ""
            new_alias = dupe["full_name"]
            if new_alias not in existing_aliases:
                con.execute("UPDATE people SET aliases=? WHERE id=?",
                    ((existing_aliases + "|" + new_alias).strip("|"), canon["id"]))

            # Soft-delete dupe
            con.execute("UPDATE people SET full_name=? WHERE id=?",
                (f"[MERGED→{canon['id']}] {dupe['full_name']}", dupe["id"]))

            alias_pairs.append((canon["full_name"], dupe["full_name"]))
            merged += 1

con.commit()
print(f"\nMerged {merged} duplicate people")
print(f"Active people: {con.execute('SELECT COUNT(*) FROM people WHERE full_name NOT LIKE ?', ('%[MERGED%',)).fetchone()[0]}")
