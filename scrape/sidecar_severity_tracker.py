"""
sidecar_severity_tracker.py
-----------------------------
Searches for outcome updates on pending cases (charged/investigation/allegation).
Writes updated severity back to DB. No manual review needed for clear upgrades
(e.g. article says "convicted" for someone we have as "charged").

Reads search results from: data/severity_search_results.json
(populated by dragnet or a dedicated search_batch call)

Usage:
  python3 scrape/sidecar_severity_tracker.py --results data/severity_search_{N}.json

Or standalone — generates its own query list for the next fleet run:
  python3 scrape/sidecar_severity_tracker.py --generate-queries
"""
import sqlite3, json, re, pathlib, datetime, argparse

DB    = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db")
ROOT  = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")

SEV_RANK = {"allegation":1,"investigation":2,"charged":3,"indicted":4,"settled":3,"convicted":6,"acquitted":0}
SEV_KEYWORDS = {
    "convicted": ["convicted","conviction","found guilty","guilty verdict","pled guilty","pleaded guilty","guilty plea"],
    "sentenced": ["sentenced to","sentenced him","sentenced her","years in prison","months in prison","years in custody"],
    "acquitted": ["acquitted","not guilty","charges dropped","case dismissed","charges dismissed"],
    "indicted":  ["indicted","indictment","grand jury"],
    "charged":   ["charged with","faces charges","arraigned"],
}

ap = argparse.ArgumentParser()
ap.add_argument("--results", help="Path to search results JSON")
ap.add_argument("--generate-queries", action="store_true")
args = ap.parse_args()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = datetime.datetime.utcnow().isoformat()

if args.generate_queries:
    # Find all people with pending severity who haven't been severity-checked recently
    pending = con.execute("""
        SELECT p.id, p.full_name,
            MAX(CASE i.severity WHEN 'charged' THEN 3 WHEN 'investigation' THEN 2 WHEN 'allegation' THEN 1 ELSE 0 END) as max_pending,
            GROUP_CONCAT(DISTINCT i.type) as types,
            MAX(i.occurred_on) as last_date
        FROM people p
        JOIN incident_people ip ON ip.person_id=p.id
        JOIN incidents i ON i.id=ip.incident_id
        WHERE i.severity IN ('charged','investigation','allegation','indicted')
          AND p.full_name NOT LIKE '%Unnamed%'
        GROUP BY p.id
        ORDER BY max_pending DESC
        LIMIT 50
    """).fetchall()

    queries = []
    for r in pending:
        name = r["full_name"]
        queries.append({
            "person_id": r["id"],
            "name": name,
            "current_severity": ["allegation","investigation","charged"][min(r["max_pending"]-1,2)],
            "query": f'"{name}" convicted sentenced verdict outcome result Chabad'
        })

    out = ROOT / "data/severity_pending_queries.json"
    out.write_text(json.dumps(queries, indent=2, ensure_ascii=False))
    print(f"Generated {len(queries)} severity-check queries → {out}")
    print("Next: run search_batch on these, then: python3 scrape/sidecar_severity_tracker.py --results data/severity_results.json")
    exit(0)

# Process results
if not args.results:
    print("Need --results or --generate-queries")
    exit(1)

results_file = pathlib.Path(args.results)
if not results_file.exists():
    print(f"File not found: {results_file}")
    exit(0)

data = json.loads(results_file.read_text())
queries = json.loads((ROOT / "data/severity_pending_queries.json").read_text())
results_list = data.get("result", data) if isinstance(data, dict) else data

upgraded = 0
for i, person in enumerate(queries):
    if i >= len(results_list): break
    hits = results_list[i] if isinstance(results_list[i], list) else []

    pid = person["person_id"]
    cur_sev = person["current_severity"]
    cur_rank = SEV_RANK.get(cur_sev, 1)

    # Check all hit content for severity keywords
    all_text = " ".join([
        (h.get("content") or h.get("snippet") or "")[:500]
        for h in hits
    ]).lower()

    best_new_sev = cur_sev
    best_new_rank = cur_rank

    if any(kw in all_text for kw in SEV_KEYWORDS["convicted"] + SEV_KEYWORDS["sentenced"]):
        if SEV_RANK["convicted"] > best_new_rank:
            best_new_sev = "convicted"
            best_new_rank = SEV_RANK["convicted"]
    elif any(kw in all_text for kw in SEV_KEYWORDS["acquitted"]):
        best_new_sev = "acquitted"
        best_new_rank = 0
    elif any(kw in all_text for kw in SEV_KEYWORDS["indicted"]):
        if SEV_RANK["indicted"] > best_new_rank:
            best_new_sev = "indicted"
            best_new_rank = SEV_RANK["indicted"]

    if best_new_sev != cur_sev:
        # Upgrade all incidents for this person
        con.execute("""
            UPDATE incidents SET severity=?, notes=COALESCE(notes,'')||' [severity auto-upgraded '||?||' → '||?||' via tracker]'
            WHERE id IN (SELECT incident_id FROM incident_people WHERE person_id=?)
              AND severity = ?
        """, (best_new_sev, cur_sev, best_new_sev, pid, cur_sev))
        print(f"  ↑ {person['name']}: {cur_sev} → {best_new_sev}")
        upgraded += 1

    # Add new source URLs found
    for h in hits:
        url = h.get("url","")
        if url and url.startswith("http"):
            con.execute("INSERT OR IGNORE INTO sources (url, title, accessed_at, type) VALUES (?,?,?,'news')",
                (url, h.get("title","")[:200], now))
            src = con.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
            if src:
                for inc in con.execute("SELECT incident_id FROM incident_people WHERE person_id=?", (pid,)):
                    con.execute("INSERT OR IGNORE INTO incident_sources (incident_id,source_id) VALUES (?,?)",
                        (inc[0], src["id"]))

con.commit()
print(f"\nSeverity upgrades: {upgraded}/{len(queries)} people checked")
