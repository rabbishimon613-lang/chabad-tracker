"""
dragnet_cycle.py
-----------------
Master orchestrator for the overnight dragnet.
Handles pre-search setup and post-search processing,
including all sidecars wired in at the right moments.

Usage:
  python3 scrape/dragnet_cycle.py --phase pre
  python3 scrape/dragnet_cycle.py --phase post --results data/cycle_results.json --extracts data/cycle_extracts.json

--phase pre:
  1. Run sidecar_doj_rss.py (free, real-time DOJ/FBI cases)
  2. Run sidecar_hot_pursuit.py (inject hot leads)
  3. Build search payload for this cycle (hot queue first, then regular queue)
  4. Write data/cycle_payload.json  ← Claude reads this to call fleet

--phase post:
  1. Run dragnet_apply.py (core DB writes)
  2. Run dragnet_expand_sources.py (learn new domains)
  3. Run sidecar_extract_numbers.py (refresh amounts/prison terms)
  4. Every 3 cycles: sidecar_archive_sweep.py --limit 15
  5. Every 5 cycles: sidecar_entity_resolution.py
  6. Every 8 cycles: sidecar_wikipedia.py
  7. Every 5 cycles: sidecar_severity_tracker.py --generate-queries
  8. Print summary stats
"""

import subprocess, sys, json, pathlib, sqlite3, datetime, argparse

ROOT   = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB     = ROOT / "data/chabad.db"
STATE  = ROOT / "data/dragnet_state.json"
HOT    = ROOT / "data/dragnet_hot_queue.json"
PAYLOAD = ROOT / "data/cycle_payload.json"
SCRAPE  = ROOT / "scrape"

ap = argparse.ArgumentParser()
ap.add_argument("--phase", choices=["pre","post"], required=True)
ap.add_argument("--results",  default=str(ROOT / "data/cycle_results.json"))
ap.add_argument("--extracts", default=str(ROOT / "data/cycle_extracts.json"))
ap.add_argument("--batch-size", type=int, default=15, help="People per cycle")
args = ap.parse_args()

def run(script, extra_args=[]):
    """Run a sidecar script, capturing output. Returns (returncode, stdout)"""
    cmd = [sys.executable, str(SCRAPE / script)] + extra_args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    out = result.stdout.strip()
    if out:
        for line in out.splitlines():
            print(f"  [{script}] {line}")
    if result.returncode != 0 and result.stderr:
        print(f"  [{script}] STDERR: {result.stderr[:300]}")
    return result.returncode, out

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"queue_position": 0, "total_processed": 0, "new_cases_found": 0,
            "new_relations_found": 0, "new_details_written": 0, "runs_completed": 0,
            "started_at": None, "last_run_at": None, "log": []}

def save_state(s):
    STATE.write_text(json.dumps(s, indent=2))

now = datetime.datetime.utcnow().isoformat()
state = load_state()
cycle_n = state.get("runs_completed", 0)

# ─────────────────────────────────────────────
# PRE PHASE
# ─────────────────────────────────────────────
if args.phase == "pre":
    print(f"\n{'='*60}")
    print(f"DRAGNET PRE-PHASE  cycle={cycle_n+1}  {now[:19]}")
    print(f"{'='*60}")

    # 1. DOJ/FBI RSS — free real-time cases, always run
    print("\n[1/3] DOJ/FBI RSS sweep...")
    run("sidecar_doj_rss.py")

    # 2. Hot pursuit — inject newly discovered leads at front of queue
    print("\n[2/3] Hot pursuit queue injection...")
    run("sidecar_hot_pursuit.py")

    # 3. Build search payload
    print("\n[3/3] Building search payload...")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Load sources/queries
    sources_file = ROOT / "data/dragnet_sources.json"
    sources_data = json.loads(sources_file.read_text()) if sources_file.exists() else {}
    domains      = sources_data.get("domains", [])
    broad_q      = sources_data.get("broad_queries", [])

    # Hot queue takes priority
    hot_queue = json.loads(HOT.read_text()) if HOT.exists() else []
    hot_batch = hot_queue[:args.batch_size]
    # Remove served entries from hot queue
    HOT.write_text(json.dumps(hot_queue[args.batch_size:], indent=2, ensure_ascii=False))

    # Fill remaining slots from regular people queue
    regular_batch = []
    if len(hot_batch) < args.batch_size:
        needed = args.batch_size - len(hot_batch)
        pos = state.get("queue_position", 0)

        # Build people queue: incident-linked people, ordered by:
        # 1. unenriched first, 2. high severity, 3. position
        people_rows = con.execute("""
            SELECT p.id, p.full_name,
                   GROUP_CONCAT(DISTINCT i.type) as types,
                   MAX(CASE i.severity
                       WHEN 'convicted' THEN 6 WHEN 'indicted' THEN 5
                       WHEN 'charged' THEN 4 WHEN 'investigation' THEN 3
                       WHEN 'settled' THEN 3 WHEN 'allegation' THEN 2 ELSE 1
                   END) as sev_rank,
                   MAX(CASE WHEN i.details IS NULL OR i.details='' THEN 1 ELSE 0 END) as needs_enrich,
                   COUNT(DISTINCT i.id) as n_incidents
            FROM people p
            JOIN incident_people ip ON ip.person_id = p.id
            JOIN incidents i ON i.id = ip.incident_id
            WHERE p.full_name NOT LIKE '%[MERGED%'
            GROUP BY p.id
            ORDER BY needs_enrich DESC, sev_rank DESC, p.id
        """).fetchall()

        total = len(people_rows)
        if pos >= total:
            pos = 0  # wrap around

        slice_ = people_rows[pos:pos + needed]
        for row in slice_:
            regular_batch.append({
                "id":    row["id"],
                "name":  row["full_name"],
                "types": row["types"] or "other",
                "hot":   False,
                "query": f'"{row["full_name"]}" Chabad Lubavitch crime fraud convicted sentenced',
            })
        state["queue_position"] = pos + len(slice_)
        state["queue_total"]    = total

    batch = hot_batch + regular_batch
    print(f"  Batch: {len(hot_batch)} hot + {len(regular_batch)} regular = {len(batch)} people")

    # Build broad query batch (rotate through them)
    broad_idx = cycle_n % max(len(broad_q), 1)
    broad_selected = broad_q[broad_idx:broad_idx+3] if broad_q else []

    # Build domain-targeted queries from top 5 domains by hit count
    top_domains = sorted(domains, key=lambda d: d.get("hit_count",0), reverse=True)[:5]
    domain_q = []
    for p in batch[:5]:
        for d in top_domains[:1]:
            domain_q.append({
                "query": f'site:{d["domain"]} "{p["name"]}"',
                "person_id": p["id"],
                "person_name": p["name"],
                "source": "domain-targeted",
            })

    # Assemble final payload
    payload = {
        "cycle": cycle_n + 1,
        "generated_at": now,
        "people_batch": batch,
        "people_queries": [
            {"query": p["query"], "person_id": p["id"], "person_name": p["name"], "hot": p.get("hot", False)}
            for p in batch
        ],
        "broad_queries": [
            {"query": q, "source": "broad"} for q in broad_selected
        ],
        "domain_queries": domain_q,
        "all_queries": (
            [{"query": p["query"], "person_id": p.get("id"), "person_name": p["name"]} for p in batch]
            + [{"query": q, "source": "broad"} for q in broad_selected]
        ),
        "people_file": str(ROOT / "data/dragnet_people_cycle.json"),
    }

    # Write people file (for dragnet_apply.py)
    pathlib.Path(payload["people_file"]).write_text(
        json.dumps(batch, indent=2, ensure_ascii=False)
    )

    PAYLOAD.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"  Total queries in payload: {len(payload['all_queries'])}")
    print(f"  Payload written to: {PAYLOAD}")
    print(f"\nPRE-PHASE COMPLETE — ready for fleet search")

# ─────────────────────────────────────────────
# POST PHASE
# ─────────────────────────────────────────────
elif args.phase == "post":
    print(f"\n{'='*60}")
    print(f"DRAGNET POST-PHASE  cycle={cycle_n+1}  {now[:19]}")
    print(f"{'='*60}")

    results_file  = pathlib.Path(args.results)
    extracts_file = pathlib.Path(args.extracts)

    # 1. Core DB writes
    if results_file.exists() and extracts_file.exists():
        print("\n[1] dragnet_apply.py — writing to DB...")
        rc, out = run("dragnet_apply.py", [
            "--results",  str(results_file),
            "--people",   str(ROOT / "data/dragnet_people_cycle.json"),
            "--extracts", str(extracts_file),
        ])
        if rc != 0:
            print("  *** dragnet_apply.py FAILED — skipping downstream steps")
    else:
        print(f"  WARN: results or extracts file missing — skipping apply")

    # 2. Expand source pool (learn new domains from this cycle)
    print("\n[2] dragnet_expand_sources.py — growing source pool...")
    run("dragnet_expand_sources.py", ["--run", str(cycle_n + 1)])

    # 3. Extract numbers (always — fast pure-python)
    print("\n[3] sidecar_extract_numbers.py — refreshing amounts/terms...")
    run("sidecar_extract_numbers.py")

    # 4. Archive sweep — every 3 cycles
    if cycle_n % 3 == 0:
        print(f"\n[4] sidecar_archive_sweep.py — Wayback check (cycle {cycle_n+1})...")
        run("sidecar_archive_sweep.py", ["--limit", "15", "--mode", "check"])

    # 5. Entity resolution — every 5 cycles
    if cycle_n % 5 == 0:
        print(f"\n[5] sidecar_entity_resolution.py — dedup people (cycle {cycle_n+1})...")
        run("sidecar_entity_resolution.py")

    # 6. Wikipedia — every 8 cycles
    if cycle_n % 8 == 0:
        print(f"\n[6] sidecar_wikipedia.py — citation mining (cycle {cycle_n+1})...")
        run("sidecar_wikipedia.py")

    # 7. Severity tracker queries — every 5 cycles
    if cycle_n % 5 == 0:
        print(f"\n[7] sidecar_severity_tracker.py — generating upgrade queries (cycle {cycle_n+1})...")
        run("sidecar_severity_tracker.py", ["--generate-queries"])

    # 8b. Stub resolver — every cycle (fast tiers 1+3, URL tier capped at 20)
    print(f"\n[8b] sidecar_stub_resolver.py — triangulating unlinked stubs...")
    run("sidecar_stub_resolver.py", ["--limit", "20"])

    # 8. Update state
    state["runs_completed"] = cycle_n + 1
    state["last_run_at"]    = now
    save_state(state)

    # 9. Print summary
    con = sqlite3.connect(DB)
    print(f"\n{'─'*40}")
    print(f"DB SNAPSHOT after cycle {cycle_n+1}:")
    print(f"  incidents : {con.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]}")
    not_merged = con.execute("SELECT COUNT(*) FROM people WHERE full_name NOT LIKE '%[MERGED%'").fetchone()[0]
    print(f"  people    : {not_merged}")
    print(f"  sources   : {con.execute('SELECT COUNT(*) FROM sources').fetchone()[0]}")
    print(f"  relations : {con.execute('SELECT COUNT(*) FROM person_relations').fetchone()[0]}")
    enriched = con.execute("SELECT COUNT(*) FROM incidents WHERE enriched_at IS NOT NULL").fetchone()[0]
    total    = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    print(f"  enriched  : {enriched}/{total} ({100*enriched//max(total,1)}%)")
    sevs = con.execute("SELECT severity, COUNT(*) FROM incidents GROUP BY severity ORDER BY COUNT(*) DESC").fetchall()
    print(f"  severity  : {dict(sevs)}")
    print(f"{'─'*40}")
    print(f"POST-PHASE COMPLETE")
