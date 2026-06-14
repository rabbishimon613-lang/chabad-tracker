"""
dragnet_apply.py
-----------------
Called after each overnight wakeup batch. Takes:
  --results   path to fleet search_batch JSON output
  --people    JSON list of {id, name, types, query} dicts that were searched
  --extracts  path to fleet_batch LLM extraction JSON output

Writes directly to DB:
  1. New incidents (if found)
  2. New co-defendant links (incident_people)
  3. New person_relations edges
  4. Enriched details on existing incidents
  5. New sources linked

Outputs a single summary line to stdout + appends to dragnet_log.jsonl
Safe to rerun — everything uses INSERT OR IGNORE / dedup checks.
"""

import sqlite3, json, pathlib, re, datetime, argparse, sys

ROOT   = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB     = ROOT / "data/chabad.db"
LOG    = ROOT / "data/dragnet_log.jsonl"
STATE  = ROOT / "data/dragnet_state.json"
EXTRACTS = ROOT / "data/raw/triage/snippet_extracts.jsonl"

SEV_RANK = {"allegation":1,"investigation":2,"charged":3,"indicted":4,"settled":3,"convicted":6}
SEV_NORM = {"arrested":"charged","arrest":"charged","guilty plea":"convicted","plea":"convicted",
            "guilty":"convicted","sentence":"convicted","sentenced":"convicted",
            "indictment":"indicted","investigation":"investigation","allegation":"allegation"}
TYPE_NORM = {
    "financial_fraud":"financial_fraud","fraud":"financial_fraud","theft":"financial_fraud",
    "tax_evasion":"tax_evasion","money_laundering":"money_laundering",
    "sexual_abuse":"sexual_abuse","child_pornography":"sexual_abuse","abuse":"sexual_abuse",
    "assault":"assault","cover_up":"cover_up","obstruction":"cover_up",
    "drug_trafficking":"drug_trafficking","immigration_fraud":"immigration_fraud",
    "insurance_fraud":"insurance_fraud","other":"other",
}

ap = argparse.ArgumentParser()
ap.add_argument("--results",   required=True)
ap.add_argument("--people",    required=True)
ap.add_argument("--extracts",  required=True)
args = ap.parse_args()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = datetime.datetime.utcnow().isoformat()

people   = json.loads(pathlib.Path(args.people).read_text())
extracts = json.loads(pathlib.Path(args.extracts).read_text())  # list of {details, severity, new_sources, co_conspirators, ...}

# Load existing summaries for dedup
seen = set()
if EXTRACTS.exists():
    for line in EXTRACTS.read_text().splitlines():
        try:
            r = json.loads(line)
            k = (r.get("summary","")[:80]).lower().strip()
            if k: seen.add(k)
        except: pass

name_to_id = {nm.lower().strip(): pid for pid, nm in con.execute("SELECT id, full_name FROM people")}

def find_or_create(name):
    name = name.strip()
    clean = re.sub(r'^(rabbi|mrs?\.|dr\.)\s+', '', name, flags=re.I).strip()
    for n in [name.lower(), clean.lower()]:
        if n in name_to_id: return name_to_id[n]
    parts = clean.split()
    if len(parts) >= 2:
        for full, pid in name_to_id.items():
            fp = full.split()
            if len(fp) >= 2 and fp[-1] == parts[-1].lower() and fp[0] == parts[0].lower():
                return pid
    cur = con.execute("INSERT INTO people (full_name,given_name,surname) VALUES (?,?,?)",
        (name, parts[0] if parts else "", parts[-1] if len(parts)>1 else ""))
    pid = cur.lastrowid
    name_to_id[name.lower()] = pid
    return pid

def link_source(incident_id, url, title=""):
    if not url or not url.startswith("http"): return
    con.execute("INSERT OR IGNORE INTO sources (url,title,accessed_at) VALUES (?,?,?)", (url, title or "", now))
    src = con.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
    if src:
        con.execute("INSERT OR IGNORE INTO incident_sources (incident_id,source_id) VALUES (?,?)",
                    (incident_id, src["id"]))

stats = {"new_incidents":0, "new_relations":0, "enriched":0, "sources":0}

for i, person in enumerate(people):
    if i >= len(extracts): break
    ex = extracts[i]
    if not ex or not isinstance(ex, dict): continue

    pid    = int(person.get("id"))
    pname  = person.get("name","")

    # Get existing incident ids for this person
    inc_ids = [r[0] for r in con.execute(
        "SELECT i.id FROM incidents i JOIN incident_people ip ON ip.incident_id=i.id WHERE ip.person_id=?", (pid,)
    )]

    # ── 1. Enrich existing incidents with new details ─────────────────────────
    details = (ex.get("details") or "").strip()
    if details and inc_ids:
        for iid in inc_ids:
            row = con.execute("SELECT details FROM incidents WHERE id=?", (iid,)).fetchone()
            existing = (row["details"] or "") if row else ""
            if details[:50].lower() not in existing.lower():
                combined = (existing + "\n\n" + details).strip()[:3000]
                con.execute("UPDATE incidents SET details=?, enriched_at=? WHERE id=?", (combined, now, iid))
                stats["enriched"] += 1

        # Upgrade severity
        new_sev = (ex.get("severity") or "").lower().strip()
        new_sev = SEV_NORM.get(new_sev, new_sev)
        if new_sev in SEV_RANK:
            for iid in inc_ids:
                row = con.execute("SELECT severity FROM incidents WHERE id=?", (iid,)).fetchone()
                if row and SEV_RANK.get(new_sev,0) > SEV_RANK.get(row["severity"] or "allegation",1):
                    con.execute("UPDATE incidents SET severity=? WHERE id=?", (new_sev, iid))

    # ── 2. New sources ────────────────────────────────────────────────────────
    for url in (ex.get("new_sources") or []):
        for iid in inc_ids:
            link_source(iid, url)
        stats["sources"] += 1

    # ── 3. New cases from extract ─────────────────────────────────────────────
    for new_case in (ex.get("new_cases") or []):
        summary = (new_case.get("summary") or "").strip()
        if not summary or len(summary) < 15: continue
        key = summary[:80].lower().strip()
        if key in seen: continue
        seen.add(key)

        inc_type = TYPE_NORM.get(new_case.get("type",""), "other")
        severity = SEV_NORM.get((new_case.get("severity") or "").lower(), "allegation")
        year     = new_case.get("year")
        location = new_case.get("location") or ""
        entity   = new_case.get("entity") or ""
        src_url  = new_case.get("source_url") or ""

        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO incidents (type,severity,occurred_on,location,summary,review_status) VALUES (?,?,?,?,?,'auto')",
                (inc_type, severity, f"{year}-01-01" if year else None, location, summary)
            )
            iid = cur.lastrowid
            if not iid: continue
            con.execute("INSERT OR IGNORE INTO incident_people (incident_id,person_id) VALUES (?,?)", (iid, pid))
            if entity:
                hrow = con.execute("SELECT id FROM houses WHERE name LIKE ? LIMIT 1", (f"%{entity[:30]}%",)).fetchone()
                if hrow:
                    con.execute("INSERT OR IGNORE INTO incident_houses (incident_id,house_id) VALUES (?,?)", (iid, hrow["id"]))
            if src_url:
                link_source(iid, src_url)
            stats["new_incidents"] += 1
            inc_ids.append(iid)
        except: pass

    # ── 4. Co-conspirators → person_relations ─────────────────────────────────
    for cname in (ex.get("co_conspirators") or []):
        if not isinstance(cname, str) or len(cname.split()) < 2: continue
        co_pid = find_or_create(cname)
        if co_pid == pid: continue
        a, b = min(pid, co_pid), max(pid, co_pid)
        try:
            con.execute("INSERT OR IGNORE INTO person_relations (person_a,person_b,rel_type,rel_detail) VALUES (?,?,?,?)",
                (a, b, "codefendant", f"co-conspirator of {pname}"))
            stats["new_relations"] += 1
        except: pass

    # ── 5. Mark enriched ──────────────────────────────────────────────────────
    for iid in inc_ids:
        con.execute("UPDATE incidents SET enriched_at=? WHERE id=? AND enriched_at IS NULL", (now, iid))

con.commit()

# ── Update state ──────────────────────────────────────────────────────────────
state = json.loads(STATE.read_text())
state["total_processed"]    = state.get("total_processed", 0) + len(people)
state["new_cases_found"]    = state.get("new_cases_found", 0) + stats["new_incidents"]
state["new_relations_found"]= state.get("new_relations_found",0) + stats["new_relations"]
state["new_details_written"]= state.get("new_details_written",0) + stats["enriched"]
state["runs_completed"]     = state.get("runs_completed", 0) + 1
state["last_run_at"]        = now
STATE.write_text(json.dumps(state, indent=2))

# ── Log entry ─────────────────────────────────────────────────────────────────
log_entry = {"ts": now, "people": len(people), **stats}
with open(LOG, "a") as f:
    f.write(json.dumps(log_entry) + "\n")

summary = f"[dragnet] run#{state['runs_completed']} | people:{len(people)} | +cases:{stats['new_incidents']} | +rels:{stats['new_relations']} | +details:{stats['enriched']} | +sources:{stats['sources']} | total_processed:{state['total_processed']}"
print(summary)
