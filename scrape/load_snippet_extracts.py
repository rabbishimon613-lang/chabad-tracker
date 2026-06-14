"""
Load snippet_extracts.jsonl → DB. Maps extracted incidents to existing people/houses or creates new ones.
"""
import json, pathlib, sqlite3, re

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB = ROOT / "data/chabad.db"
EXTRACTS = ROOT / "data/raw/triage/snippet_extracts.jsonl"

con = sqlite3.connect(DB)
con.execute("PRAGMA journal_mode=WAL")

SEV_NORM = {
    "allegation":"allegation","investigation":"investigation",
    "charged":"charged","indicted":"indicted","convicted":"convicted",
    "settled":"settled","arrested":"charged","arrest":"charged",
    "guilty plea":"convicted","plea":"convicted","acquitted":"acquitted",
}

TYPE_NORM = {
    "financial_fraud":"financial_fraud","fraud":"financial_fraud",
    "tax_evasion":"tax_evasion","money_laundering":"money_laundering",
    "sexual_abuse":"sexual_abuse","child_pornography":"sexual_abuse",
    "assault":"assault","cover_up":"cover_up","obstruction":"cover_up",
    "drug_trafficking":"drug_trafficking","immigration_fraud":"immigration_fraud",
    "insurance_fraud":"insurance_fraud","welfare_fraud":"financial_fraud",
    "other":"other","unclear":"other",
}

def find_or_create_person(name):
    name = name.strip()
    # Strip "Rabbi " prefix for matching
    clean = re.sub(r'^(rabbi|mrs?\.?)\s+', '', name, flags=re.I).strip()
    # Exact match first (case-insensitive)
    row = con.execute(
        "SELECT id FROM people WHERE LOWER(full_name) = LOWER(?) OR LOWER(full_name) = LOWER(?) LIMIT 1",
        (name, clean)
    ).fetchone()
    if row: return row[0]
    # LIKE fallback only for names longer than 6 chars (avoids matching "Smith" → "Goldsmith")
    if len(clean) > 6:
        row = con.execute(
            "SELECT id FROM people WHERE full_name LIKE ? LIMIT 1",
            (f"%{clean}%",)
        ).fetchone()
        if row: return row[0]
    # Create new
    parts = clean.split()
    given = parts[0] if parts else ""
    surname = parts[-1] if len(parts) > 1 else ""
    cur = con.execute(
        "INSERT INTO people (full_name, given_name, surname) VALUES (?,?,?)",
        (name, given, surname)
    )
    return cur.lastrowid

def find_or_create_house(entity_name):
    if not entity_name: return None
    entity_name = entity_name.strip()
    row = con.execute(
        "SELECT id FROM houses WHERE name LIKE ? LIMIT 1",
        (f"%{entity_name[:30]}%",)
    ).fetchone()
    if row: return row[0]
    cur = con.execute("INSERT INTO houses (name) VALUES (?)", (entity_name,))
    return cur.lastrowid

loaded = 0
skipped = 0
seen_summaries = set()

# Load existing summaries to avoid dupes
for row in con.execute("SELECT summary FROM incidents WHERE summary IS NOT NULL"):
    seen_summaries.add(row[0][:80].lower().strip())

for line in EXTRACTS.read_text().splitlines():
    try:
        r = json.loads(line)
    except: continue
    if r.get("skip"): continue

    name = (r.get("name") or "").strip()
    summary = (r.get("summary") or "").strip()
    inc_type = TYPE_NORM.get(r.get("type",""), "other")
    severity = SEV_NORM.get(r.get("severity","").lower(), "allegation")
    year = r.get("year")
    location = r.get("location") or ""
    entity = r.get("entity") or ""
    source_url = r.get("source_url","")

    # Skip unnamed/vague
    if not name or name.lower() in ("unknown","unnamed","rabbi (unnamed)","rabbi (name not specified)","new jersey rabbi","lakewood rabbi","rabbi"):
        skipped += 1; continue
    if not summary or len(summary) < 10:
        skipped += 1; continue

    # Dedup on summary
    key = summary[:80].lower().strip()
    if key in seen_summaries:
        skipped += 1; continue
    seen_summaries.add(key)

    # Parse location
    city, country = "", ""
    if location:
        parts = [p.strip() for p in location.split(",")]
        city = parts[0] if parts else ""
        country = parts[-1] if len(parts) > 1 else ""

    # Occurred on
    occurred_on = f"{year}-01-01" if year else None

    # Insert incident
    try:
        cur = con.execute("""
            INSERT OR IGNORE INTO incidents (type, severity, occurred_on, location, summary, review_status)
            VALUES (?,?,?,?,?,'auto')
        """, (inc_type, severity, occurred_on, location, summary))
        inc_id = cur.lastrowid
        if not inc_id:
            skipped += 1; continue

        # Link person
        person_id = find_or_create_person(name)
        con.execute("INSERT OR IGNORE INTO incident_people (incident_id, person_id) VALUES (?,?)", (inc_id, person_id))

        # Link house
        if entity:
            house_id = find_or_create_house(entity)
            if house_id:
                con.execute("INSERT OR IGNORE INTO incident_houses (incident_id, house_id) VALUES (?,?)", (inc_id, house_id))
                con.execute("INSERT OR IGNORE INTO house_roles (person_id, house_id) VALUES (?,?)", (person_id, house_id))

        # Source
        if source_url:
            con.execute("INSERT OR IGNORE INTO sources (url) VALUES (?)", (source_url,))
            src_row = con.execute("SELECT id FROM sources WHERE url=?", (source_url,)).fetchone()
            if src_row:
                con.execute("INSERT OR IGNORE INTO incident_sources (incident_id, source_id) VALUES (?,?)", (inc_id, src_row[0]))

        loaded += 1
    except Exception as e:
        skipped += 1

con.commit()
print(f"Loaded: {loaded} new incidents, skipped: {skipped}")
print(f"Total incidents: {con.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]}")
print(f"Total people:    {con.execute('SELECT COUNT(*) FROM people').fetchone()[0]}")
