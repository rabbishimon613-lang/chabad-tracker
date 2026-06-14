"""
Pipeline: bucket_aa + bucket_bb → filter snippets → extract incidents → load to DB.
Run after bucket scripts complete.
"""
import asyncio, json, pathlib, sys, os, re, sqlite3

FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
sys.path.insert(0, str(FLEET))
for line in open(FLEET / ".env"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k, v.strip('"').strip("'"))

from providers import build_providers
from roles import dispatch_role

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
BUCKETS = ROOT / "data/raw/buckets"
OUT_FILE = ROOT / "data/raw/triage/snippet_extracts.jsonl"
DB = ROOT / "data/chabad.db"

CRIME_KW = [
    "fraud","convict","indict","charg","arrest","plead","guilty","sentenc","prison",
    "abuse","assault","molest","rape","sex crime","child porn","trafficking",
    "laundering","embezzl","theft","steal","scam","ponzi","scheme","extort",
    "obstruct","cover.up","bribery","corruption","tax evad","wire fraud",
    "bank fraud","insurance fraud","welfare","medicaid","immigration fraud",
]
CHABAD_KW = ["chabad","lubavitch","rebbe","rabbi","yeshiva","shliach","emissary","770"]

def is_relevant(text):
    tl = text.lower()
    return any(k in tl for k in CHABAD_KW) and any(k in tl for k in CRIME_KW)

# --- Stage 1: Filter ---
def filter_buckets():
    existing_urls = set()
    if OUT_FILE.exists():
        for line in OUT_FILE.read_text().splitlines():
            try: existing_urls.add(json.loads(line).get("source_url",""))
            except: pass

    candidates = []
    seen_urls = set(existing_urls)
    all_buckets = (list(BUCKETS.glob("bucket_a*.jsonl")) + list(BUCKETS.glob("bucket_b*.jsonl")) +
                   list(BUCKETS.glob("bucket_c*.jsonl")) + list(BUCKETS.glob("bucket_d*.jsonl")) +
                   list(BUCKETS.glob("bucket_e*.jsonl")) + list(BUCKETS.glob("bucket_f*.jsonl")) +
                   list(BUCKETS.glob("bucket_g*.jsonl")) + list(BUCKETS.glob("bucket_h*.jsonl")))
    for bucket_file in sorted(all_buckets):
        for line in bucket_file.read_text().splitlines():
            try:
                obj = json.loads(line)
                for r in obj.get("results", []):
                    url = r.get("url", "")
                    if not url or url in seen_urls: continue
                    title = r.get("title", "")
                    snippet = r.get("snippet", r.get("content", ""))[:600]
                    text = f"{title} {snippet}"
                    if is_relevant(text):
                        candidates.append({"url": url, "title": title, "snippet": snippet})
                        seen_urls.add(url)
            except: pass

    print(f"New candidates: {len(candidates)}")
    return candidates

# --- Stage 2: Extract ---
PROMPT_TMPL = """Extract criminal/legal incidents for a Chabad-Lubavitch wrongdoing database.

TITLE: {title}
URL: {url}
SNIPPET: {snippet}

Output one JSON object per line for each distinct incident. Schema:
{{"name":"Full Name","type":"financial_fraud|tax_evasion|money_laundering|sexual_abuse|child_pornography|assault|cover_up|drug_trafficking|immigration_fraud|insurance_fraud|welfare_fraud|other","severity":"allegation|investigation|charged|indicted|convicted|settled","year":YYYY_or_null,"location":"City, Country or null","entity":"Chabad/Lubavitch house or org name or null","summary":"one sentence ≤120 chars"}}

Rules:
- Only include if a named individual or named Chabad entity is clearly the perpetrator
- If no clear perpetrator: output {{"skip":true}}
- Output ONLY JSON lines, zero prose"""

async def extract_one(c, sem, providers):
    url = c["url"]
    prompt = PROMPT_TMPL.format(
        title=c["title"][:200], url=url[:200], snippet=c["snippet"][:600]
    )
    async with sem:
        try:
            result = await dispatch_role("fast", prompt, 400, providers)
            resp = result.text if result and result.text else ""
            results = []
            for line in resp.strip().split("\n"):
                line = line.strip()
                if not line: continue
                try:
                    obj = json.loads(line)
                    if obj.get("skip"): continue
                    if not obj.get("name") and not obj.get("entity"): continue
                    obj["source_url"] = url
                    obj["source_title"] = c["title"]
                    results.append(obj)
                except: pass
            return results
        except: return []

async def extract_all(candidates):
    providers = build_providers()
    sem = asyncio.Semaphore(8)
    tasks = [extract_one(c, sem, providers) for c in candidates]
    new_count = 0
    done = 0
    with open(OUT_FILE, "a") as f:
        for coro in asyncio.as_completed(tasks):
            results = await coro
            done += 1
            for r in results:
                f.write(json.dumps(r) + "\n")
                new_count += 1
            if done % 50 == 0:
                print(f"  [{done}/{len(tasks)}] new extracts: {new_count}")
    print(f"\nExtraction done. New incidents: {new_count}")
    return new_count

# --- Stage 3: Load ---
SEV_NORM = {"allegation":"allegation","investigation":"investigation","charged":"charged",
    "indicted":"indicted","convicted":"convicted","settled":"settled",
    "arrested":"charged","arrest":"charged","guilty plea":"convicted","plea":"convicted","acquitted":"acquitted"}
TYPE_NORM = {"financial_fraud":"financial_fraud","fraud":"financial_fraud","tax_evasion":"tax_evasion",
    "money_laundering":"money_laundering","sexual_abuse":"sexual_abuse","child_pornography":"sexual_abuse",
    "assault":"assault","cover_up":"cover_up","obstruction":"cover_up","drug_trafficking":"drug_trafficking",
    "immigration_fraud":"immigration_fraud","insurance_fraud":"insurance_fraud",
    "welfare_fraud":"financial_fraud","other":"other","unclear":"other"}

def load_to_db():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")

    seen_summaries = set()
    for row in con.execute("SELECT summary FROM incidents WHERE summary IS NOT NULL"):
        seen_summaries.add(row[0][:80].lower().strip())

    import re
    def find_or_create_person(name):
        name = name.strip()
        clean = re.sub(r'^(rabbi|mrs?\.?)\s+', '', name, flags=re.I).strip()
        row = con.execute("SELECT id FROM people WHERE full_name = ? OR full_name LIKE ? LIMIT 1",
            (name, f"%{clean}%")).fetchone()
        if row: return row[0]
        parts = clean.split()
        given = parts[0] if parts else ""
        surname = parts[-1] if len(parts) > 1 else ""
        cur = con.execute("INSERT INTO people (full_name, given_name, surname) VALUES (?,?,?)", (name, given, surname))
        return cur.lastrowid

    def find_or_create_house(entity_name):
        if not entity_name: return None
        entity_name = entity_name.strip()
        row = con.execute("SELECT id FROM houses WHERE name LIKE ? LIMIT 1", (f"%{entity_name[:30]}%",)).fetchone()
        if row: return row[0]
        cur = con.execute("INSERT INTO houses (name) VALUES (?)", (entity_name,))
        return cur.lastrowid

    loaded = skipped = 0
    for line in OUT_FILE.read_text().splitlines():
        try: r = json.loads(line)
        except: continue
        if r.get("skip"): continue
        name = (r.get("name") or "").strip()
        summary = (r.get("summary") or "").strip()
        if not name or name.lower() in ("unknown","unnamed","rabbi (unnamed)","rabbi (name not specified)","new jersey rabbi","lakewood rabbi","rabbi"): skipped += 1; continue
        if not summary or len(summary) < 10: skipped += 1; continue
        key = summary[:80].lower().strip()
        if key in seen_summaries: skipped += 1; continue
        seen_summaries.add(key)

        inc_type = TYPE_NORM.get(r.get("type",""), "other")
        severity = SEV_NORM.get(r.get("severity","").lower(), "allegation")
        year = r.get("year")
        location = r.get("location") or ""
        entity = r.get("entity") or ""
        source_url = r.get("source_url","")
        occurred_on = f"{year}-01-01" if year else None

        try:
            cur = con.execute("""INSERT OR IGNORE INTO incidents (type, severity, occurred_on, location, summary, review_status)
                VALUES (?,?,?,?,?,'auto')""", (inc_type, severity, occurred_on, location, summary))
            inc_id = cur.lastrowid
            if not inc_id: skipped += 1; continue
            person_id = find_or_create_person(name)
            con.execute("INSERT OR IGNORE INTO incident_people (incident_id, person_id) VALUES (?,?)", (inc_id, person_id))
            if entity:
                house_id = find_or_create_house(entity)
                if house_id:
                    con.execute("INSERT OR IGNORE INTO incident_houses (incident_id, house_id) VALUES (?,?)", (inc_id, house_id))
                    con.execute("INSERT OR IGNORE INTO house_roles (person_id, house_id) VALUES (?,?)", (person_id, house_id))
            if source_url:
                con.execute("INSERT OR IGNORE INTO sources (url) VALUES (?)", (source_url,))
                src_row = con.execute("SELECT id FROM sources WHERE url=?", (source_url,)).fetchone()
                if src_row:
                    con.execute("INSERT OR IGNORE INTO incident_sources (incident_id, source_id) VALUES (?,?)", (inc_id, src_row[0]))
            loaded += 1
        except: skipped += 1

    con.commit()
    print(f"Loaded: {loaded} new incidents, skipped: {skipped}")
    print(f"Total incidents: {con.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]}")
    print(f"Total people: {con.execute('SELECT COUNT(*) FROM people').fetchone()[0]}")
    con.close()

if __name__ == "__main__":
    candidates = filter_buckets()
    if candidates:
        asyncio.run(extract_all(candidates))
    else:
        print("No new candidates — running load only")
    load_to_db()
