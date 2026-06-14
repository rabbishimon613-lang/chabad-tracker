"""
dragnet_expand_sources.py
--------------------------
After each dragnet cycle, scan newly found source URLs and:
  1. Extract their domains
  2. Add new domains to dragnet_sources.json (if not already there)
  3. Increment hit counts on known domains
  4. Generate new broad_queries from newly discovered institutions/people
  5. Flag high-value new domains for next cycle to target specifically

Usage:
  python3 scrape/dragnet_expand_sources.py --run N

Reads:
  data/dragnet_extract_{N}.json   (fleet extraction results from cycle N)
  data/dragnet_sources.json       (current source pool)
  data/chabad.db                  (to find new institutions mentioned)

Writes:
  data/dragnet_sources.json       (updated)
  data/dragnet_next_queries.json  (fresh queries for next cycle based on discoveries)
"""

import sqlite3, json, pathlib, re, argparse
from urllib.parse import urlparse
import datetime

ROOT    = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
DB      = ROOT / "data/chabad.db"
SOURCES = ROOT / "data/dragnet_sources.json"

ap = argparse.ArgumentParser()
ap.add_argument("--run", type=int, required=True)
args = ap.parse_args()

extract_file = ROOT / f"data/dragnet_extract_{args.run}.json"
if not extract_file.exists():
    print(f"No extract file for run {args.run}")
    exit(0)

extracts = json.loads(extract_file.read_text())
sources  = json.loads(SOURCES.read_text())
known_domains = {d["domain"] for d in sources["domains"]}
now = datetime.datetime.utcnow().isoformat()

new_domains   = []
new_queries   = []
hit_counts    = {}
new_institutions = []
new_people_found = []

for ex in (extracts if isinstance(extracts, list) else [extracts]):
    if not isinstance(ex, dict): continue

    # Harvest all URLs found
    all_urls = list(ex.get("new_sources") or [])
    for nc in (ex.get("new_cases") or []):
        if nc.get("source_url"):
            all_urls.append(nc["source_url"])

    for url in all_urls:
        if not url or not url.startswith("http"): continue
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace("www.", "")
            if not domain: continue

            # Count hits on known domains
            hit_counts[domain] = hit_counts.get(domain, 0) + 1

            # Discover new domains
            if domain not in known_domains:
                # Filter out social media / generic
                skip = {"facebook.com","twitter.com","instagram.com","youtube.com",
                        "google.com","wikipedia.org","linkedin.com","amazon.com"}
                if domain not in skip:
                    new_domains.append({
                        "domain": domain,
                        "type": "discovered",
                        "priority": 5,
                        "hits": 1,
                        "note": f"Auto-discovered run {args.run} from: {url[:80]}",
                        "discovered_at": now
                    })
                    known_domains.add(domain)
                    print(f"  NEW DOMAIN: {domain}")
        except: pass

    # Extract new institutions for targeted queries
    for inst in (ex.get("related_institutions") or []):
        if isinstance(inst, str) and len(inst) > 5 and "Chabad" in inst:
            new_institutions.append(inst)
            new_queries.append(f'"{inst}" fraud abuse lawsuit crime conviction')

    # Extract new co-conspirator names for targeted queries
    for name in (ex.get("co_conspirators") or []):
        if isinstance(name, str) and len(name.split()) >= 2:
            new_people_found.append(name)
            new_queries.append(f'"{name}" Chabad Lubavitch crime fraud conviction arrested')

# Update hit counts on known domains
for d in sources["domains"]:
    if d["domain"] in hit_counts:
        d["hits"] = d.get("hits", 0) + hit_counts[d["domain"]]

# Add newly discovered domains
sources["discovered"].extend(new_domains)
sources["last_updated"] = now

# Add new broad queries (deduplicated)
existing_q = set(sources.get("broad_queries", []))
for q in new_queries:
    if q not in existing_q:
        sources["broad_queries"].append(q)
        existing_q.add(q)

SOURCES.write_text(json.dumps(sources, ensure_ascii=False, indent=2))

# Write next-cycle targeted queries
next_queries = {
    "run": args.run + 1,
    "generated_at": now,
    # Top priority domains to hit next cycle (highest priority + most hits)
    "target_domains": [
        d["domain"] for d in sorted(
            sources["domains"] + sources["discovered"],
            key=lambda x: (x.get("priority",5), x.get("hits",0)),
            reverse=True
        )[:6]
    ],
    # Fresh broad queries rotated from pool
    "broad_queries": sources["broad_queries"][-8:],  # most recently added = freshest leads
    "new_institutions": new_institutions[:5],
    "new_people": new_people_found[:10],
}
out = ROOT / f"data/dragnet_next_queries.json"
out.write_text(json.dumps(next_queries, ensure_ascii=False, indent=2))

print(f"[expand] run {args.run}: +{len(new_domains)} new domains, +{len(new_queries)} new queries")
print(f"  Top domains for next cycle: {next_queries['target_domains'][:4]}")
print(f"  New institutions queued: {new_institutions[:3]}")
print(f"  New people to hunt: {new_people_found[:5]}")
