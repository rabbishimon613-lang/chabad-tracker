"""
apply_enrichment.py
--------------------
Takes fleet search results (JSON file) + enrichment queue (JSON file),
uses fleet LLM output to UPDATE existing incidents with:
  - details: fuller wiki-style narrative
  - severity: upgraded if source confirms higher status
  - new sources linked
  - leads: new names/connections extracted

Usage (called by enrichment agent):
  python3 scrape/apply_enrichment.py \
      --queue data/enrichment_queue.json \
      --results path/to/fleet_results.json \
      --enrichments path/to/fleet_llm_output.json
"""

import sqlite3, json, pathlib, datetime, argparse, re

ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB   = ROOT / "data/chabad.db"

SEV_RANK = {
    "allegation":1, "investigation":2, "charged":3,
    "indicted":4, "settled":3, "convicted":6, "acquitted":0
}

ap = argparse.ArgumentParser()
ap.add_argument("--queue",       required=True, help="enrichment_queue.json")
ap.add_argument("--results",     required=True, help="fleet search results JSON")
ap.add_argument("--enrichments", required=True, help="fleet LLM enrichment JSON (parallel to queue)")
args = ap.parse_args()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

queue       = json.loads(pathlib.Path(args.queue).read_text())
results     = json.loads(pathlib.Path(args.results).read_text()).get("result", [])
enrichments = json.loads(pathlib.Path(args.enrichments).read_text())  # list of enrichment objects

def link_source(incident_id, url, title=""):
    if not url or not url.startswith("http"):
        return
    now = datetime.datetime.utcnow().isoformat()
    con.execute(
        "INSERT OR IGNORE INTO sources (url, title, accessed_at) VALUES (?,?,?)",
        (url, title or "", now)
    )
    src = con.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
    if src:
        con.execute(
            "INSERT OR IGNORE INTO incident_sources (incident_id, source_id) VALUES (?,?)",
            (incident_id, src["id"])
        )

updated = 0
sources_added = 0
leads_total = []

for i, person in enumerate(queue):
    if i >= len(enrichments):
        break

    enrich = enrichments[i]
    if not enrich or not isinstance(enrich, dict):
        continue

    inc_ids = person["incident_ids"]
    now = datetime.datetime.utcnow().isoformat()

    # --- details ---
    new_details = (enrich.get("details") or "").strip()
    if new_details:
        for iid in inc_ids:
            row = con.execute("SELECT details FROM incidents WHERE id=?", (iid,)).fetchone()
            existing = (row["details"] or "") if row else ""
            # Append if new content
            if new_details[:60].lower() not in existing.lower():
                combined = (existing + "\n\n" + new_details).strip()[:3000]
                con.execute("UPDATE incidents SET details=?, enriched_at=? WHERE id=?",
                            (combined, now, iid))
        updated += 1

    # --- severity upgrade ---
    new_sev = (enrich.get("severity") or "").strip().lower()
    if new_sev and new_sev in SEV_RANK:
        for iid in inc_ids:
            row = con.execute("SELECT severity FROM incidents WHERE id=?", (iid,)).fetchone()
            if row:
                cur_rank = SEV_RANK.get(row["severity"] or "allegation", 1)
                new_rank = SEV_RANK.get(new_sev, 1)
                if new_rank > cur_rank:
                    con.execute("UPDATE incidents SET severity=? WHERE id=?", (new_sev, iid))
                    print(f"  ↑ {person['name']}: {row['severity']} → {new_sev}")

    # --- new sources ---
    for url in (enrich.get("new_sources") or []):
        for iid in inc_ids:
            link_source(iid, url)
        sources_added += 1

    # Also add URLs from search results
    if i < len(results):
        for hit in (results[i] or []):
            url = hit.get("url","")
            title = hit.get("title","")
            for iid in inc_ids:
                link_source(iid, url, title)

    # --- leads ---
    leads = enrich.get("leads") or []
    co = enrich.get("co_conspirators") or []
    institutions = enrich.get("related_institutions") or []
    notes = enrich.get("notes") or ""

    if leads or co or institutions:
        leads_entry = {
            "person": person["name"],
            "leads": leads,
            "co_conspirators": co,
            "related_institutions": institutions,
            "notes": notes,
        }
        leads_total.append(leads_entry)
        # Write leads to incidents.leads field
        leads_json = json.dumps(leads_entry)
        for iid in inc_ids:
            con.execute("UPDATE incidents SET leads=? WHERE id=? AND leads IS NULL",
                        (leads_json, iid))

    # Mark enriched even if no new details
    for iid in inc_ids:
        con.execute("UPDATE incidents SET enriched_at=? WHERE id=? AND enriched_at IS NULL",
                    (now, iid))

con.commit()

# Save leads for next round
leads_path = ROOT / "data/enrichment_leads.json"
existing_leads = []
if leads_path.exists():
    try:
        existing_leads = json.loads(leads_path.read_text())
    except:
        pass
existing_leads.extend(leads_total)
leads_path.write_text(json.dumps(existing_leads, ensure_ascii=False, indent=2))

print(f"\n=== ENRICHMENT APPLIED ===")
print(f"People processed:     {min(len(queue), len(enrichments))}")
print(f"Incidents updated:    {updated}")
print(f"Sources added:        {sources_added}")
print(f"Lead threads found:   {len(leads_total)}")
print(f"Leads file:           {leads_path}")
print(f"DB incidents:         {con.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]}")
print(f"Enriched incidents:   {con.execute('SELECT COUNT(*) FROM incidents WHERE enriched_at IS NOT NULL').fetchone()[0]}")
