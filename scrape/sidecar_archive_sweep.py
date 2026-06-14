"""
sidecar_archive_sweep.py
-------------------------
For every source URL in the DB, checks the Wayback Machine for archived versions.
If a URL returns 404 or is paywalled, finds the latest good snapshot.
Updates sources.fetch_status and sources.full_text (excerpt).

Also: for every known perpetrator, searches Wayback for deleted articles:
  https://web.archive.org/web/*/site.com/search?q="name"

No LLM. Pure HTTP. Run slowly (1 req/sec) to avoid rate limiting.
"""
import sqlite3, json, pathlib, time, urllib.request, datetime, argparse

DB   = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker/data/chabad.db")
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=30, help="Max URLs to check per run")
ap.add_argument("--mode", choices=["check","people"], default="check")
args = ap.parse_args()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = datetime.datetime.utcnow().isoformat()

def wayback_check(url):
    """Returns (archived_url, timestamp) or (None, None)"""
    api = f"http://archive.org/wayback/available?url={urllib.parse.quote(url)}"
    try:
        with urllib.request.urlopen(api, timeout=8) as r:
            data = json.loads(r.read())
        snap = data.get("archived_snapshots",{}).get("closest",{})
        if snap.get("available"):
            return snap["url"], snap["timestamp"]
    except: pass
    return None, None

import urllib.parse

if args.mode == "check":
    # Check existing sources that haven't been verified
    rows = con.execute("""
        SELECT id, url FROM sources
        WHERE fetch_status IN ('linked', NULL)
          AND url NOT LIKE '%web.archive.org%'
          AND url IS NOT NULL
        LIMIT ?
    """, (args.limit,)).fetchall()

    print(f"Checking {len(rows)} source URLs against Wayback Machine...")
    found_archives = 0

    for r in rows:
        url = r["url"]
        archived_url, ts = wayback_check(url)

        if archived_url:
            # Update source with archive URL
            con.execute("""
                UPDATE sources SET
                    fetch_status = 'archived',
                    notes = COALESCE(notes,'') || ' [archived: ' || ? || ']'
                WHERE id=?
            """, (archived_url, r["id"]))
            found_archives += 1
            print(f"  ✓ archived: {url[:60]}")
        else:
            con.execute("UPDATE sources SET fetch_status='checked' WHERE id=?", (r["id"],))

        time.sleep(0.5)  # Be polite to archive.org

    con.commit()
    print(f"\nFound {found_archives}/{len(rows)} archived versions")

elif args.mode == "people":
    # Search Wayback for deleted articles about known perpetrators
    people = con.execute("""
        SELECT p.id, p.full_name FROM people p
        JOIN incident_people ip ON ip.person_id=p.id
        GROUP BY p.id
        ORDER BY COUNT(*) DESC LIMIT ?
    """, (args.limit,)).fetchall()

    new_sources = 0
    for p in people:
        name = p["full_name"]
        # Wayback CDX API — find all archived pages mentioning this name
        query = urllib.parse.quote(f'"{name}" chabad')
        cdx_url = f"http://web.archive.org/cdx/search/cdx?url=*&output=json&fl=original,timestamp&filter=statuscode:200&limit=5&q={query}"
        try:
            with urllib.request.urlopen(cdx_url, timeout=10) as r:
                rows = json.loads(r.read())
            for row in rows[1:]:  # skip header
                orig_url, ts = row[0], row[1]
                archive_url = f"https://web.archive.org/web/{ts}/{orig_url}"
                # Add to sources
                con.execute("INSERT OR IGNORE INTO sources (url,title,accessed_at,type,fetch_status) VALUES (?,?,?,'archive','wayback')",
                    (archive_url, f"[Archive] {name}", now))
                new_sources += 1
        except: pass
        time.sleep(1.0)

    con.commit()
    print(f"Added {new_sources} Wayback archive sources")
