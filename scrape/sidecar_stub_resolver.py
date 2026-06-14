"""
sidecar_stub_resolver.py
-------------------------
Triangulates person names for unlinked "stub" incidents using three tiers:

TIER 1 — Direct name extraction from summary text
  The auto-linker only matches against existing people. This tier also
  CREATES new people when a name is found in the summary but not yet in DB.

TIER 2 — Fetch source URL, extract name from article text
  For stubs that have a source URL, fetch the article and pull the name.
  Uses urllib (no API key). Caps at 30 fetches per run.

TIER 3 — Build targeted search queries for remaining stubs
  Writes queries to data/dragnet_stub_queries.json for the next dragnet
  cycle's Tier D pass (fleet search + fast worker extraction).
  Does NOT consume search API budget here — just queues the work.

Run after dragnet_apply.py in post-phase, or standalone:
  python3 scrape/sidecar_stub_resolver.py [--tier 1] [--tier 2] [--tier 3]

Writes: data/dragnet_stub_queries.json  (Tier 3 output for dragnet to pick up)
        data/stub_resolver_log.jsonl    (audit trail)
"""

import sqlite3, pathlib, re, json, datetime, urllib.request, time, argparse

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB   = ROOT / "data/chabad.db"
STUB_QUERIES = ROOT / "data/dragnet_stub_queries.json"
LOG          = ROOT / "data/stub_resolver_log.jsonl"

ap = argparse.ArgumentParser()
ap.add_argument("--tier", type=int, choices=[1,2,3], default=None,
                help="Run only one tier (default: all)")
ap.add_argument("--limit", type=int, default=30,
                help="Max URL fetches for Tier 2 (default: 30)")
args = ap.parse_args()
RUN_ALL = args.tier is None

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = datetime.datetime.utcnow().isoformat()

log_entries = []
def log(tier, inc_id, action, name=None, detail=None):
    e = {"ts": now, "tier": tier, "incident_id": inc_id, "action": action}
    if name: e["name"] = name
    if detail: e["detail"] = detail
    log_entries.append(e)
    print(f"  [T{tier}] inc={inc_id} {action}" + (f" → {name}" if name else ""))

# ── helpers ──────────────────────────────────────────────────────────────────

SKIP_WORDS = {
    "United States", "New York", "Los Angeles", "Supreme Court", "Federal Bureau",
    "Department Justice", "Jewish Community", "Chabad House", "Crown Heights",
    "San Diego", "Yeshiva University", "Tel Aviv", "New Jersey", "Sex Abuse",
    "Royal Commission", "Court Finds", "Court Rules", "District Court",
    "Circuit Court", "United Kingdom", "South Australia", "West Australia",
    "New South Wales", "Victoria Australia", "Chabad Lubavitch",
    # Generic institutional/place terms that look like names
    "Chabad Center", "Chabad Poway", "Chabad Sydney", "Chabad Israel",
    "Chabad Youth", "Former Chabad", "Former Montreal", "Former Rabbi",
    "Beverly Hills", "North Miami", "Pierce County", "Kiryas Joel",
    "Brooklyn Chabad", "Miami Beach", "Miami Chabad", "Delray Beach",
    "Multiple Chabad", "Australian Chabad", "Paris Chabad", "Yeshivah Centre",
    "Yeshivah College", "Oholei Torah", "Friendship Circle", "Lubavitch Educational",
    "Chabad Hasidim", "Jewish Organizations", "Cleveland Heights", "Tel Arza",
    "Chief Chabad", "No Chabad",
}

# Hebrew/Jewish first names — strong signal this is a real person name
JEWISH_FIRSTNAMES = {
    "moshe","shlomo","menachem","mendel","dovid","yosef","chaim","zalman","levi",
    "baruch","shneur","yehuda","avraham","aryeh","naftali","pinchas","shimon",
    "sholom","shalom","boruch","eliezer","yaacov","yitzchak","mordechai","efraim",
    "tzvi","zvi","binyamin","aharon","yisroel","israel","meir","meyer","ber",
    "velvel","mayer","leibel","schmiel","schneur","herschel","hirsch","zelig",
    "bentzion","menahem","nachman","kalman","fishel","shmaryahu","schmarya",
    "berel","heshy","sruly","yudi","motti","shmulik","lazer","chezkel",
}

TITLE_PREFIXES = re.compile(r'^(Rabbi|Rebbetzin|Grand Rabbi|Grand Rebbe|Dr\.?|Mrs?\.|Rev\.|HaRav|Cantor)\s+', re.I)

def looks_like_person_name(orig, clean):
    """Return True only if this looks like an actual person name, not a place/org."""
    parts = clean.lower().split()
    if len(parts) < 2:
        return False
    # Must not be a known skip phrase
    if any(w in orig for w in SKIP_WORDS):
        return False
    # If it starts with a title (Rabbi, Dr, etc), trust it
    if TITLE_PREFIXES.match(orig):
        return True
    # If first word is a known Jewish/Hebrew first name, trust it
    if parts[0] in JEWISH_FIRSTNAMES:
        return True
    # Require neither word to be a common place/institution word
    place_words = {"chabad","lubavitch","yeshiva","yeshivah","synagogue","center",
                   "centre","institute","foundation","school","college","former",
                   "multiple","three","two","australian","montreal","paris","brooklyn",
                   "miami","chicago","new","los","san","north","south","east","west"}
    if any(p in place_words for p in parts):
        return False
    # Last word should look like a surname (4+ chars, not a common word)
    common_words = {"fraud","abuse","case","court","rabbi","crime","arrested","charged",
                    "convicted","sentenced","trust","fund","group","inc"}
    if parts[-1] in common_words:
        return False
    return True

def extract_candidate_names(text):
    """Return candidate full names (2+ words, capitalized) from text."""
    # Pattern: optional title + First Last (possibly middle)
    candidates = re.findall(
        r'\b(?:(?:Rabbi|Rebbetzin|Grand Rabbi|Grand Rebbe|Dr\.?|Mrs?\.|Rev\.)\s+)?'
        r'([A-Z][a-z]{1,15}(?:[\s\-][A-Z][a-z]{1,15}){1,3})\b',
        text
    )
    out = []
    for c in candidates:
        clean = TITLE_PREFIXES.sub('', c).strip()
        if looks_like_person_name(c, clean):
            out.append((c, clean))
    return out

def find_or_create_person(name_original, name_clean):
    """Return person_id, created(bool). Creates if name_clean has 2+ words."""
    # Try exact match first (with and without title)
    for lookup in (name_original, name_clean):
        r = con.execute(
            "SELECT id FROM people WHERE full_name=? AND full_name NOT LIKE '%[MERGED%'",
            (lookup,)).fetchone()
        if r: return r["id"], False
    # Try LIKE on clean name (handles 'Rabbi X Y' stored as 'X Y')
    r = con.execute(
        "SELECT id FROM people WHERE full_name LIKE ? AND full_name NOT LIKE '%[MERGED%' LIMIT 1",
        (f"%{name_clean}%",)).fetchone()
    if r: return r["id"], False
    # Create
    cid = con.execute("INSERT INTO people (full_name) VALUES (?)", (name_original,)).lastrowid
    return cid, True

def link_incident(inc_id, person_id):
    con.execute(
        "INSERT OR IGNORE INTO incident_people (incident_id, person_id, role) VALUES (?,?,'perpetrator')",
        (inc_id, person_id))

def get_unlinked():
    return con.execute("""
        SELECT i.id, i.summary, i.type, i.severity,
               substr(i.occurred_on,1,4) as yr, i.location, i.amount_usd, i.prison_years,
               s.url, s.title as src_title
        FROM incidents i
        LEFT JOIN incident_sources isr ON isr.incident_id=i.id
        LEFT JOIN sources s ON s.id=isr.source_id
        WHERE NOT EXISTS (SELECT 1 FROM incident_people ip WHERE ip.incident_id=i.id)
        ORDER BY i.id
    """).fetchall()

# ── TIER 1: extract names from summary text ──────────────────────────────────
t1_linked = 0
if args.tier == 1 or RUN_ALL:
    print(f"\n[TIER 1] Name extraction from summaries...")
    for inc in get_unlinked():
        if not inc["summary"] or len(inc["summary"]) < 20: continue
        candidates = extract_candidate_names(inc["summary"])
        for orig, clean in candidates[:6]:
            pid, created = find_or_create_person(orig, clean)
            link_incident(inc["id"], pid)
            action = "created+linked" if created else "linked"
            log(1, inc["id"], action, name=orig)
            t1_linked += 1
            break   # only first good match per incident
    con.commit()
    print(f"  Tier 1: {t1_linked} linked")

# ── TIER 2: fetch source URLs and extract names ───────────────────────────────
t2_linked = 0
if args.tier == 2 or RUN_ALL:
    print(f"\n[TIER 2] URL fetch + name extraction (limit={args.limit})...")
    HEADERS = {"User-Agent": "Mozilla/5.0 (research)"}
    fetched = 0

    for inc in get_unlinked():
        if not inc["url"]: continue
        if fetched >= args.limit: break

        try:
            req = urllib.request.Request(inc["url"], headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read(8000).decode("utf-8", errors="replace")
            fetched += 1
            time.sleep(0.3)

            # Strip tags
            text = re.sub(r'<[^>]+>', ' ', raw)
            text = re.sub(r'\s+', ' ', text)[:3000]

            # Try to extract name from article
            # Priority: structured patterns like "Rabbi X Y was convicted"
            patterns = [
                r'(?:Rabbi|Rebbetzin|Dr\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})(?:\s+(?:was|has|pled|pleaded|sentenced|convicted|charged|arrested))',
                r'([A-Z][a-z]+\s+[A-Z][a-z]+),?\s+(?:a\s+)?(?:rabbi|cantor|principal|teacher|director)',
            ]
            found_name = None
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    found_name = m.group(1).strip()
                    break

            if not found_name:
                # Fallback: first good candidate name from article
                cands = extract_candidate_names(text)
                for orig, clean in cands[:8]:
                    if len(clean.split()) >= 2:
                        found_name = orig
                        break

            if found_name:
                clean = TITLE_PREFIXES.sub('', found_name).strip()
                pid, created = find_or_create_person(found_name, clean)
                link_incident(inc["id"], pid)
                action = "created+linked" if created else "linked"
                log(2, inc["id"], action, name=found_name, detail=inc["url"])
                t2_linked += 1

        except Exception as e:
            log(2, inc["id"], "fetch_error", detail=str(e)[:120])

    con.commit()
    print(f"  Tier 2: {t2_linked} linked from {fetched} URLs fetched")

# ── TIER 3: build search queries for remaining stubs ─────────────────────────
t3_queued = 0
if args.tier == 3 or RUN_ALL:
    print(f"\n[TIER 3] Building search queries for remaining stubs...")

    remaining = get_unlinked()
    stub_queries = json.loads(STUB_QUERIES.read_text()) if STUB_QUERIES.exists() else []
    existing_ids = {q["incident_id"] for q in stub_queries}

    for inc in remaining:
        if inc["id"] in existing_ids: continue

        summary = (inc["summary"] or "")[:120]
        loc     = inc["location"] or ""
        yr      = inc["yr"] or ""
        typ     = inc["type"] or ""
        sev     = inc["severity"] or ""

        # Build the most specific query possible from available signals
        parts = []

        # Extract any partial name already in summary (for search context)
        partial_name = None
        cands = extract_candidate_names(summary)
        if cands:
            partial_name = cands[0][1]  # stripped-title version

        if partial_name:
            parts.append(f'"{partial_name}"')

        # Add location and Chabad anchor
        if loc:
            city = loc.split(",")[0].strip()
            parts.append(f'"{city}"')

        parts.append("Chabad")

        # Add type signal
        type_keywords = {
            "sexual_abuse": "sexual abuse convicted OR arrested",
            "financial_fraud": "fraud convicted OR indicted",
            "tax_evasion": "tax fraud convicted",
            "money_laundering": "money laundering convicted",
            "cover_up": "cover up abuse rabbi",
            "immigration_fraud": "immigration fraud convicted",
            "assault": "assault convicted",
        }
        parts.append(type_keywords.get(typ, sev))

        if yr:
            parts.append(yr)

        query = " ".join(parts)

        stub_queries.append({
            "incident_id": inc["id"],
            "query": query,
            "summary_hint": summary[:80],
            "type": typ,
            "severity": sev,
            "location": loc,
            "year": yr,
            "has_url": bool(inc["url"]),
            "source_url": inc["url"],
            "added_at": now,
        })
        t3_queued += 1

    STUB_QUERIES.write_text(json.dumps(stub_queries, indent=2, ensure_ascii=False))
    print(f"  Tier 3: {t3_queued} queries queued → {STUB_QUERIES}")

# ── write log ────────────────────────────────────────────────────────────────
if log_entries:
    with open(LOG, "a") as f:
        for e in log_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

# ── summary ──────────────────────────────────────────────────────────────────
unlinked_now = con.execute("""
    SELECT COUNT(*) FROM incidents i
    WHERE NOT EXISTS (SELECT 1 FROM incident_people ip WHERE ip.incident_id=i.id)
""").fetchone()[0]

print(f"""
STUB RESOLVER SUMMARY
  Tier 1 (name extraction): {t1_linked} linked
  Tier 2 (URL fetch):       {t2_linked} linked
  Tier 3 (queries queued):  {t3_queued} queued
  Still unlinked:           {unlinked_now}
""")
