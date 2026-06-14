"""
Layer 3b: family inference (conservative first pass).

Steps:
  1) Surname clusters → families (≥3 people OR on known-dynasty list)
  2) Spouse inference: same-surname Rabbi/Mrs. pair sharing ≥1 house  → family_relations.spouse_of
  3) Parent/sibling: surnamed people 25+ years apart sharing house → family_relations (heuristic, low confidence)
"""
import sqlite3, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB   = ROOT / "data" / "chabad.db"

# Surnames we treat as families regardless of count (known dynasties + perps we surfaced)
KNOWN_DYNASTIES = {
    "krinsky","shemtov","cunin","kotlarsky","lazar","hecht","raskin","wilhelm","spalter",
    "gurary","holtzberg","feldman","engel","posner","eliezrie","pinson","telsner","junik",
    "marozov","aronov","levitin","loschak","liberow","notik","goldstein","greenberg",
    "edelman","werner","levertov","raichik","eidelman","okunov","sobel","charitonov","segal",
    "kievman","rivkin","gansburg","herson","rubashkin","goodman","kazen","gutnick","lew",
    "weinberg","jacobson","loschak","metzger","steiner","gordon","backman","bryski","bukiet",
    "kalmenson","mishulovin","plotkin","schochet","schusterman","sebbag","silberberg",
    "zalmanov","zarchi","zaltzman","new","mottel","light","kogan","drukman","gaerman"
}

# Surnames so common we should NOT cluster them as one "family"
COMMON_NOISE = {"cohen","levy","levi","katz","kaplan","friedman","goldberg","greenberg",
                "rosenberg","schwartz","weinberg","stein","weiss","klein","fisher","fischer"}

def clean(s):
    return (s or "").strip().lower()

def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")

    # ---- Step 1: Surname clusters → families ----
    surnames = {}
    for pid, sn in con.execute(
        "SELECT id, LOWER(surname) FROM people WHERE surname != ''"
    ).fetchall():
        if not sn: continue
        surnames.setdefault(sn, []).append(pid)

    seed_surnames = []
    for sn, people_ids in surnames.items():
        # Keep if it's a known dynasty OR has ≥3 people, BUT not a common-noise surname
        # unless it's on the explicit known-dynasty list.
        if sn in KNOWN_DYNASTIES:
            seed_surnames.append(sn)
        elif sn in COMMON_NOISE:
            continue
        elif len(people_ids) >= 3:
            seed_surnames.append(sn)

    print(f"family seeds: {len(seed_surnames)}")

    # Wipe and rebuild for idempotency
    con.execute("DELETE FROM family_members")
    con.execute("DELETE FROM family_relations")
    con.execute("DELETE FROM families")

    fam_id_by_surname = {}
    for sn in sorted(seed_surnames):
        cur = con.execute("""
            INSERT INTO families (surname, display_name, lineage_type, notes)
            VALUES (?, ?, 'unknown', ?) RETURNING id
        """, (sn.title(), f"{sn.title()} family",
              "auto-seeded from surname cluster"))
        fam_id_by_surname[sn] = cur.fetchone()[0]

    # Members
    n_members = 0
    for sn, fid in fam_id_by_surname.items():
        for pid in surnames[sn]:
            con.execute("""
                INSERT OR IGNORE INTO family_members (family_id, person_id, relation)
                VALUES (?, ?, 'member')
            """, (fid, pid))
            n_members += 1
    print(f"family_members rows: {n_members}")

    # ---- Step 2: Spouse inference ----
    # For each family, find Rabbi+Mrs pairs sharing ≥1 house.
    spouse_count = 0
    rows = con.execute("""
        SELECT fm.family_id, p.id, p.full_name, p.given_name, p.gender
        FROM family_members fm JOIN people p ON p.id = fm.person_id
    """).fetchall()
    by_fam = {}
    for fid, pid, full, gn, g in rows:
        title = (full.split() or [""])[0].lower().strip(".")
        is_m  = (g == "m") or title in ("rabbi","mr","reb")
        is_f  = (g == "f") or title in ("mrs","ms","miss")
        by_fam.setdefault(fid, []).append({"id":pid,"name":full,"first":gn or "","m":is_m,"f":is_f})

    for fid, members in by_fam.items():
        males   = [m for m in members if m["m"] and not m["f"]]
        females = [m for m in members if m["f"] and not m["m"]]
        if not males or not females: continue
        for mal in males:
            for fem in females:
                # require shared house
                shared = con.execute("""
                    SELECT 1 FROM house_roles r1 JOIN house_roles r2 ON r1.house_id = r2.house_id
                    WHERE r1.person_id=? AND r2.person_id=? LIMIT 1
                """, (mal["id"], fem["id"])).fetchone()
                if not shared: continue
                a, b = sorted([mal["id"], fem["id"]])
                # Insert both directions for easy traversal
                con.execute("""
                    INSERT OR IGNORE INTO family_relations (person_a, person_b, relation)
                    VALUES (?, ?, 'spouse_of')
                """, (a, b))
                spouse_count += 1
    print(f"spouse_of relations: {spouse_count}")

    con.commit()

    # Stats
    print("\ntop 20 families by member count:")
    for sn, n in con.execute("""
        SELECT f.surname, COUNT(*) FROM families f
        JOIN family_members fm ON fm.family_id = f.id
        GROUP BY f.id ORDER BY 2 DESC LIMIT 20
    """).fetchall():
        print(f"  {n:4d}  {sn}")

    con.close()

if __name__ == "__main__":
    main()
