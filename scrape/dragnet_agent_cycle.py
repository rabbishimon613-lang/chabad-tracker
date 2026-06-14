"""
dragnet_agent_cycle.py
-----------------------
Called by a background agent each ScheduleWakeup.
Prepares everything Python-side so the agent only needs to:
  1. Fire ONE search_batch call
  2. Fire ONE fleet_batch call
  3. Write results

Usage:
  python3 scrape/dragnet_agent_cycle.py --phase prep
    → builds all queries, writes data/agent_cycle_input.json

  python3 scrape/dragnet_agent_cycle.py --phase apply --results data/agent_fleet_results.json
    → writes all new cases/details to DB, updates state

  python3 scrape/dragnet_agent_cycle.py --phase summary
    → prints and writes data/cycle_last_result.json
"""

import sqlite3, pathlib, json, datetime, re, argparse, sys

ROOT  = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB    = ROOT / "data/chabad.db"
STATE = ROOT / "data/dragnet_state.json"
HOT   = ROOT / "data/dragnet_hot_queue.json"
SOURCES_FILE = ROOT / "data/dragnet_sources.json"
STUB_Q       = ROOT / "data/dragnet_stub_queries.json"
CYCLE_INPUT  = ROOT / "data/agent_cycle_input.json"
FLEET_RESULTS= ROOT / "data/agent_fleet_results.json"
LAST_RESULT  = ROOT / "data/cycle_last_result.json"

ap = argparse.ArgumentParser()
ap.add_argument("--phase", choices=["prep","apply","summary"], required=True)
ap.add_argument("--results", default=str(FLEET_RESULTS))
ap.add_argument("--batch-size", type=int, default=20)
ap.add_argument("--broad-per-cycle", type=int, default=10)
ap.add_argument("--stub-per-cycle", type=int, default=8)
args = ap.parse_args()

now = datetime.datetime.utcnow().isoformat()

def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {
        "queue_position": 0, "runs_completed": 0, "total_processed": 0}

def save_state(s):
    STATE.write_text(json.dumps(s, indent=2))

# ─── PREP PHASE ──────────────────────────────────────────────────────────────
if args.phase == "prep":
    state   = load_state()
    cycle_n = state.get("runs_completed", 0)
    pos     = state.get("queue_position", 0)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # ── Person batch (20 people, hot queue first) ─────────────────────────────
    hot_queue = json.loads(HOT.read_text()) if HOT.exists() else []
    hot_batch = hot_queue[:args.batch_size]
    HOT.write_text(json.dumps(hot_queue[args.batch_size:], indent=2, ensure_ascii=False))

    regular_batch = []
    if len(hot_batch) < args.batch_size:
        needed = args.batch_size - len(hot_batch)
        people_rows = con.execute("""
            SELECT p.id, p.full_name,
                   GROUP_CONCAT(DISTINCT i.type) as types,
                   MAX(CASE i.severity
                       WHEN 'convicted' THEN 6 WHEN 'indicted' THEN 5
                       WHEN 'charged'   THEN 4 WHEN 'investigation' THEN 3
                       WHEN 'settled'   THEN 3 WHEN 'allegation'   THEN 2 ELSE 1
                   END) as sev_rank
            FROM people p
            JOIN incident_people ip ON ip.person_id=p.id
            JOIN incidents i        ON i.id=ip.incident_id
            WHERE p.full_name NOT LIKE '%[MERGED%'
            GROUP BY p.id
            ORDER BY sev_rank DESC, p.id
        """).fetchall()

        total_people = len(people_rows)
        if pos >= total_people: pos = 0
        for row in people_rows[pos:pos+needed]:
            loc_r = con.execute("SELECT location FROM incidents i JOIN incident_people ip ON ip.incident_id=i.id WHERE ip.person_id=? AND location IS NOT NULL LIMIT 1", (row["id"],)).fetchone()
            house_r = con.execute("SELECT h.name FROM houses h JOIN house_roles hr ON hr.house_id=h.id WHERE hr.person_id=? LIMIT 1", (row["id"],)).fetchone()
            regular_batch.append({
                "id": row["id"], "name": row["full_name"],
                "types": row["types"] or "other",
                "location": loc_r[0] if loc_r else "",
                "house": house_r[0] if house_r else "",
                "hot": False,
            })
        state["queue_position"] = pos + len(regular_batch)
        state["queue_total"]    = total_people

    people_batch = hot_batch + regular_batch
    print(f"People batch: {len(hot_batch)} hot + {len(regular_batch)} regular = {len(people_batch)}")

    # ── Build Tier A: person queries (rotate angle by cycle+index) ────────────
    ANGLES = [
        '"{name}" site:justice.gov OR site:fbi.gov',
        '"{name}" site:courtlistener.com OR site:law.justia.com',
        '"{name}" Chabad crime -site:chabad.org -site:jta.org',
        '"{name}" rabbi arrested charged convicted "{location}"',
        '"{name}" victim lawsuit civil settlement Chabad',
        '"{name}" site:haaretz.com OR site:thejc.com OR site:australianjewishnews.com',
        '"{name}" Lubavitch court verdict sentencing documents',
        '"{name}" Chabad "{house}" fraud abuse crime',
    ]
    tier_a_queries = []
    for i, p in enumerate(people_batch):
        angle_idx = (cycle_n + i) % len(ANGLES)
        q = ANGLES[angle_idx].format(name=p["name"], location=p.get("location","").split(",")[0], house=p.get("house","Chabad"))
        tier_a_queries.append({"query": q, "person_id": p["id"], "person_name": p["name"], "tier": "A"})

    # ── Build Tier B: broad dragnet (10 per cycle, rotating) ─────────────────
    sources_data = json.loads(SOURCES_FILE.read_text()) if SOURCES_FILE.exists() else {}
    broad_q      = sources_data.get("broad_queries", [])

    # Augment with hardcoded high-value broad queries
    HARDCODED_BROAD = [
        'site:justice.gov "Chabad" OR "Lubavitch" convicted sentenced 2024 2025',
        'site:justice.gov "Chabad" OR "Lubavitch" charged indicted 2023 2024 2025',
        'Chabad rabbi convicted sentenced 2024 2025 -site:chabad.org',
        'Lubavitch rabbi arrested charged 2024 2025 -site:chabad.org',
        'Chabad rabbi sex abuse convicted sentenced 2023 2024 2025',
        'Chabad rabbi fraud money laundering convicted UK Canada Australia 2022 2023 2024',
        'site:australianjewishnews.com Chabad rabbi charged convicted 2022 2023 2024',
        'site:thejc.com Chabad OR Lubavitch rabbi convicted fraud abuse 2022 2023 2024',
        'חב"ד רב הורשע נאשם מעצר 2023 2024',
        'site:failedmessiah.typepad.com Chabad convicted arrested charged rabbi',
        'Chabad rabbi convicted Canada Montreal Toronto 2020 2021 2022 2023 2024',
        'Chabad rabbi convicted UK London Manchester 2019 2020 2021 2022 2023 2024',
        'Chabad rabbi arrested Israel fraud abuse 2023 2024 site:haaretz.com OR site:timesofisrael.com',
        '"Operation Bid Rig" rabbi sentenced prison NJ',
        'Agriprocessors convicted sentenced employees managers workers 2008 2009 2010',
        'Chabad rabbi Argentina Brazil South America convicted fraud abuse',
        'Chabad yeshiva teacher convicted sexual abuse students 2020 2021 2022 2023 2024',
        'site:courtlistener.com Chabad rabbi convicted sentenced',
        'Chabad rabbi get extortion kidnapping convicted sentenced',
        'Chabad rabbi immigration fraud visa convicted sentenced',
    ]
    all_broad = HARDCODED_BROAD + [q for q in broad_q if q not in HARDCODED_BROAD]
    broad_idx = (cycle_n * args.broad_per_cycle) % max(len(all_broad), 1)
    selected_broad = []
    for i in range(args.broad_per_cycle):
        selected_broad.append(all_broad[(broad_idx + i) % len(all_broad)])

    tier_b_queries = [{"query": q, "tier": "B", "label": f"broad-{i}"} for i, q in enumerate(selected_broad)]

    # ── Build Tier C: stub resolution (8 per cycle) ────────────────────────────
    stub_queries_all = json.loads(STUB_Q.read_text()) if STUB_Q.exists() else []
    # Pick unresolved stubs with highest signal (has source_url or longer summary_hint)
    unresolved = [s for s in stub_queries_all if not s.get("resolved")]
    unresolved.sort(key=lambda x: (bool(x.get("source_url")), len(x.get("summary_hint",""))), reverse=True)
    stub_batch = unresolved[:args.stub_per_cycle]
    tier_c_queries = [{"query": s["query"], "tier": "C", "incident_id": s.get("incident_id"), "source_url": s.get("source_url"), "label": s.get("summary_hint","")[:40]} for s in stub_batch]

    all_queries = tier_a_queries + tier_b_queries + tier_c_queries
    print(f"Total queries: {len(tier_a_queries)} Tier-A + {len(tier_b_queries)} Tier-B + {len(tier_c_queries)} Tier-C = {len(all_queries)}")

    # ── People metadata for fleet prompts ─────────────────────────────────────
    people_meta = {}
    for p in people_batch:
        inc_rows = con.execute("""
            SELECT i.type, i.severity, substr(i.summary,1,120) as s
            FROM incidents i JOIN incident_people ip ON ip.incident_id=i.id
            WHERE ip.person_id=? ORDER BY i.id LIMIT 3
        """, (p["id"],)).fetchall()
        people_meta[p["id"]] = {
            "name": p["name"], "types": p["types"],
            "location": p.get("location",""), "house": p.get("house",""),
            "known_incidents": [{"type":r["type"],"severity":r["severity"],"summary":r["s"]} for r in inc_rows]
        }

    # ── Write input file ───────────────────────────────────────────────────────
    payload = {
        "cycle_n": cycle_n + 1,
        "generated_at": now,
        "people_batch": people_batch,
        "people_meta": people_meta,
        "all_queries": all_queries,
        "tier_a_count": len(tier_a_queries),
        "tier_b_count": len(tier_b_queries),
        "tier_c_count": len(tier_c_queries),
        "stub_batch": stub_batch,
    }
    CYCLE_INPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Cycle input written to {CYCLE_INPUT}")
    print(f"Queue position: {pos} → {state['queue_position']} / {state.get('queue_total','?')}")

    # Save updated state (queue position) but don't increment runs_completed yet
    save_state(state)
    sys.exit(0)

# ─── APPLY PHASE ─────────────────────────────────────────────────────────────
elif args.phase == "apply":
    results_path = pathlib.Path(args.results)
    if not results_path.exists():
        print(f"ERROR: results file {results_path} not found")
        sys.exit(1)

    fleet_output = json.loads(results_path.read_text())
    cycle_input  = json.loads(CYCLE_INPUT.read_text()) if CYCLE_INPUT.exists() else {}

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    new_incidents = 0
    new_relations = 0
    new_details   = 0
    top_finds     = []

    VALID_TYPES = {"financial_fraud","sexual_abuse","cover_up","money_laundering","tax_evasion",
                   "drug_trafficking","immigration_fraud","assault","other"}
    VALID_SEVS  = {"convicted","indicted","charged","settled","investigation","allegation"}

    def get_or_create(name):
        name = (name or "").strip()
        if not name or len(name) < 4: return None, False
        r = con.execute("SELECT id FROM people WHERE full_name=? AND full_name NOT LIKE '%[MERGED%'", (name,)).fetchone()
        if r: return r[0], False
        # Check for close match (last name)
        parts = name.split()
        if len(parts) >= 2:
            r = con.execute("SELECT id FROM people WHERE full_name LIKE ? AND full_name NOT LIKE '%[MERGED%' LIMIT 1",
                            (f"%{parts[-1]}%",)).fetchone()
            # Only use if first name letter matches
            if r:
                existing = r[0]
                ex_name = con.execute("SELECT full_name FROM people WHERE id=?", (existing,)).fetchone()[0]
                ex_parts = ex_name.split()
                if ex_parts and parts[0][0].lower() == ex_parts[-len(parts)][0].lower() if len(ex_parts) >= len(parts) else False:
                    return existing, False
        cid = con.execute("INSERT INTO people (full_name) VALUES (?)", (name,)).lastrowid
        return cid, True

    def add_case(perp_name, summary, typ, sev, year, loc, url, amount=None, prison=None, co_names=[]):
        if not perp_name or len(perp_name.split()) < 2: return None
        typ = typ if typ in VALID_TYPES else "other"
        sev = sev if sev in VALID_SEVS else "allegation"
        pid, created = get_or_create(perp_name)
        if pid is None: return None

        # Skip if person already has same type+severity (dedup)
        if con.execute("SELECT 1 FROM incidents i JOIN incident_people ip ON ip.incident_id=i.id WHERE ip.person_id=? AND i.type=? AND i.severity=?", (pid,typ,sev)).fetchone():
            return None

        yr = f"{year}-01-01" if year and str(year).isdigit() else None
        amt = float(amount) if amount and str(amount).replace('.','').isdigit() else None
        pri = float(prison) if prison and str(prison).replace('.','').isdigit() else None

        cur = con.execute(
            "INSERT INTO incidents (type,severity,occurred_on,location,summary,amount_usd,prison_years,enriched_at) VALUES (?,?,?,?,?,?,?,?)",
            (typ, sev, yr, loc or "", summary or "", amt, pri, now))
        iid = cur.lastrowid
        con.execute("INSERT OR IGNORE INTO incident_people (incident_id,person_id,role) VALUES (?,?,'perpetrator')", (iid, pid))

        if url:
            con.execute("INSERT OR IGNORE INTO sources (url,title,accessed_at,type) VALUES (?,?,?,'court')", (url, (summary or "")[:120], now))
            src = con.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
            if src: con.execute("INSERT OR IGNORE INTO incident_sources (incident_id,source_id) VALUES (?,?)", (iid, src[0]))

        for coname in (co_names or []):
            if not coname or len(coname.split()) < 2: continue
            cp, _ = get_or_create(coname)
            if cp and cp != pid:
                con.execute("INSERT OR IGNORE INTO incident_people (incident_id,person_id,role) VALUES (?,?,'perpetrator')", (iid, cp))
                pa, pb = min(pid,cp), max(pid,cp)
                con.execute("INSERT OR IGNORE INTO person_relations (person_a,person_b,rel_type) VALUES (?,?,'codefendant')", (pa,pb))
        return iid

    # Process Tier A results (person enrichment + new cases)
    tier_a_results = fleet_output.get("tier_a", [])
    for item in tier_a_results:
        pid  = item.get("person_id")
        name = item.get("name","")
        data = item.get("fleet_result", {})
        if not isinstance(data, dict): continue

        # Update details
        details = data.get("details","")
        sev     = data.get("severity","")
        if details and pid:
            con.execute("UPDATE incidents SET enriched_at=?, details=? WHERE id IN (SELECT incident_id FROM incident_people WHERE person_id=?) AND enriched_at IS NULL",
                        (now, details, pid))
            new_details += 1

        # Add new sources
        for url in (data.get("new_sources") or []):
            if url: con.execute("INSERT OR IGNORE INTO sources (url,title,accessed_at,type) VALUES (?,?,?,'court')", (url, name[:80], now))

        # Add new cases
        for nc in (data.get("new_cases") or []):
            iid = add_case(
                nc.get("perpetrator_name") or name,
                nc.get("summary",""),
                nc.get("type","other"),
                nc.get("severity","allegation"),
                nc.get("year"),
                nc.get("location",""),
                nc.get("source_url",""),
                nc.get("amount_usd"),
                nc.get("prison_years"),
                nc.get("co_conspirators",[]),
            )
            if iid:
                new_incidents += 1
                top_finds.append(nc.get("perpetrator_name") or name)

        # Add co-conspirators as relations
        for coname in (data.get("co_conspirators") or []):
            if coname and pid and len(coname.split()) >= 2:
                cp, _ = get_or_create(coname)
                if cp and cp != pid:
                    pa, pb = min(pid,cp), max(pid,cp)
                    r = con.execute("INSERT OR IGNORE INTO person_relations (person_a,person_b,rel_type) VALUES (?,?,'codefendant')", (pa,pb))
                    if con.execute("SELECT changes()").fetchone()[0]: new_relations += 1

    # Process Tier B/C results (new case extraction from broad/stub queries)
    for item in fleet_output.get("tier_bc", []):
        data = item.get("fleet_result", {})
        if not isinstance(data, dict): continue
        for nc in (data.get("new_cases") or []):
            pname = nc.get("perpetrator_name","")
            if not pname or len(pname.split()) < 2: continue
            # Skip obvious non-names
            skip = {"Unknown","A rabbi","A Brooklyn","The rabbi","Unspecified","null","None"}
            if any(pname.startswith(s) for s in skip): continue
            iid = add_case(
                pname,
                nc.get("summary",""),
                nc.get("type","other"),
                nc.get("severity","allegation"),
                nc.get("year"),
                nc.get("location",""),
                nc.get("source_url",""),
                nc.get("amount_usd"),
                nc.get("prison_years"),
            )
            if iid:
                new_incidents += 1
                top_finds.append(pname)

    # Mark stub queries as resolved if they produced a result
    stub_batch = cycle_input.get("stub_batch", [])
    stubs = json.loads(STUB_Q.read_text()) if STUB_Q.exists() else []
    for s in stubs:
        if any(s.get("incident_id") == sb.get("incident_id") for sb in stub_batch):
            s["resolved"] = True
    STUB_Q.write_text(json.dumps(stubs, indent=2, ensure_ascii=False))

    con.commit()

    # Update state
    state = load_state()
    state["runs_completed"] = state.get("runs_completed", 0) + 1
    state["last_run_at"]    = now
    state["new_cases_found"]     = state.get("new_cases_found",0) + new_incidents
    state["new_relations_found"] = state.get("new_relations_found",0) + new_relations
    state["new_details_written"] = state.get("new_details_written",0) + new_details
    save_state(state)

    # Write result
    total_inc = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    result = {
        "cycle":         state["runs_completed"],
        "completed_at":  now,
        "new_incidents": new_incidents,
        "new_relations": new_relations,
        "new_details":   new_details,
        "total_incidents": total_inc,
        "queue_position":  state.get("queue_position",0),
        "queue_total":     state.get("queue_total",0),
        "top_finds":       top_finds[:8],
    }
    LAST_RESULT.write_text(json.dumps(result, indent=2))

    print(f"APPLY DONE: +{new_incidents} incidents, +{new_relations} relations, +{new_details} details")
    print(f"Total: {total_inc} | Queue: {state.get('queue_position',0)}/{state.get('queue_total',0)}")
    print(f"Top finds: {top_finds[:5]}")
    sys.exit(0)

# ─── SUMMARY PHASE ────────────────────────────────────────────────────────────
elif args.phase == "summary":
    if LAST_RESULT.exists():
        r = json.loads(LAST_RESULT.read_text())
        print(f"CYCLE {r['cycle']} DONE | +{r['new_incidents']} cases +{r['new_relations']} relations +{r['new_details']} details | total={r['total_incidents']} | pos={r['queue_position']}/{r['queue_total']} | finds={r['top_finds'][:5]}")
    else:
        print("No result file found")
    sys.exit(0)
