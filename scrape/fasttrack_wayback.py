"""
Fast-track wayback bucket — these URLs are pre-filtered by chabad-slug match,
so skip LLM triage and inject directly as chabad_related=true into triage.jsonl.
"""
import json, pathlib, time, hashlib
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
SRC  = ROOT/"data/raw/searches/bucket_n_failedmessiah/index.json"
TRIAGE = ROOT/"data/triage.jsonl"

data = json.load(open(SRC))
urls = [r["url"] for r in data["results"]]
print(f"loaded {len(urls)} wayback URLs")

# Read existing triage to dedupe
seen = set()
if TRIAGE.exists():
    for line in open(TRIAGE):
        try:
            row = json.loads(line)
            seen.add(row.get("url"))
        except: pass
print(f"existing triaged URLs: {len(seen)}")

added = 0
with open(TRIAGE, "a") as f:
    for url in urls:
        if url in seen: continue
        row = {
            "url": url,
            "title": "FailedMessiah archived post (wayback)",
            "snippet": "Pre-filtered chabad/lubavitch slug match from failedmessiah.typepad.com archive",
            "engine": "wayback",
            "query": "failedmessiah_wayback",
            "is_chabad_related": True,
            "mentions_perp": False,
            "triaged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        f.write(json.dumps(row) + "\n")
        added += 1
print(f"appended {added} chabad-related rows to triage")
