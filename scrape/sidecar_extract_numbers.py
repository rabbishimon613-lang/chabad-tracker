"""
sidecar_extract_numbers.py
--------------------------
Scans incident summaries + details for:
  - victim counts  → incidents.victim_count
  - dollar amounts → incidents.amount_usd
  - prison terms   → incidents.prison_years
  - confidence     → incidents.confidence (based on source count + source type)

Pure python/regex — no API calls, no fleet tokens. Run any time.
"""
import sqlite3, re, pathlib

DB = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

def parse_amount(s):
    """'$2.3 million' → 2300000.0, '$500,000' → 500000.0"""
    s = s.replace(",","")
    m = re.search(r'\$?([\d.]+)\s*(million|billion|thousand)?', s, re.I)
    if not m: return None
    n = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit == "billion": n *= 1_000_000_000
    elif unit == "million": n *= 1_000_000
    elif unit == "thousand": n *= 1_000
    return n

def parse_prison(s):
    """'7 years', '18 months', 'life' → years as float"""
    if re.search(r'\blife\b', s, re.I): return 99.0
    m = re.search(r'([\d.]+)\s*year', s, re.I)
    if m: return float(m.group(1))
    m = re.search(r'([\d.]+)\s*month', s, re.I)
    if m: return round(float(m.group(1)) / 12, 2)
    return None

VICTIM_PATTERNS = [
    r'(\d+)\s+(?:victims?|children|students?|minors?|boys?|girls?|complainants?|plaintiffs?)',
    r'(?:at least|more than|over)\s+(\d+)\s+(?:victims?|children|people)',
    r'(\d+)\s+(?:counts?|charges?)\s+of',
    r'molested\s+(\d+)',
    r'abused\s+(\d+)',
]

AMOUNT_PATTERNS = [
    r'\$[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?',
    r'[\d,]+(?:\.\d+)?\s*(?:million|billion)\s+(?:dollar|shekel|pound)',
    r'(?:defrauded?|stole?|embezzled?|laundered?)\s+(?:approximately\s+)?\$?[\d,]+',
]

PRISON_PATTERNS = [
    r'sentenced\s+to\s+[\d.]+\s+(?:year|month)',
    r'[\d.]+\s+(?:year|month)s?\s+(?:in\s+)?(?:federal\s+)?(?:prison|custody|jail)',
    r'[\d.]+\s+to\s+[\d.]+\s+(?:year|month)',
]

rows = con.execute("SELECT id, summary, notes, details FROM incidents").fetchall()

updated = victims_found = amounts_found = prison_found = 0

for r in rows:
    text = " ".join(filter(None, [r["summary"], r["notes"], r["details"]]))
    if not text: continue

    victim_count = None
    amount_usd = None
    prison_years = None

    # Victims
    for pat in VICTIM_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            try:
                v = int(m.group(1))
                if 1 <= v <= 10000:
                    victim_count = v
                    break
            except: pass

    # Amounts
    for pat in AMOUNT_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            amt = parse_amount(m.group(0))
            if amt and amt > 0:
                amount_usd = amt
                break

    # Prison
    for pat in PRISON_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            yrs = parse_prison(m.group(0))
            if yrs:
                prison_years = yrs
                break

    # Confidence score
    src_count = con.execute(
        "SELECT COUNT(*) FROM incident_sources WHERE incident_id=?", (r["id"],)
    ).fetchone()[0]
    sev = con.execute("SELECT severity FROM incidents WHERE id=?", (r["id"],)).fetchone()["severity"]
    sev_conf = {"convicted":0.9,"indicted":0.8,"charged":0.75,"settled":0.7,
                "investigation":0.5,"allegation":0.4,"acquitted":0.85}.get(sev or "", 0.5)
    source_conf = min(0.95, 0.4 + src_count * 0.15)
    confidence = round((sev_conf + source_conf) / 2, 3)

    if victim_count or amount_usd or prison_years:
        con.execute("""
            UPDATE incidents SET
              victim_count = COALESCE(victim_count, ?),
              amount_usd   = COALESCE(amount_usd, ?),
              prison_years = COALESCE(prison_years, ?),
              confidence   = ?
            WHERE id=?
        """, (victim_count, amount_usd, prison_years, confidence, r["id"]))
        updated += 1
        if victim_count: victims_found += 1
        if amount_usd:   amounts_found += 1
        if prison_years: prison_found  += 1
    else:
        con.execute("UPDATE incidents SET confidence=? WHERE id=?", (confidence, r["id"]))

con.commit()
print(f"Updated {updated} incidents")
print(f"  Victim counts found:  {victims_found}")
print(f"  Dollar amounts found: {amounts_found}")
print(f"  Prison terms found:   {prison_found}")

# Summary stats
print("\nTop incidents by amount:")
for r in con.execute("SELECT summary, amount_usd, victim_count, prison_years FROM incidents WHERE amount_usd IS NOT NULL ORDER BY amount_usd DESC LIMIT 10"):
    print(f"  ${r[1]:,.0f} | {r[3]}yr | {r[2]}vic | {(r[0] or '')[:70]}")
