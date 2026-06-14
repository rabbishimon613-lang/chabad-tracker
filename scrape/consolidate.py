"""
Consolidate the 155 extracted incident records into canonical incidents.

Clustering: (normalized_perp_name, year_bucket, incident_type_primary)
For each cluster: pick canonical = longest summary, aggregate source URLs from members.

Output: data/raw/canonical/incidents.json
"""
import json, glob, pathlib, re, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC  = ROOT / "data" / "raw" / "extracted"
OUT_DIR = ROOT / "data" / "raw" / "canonical"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT  = OUT_DIR / "incidents.json"

TITLES = {"rabbi","rebbe","mrs","mr","ms","miss","dr","prof","reb","r"}
# Known institutional names that should NOT be treated as perpetrators
INSTITUTIONS = ["colel chabad", "agriprocessors", "merkos", "chabad of", "lubavitch",
                "friends of", "yeshivah centre", "aleph institute"]

def normalize_name(name: str) -> str:
    if not name: return ""
    n = name.lower().strip()
    n = re.sub(r"[^\w\s\-]", "", n)
    parts = [p for p in n.split() if p not in TITLES and not p.startswith("-")]
    return " ".join(parts).strip()

def is_institution(name: str) -> bool:
    n = (name or "").lower()
    return any(inst in n for inst in INSTITUTIONS)

def primary_type(t: str) -> str:
    if not t: return "unclear"
    return t.split("|")[0].split(",")[0].strip()

def year_bucket(inc) -> str:
    y = inc.get("year")
    if isinstance(y, int):  return str(y // 5 * 5)   # 5-year buckets
    d = (inc.get("date") or "")[:4]
    if d.isdigit(): return str(int(d) // 5 * 5)
    return "unknown"

def cluster_key(inc):
    return (normalize_name(inc.get("perpetrator_name","")),
            year_bucket(inc),
            primary_type(inc.get("incident_type","")))


def load():
    rows = []
    for f in sorted(SRC.glob("*.json")):
        d = json.loads(open(f).read())
        if "_error" in d: continue
        url = d.get("_url","")
        for inc in d.get("incidents", []):
            inc["_source_url"] = url
            inc["_source_title"] = d.get("_title","")
            rows.append(inc)
    return rows


def canonical(cluster):
    # Drop institutional "perpetrators" — they're affiliations, not people.
    # Keep them only if no human-named entries exist in the cluster.
    humans = [r for r in cluster if not is_institution(r.get("perpetrator_name",""))]
    cluster = humans or cluster

    # Pick record with longest summary
    best = max(cluster, key=lambda r: len(r.get("summary","") or ""))
    sources = []
    seen_urls = set()
    for r in cluster:
        u = r.get("_source_url")
        if u and u not in seen_urls:
            seen_urls.add(u)
            sources.append({"url": u, "title": r.get("_source_title","")})

    return {
        "perpetrator_name": best.get("perpetrator_name"),
        "perpetrator_role": best.get("perpetrator_role"),
        "chabad_affiliation": best.get("chabad_affiliation"),
        "location": best.get("location"),
        "year": best.get("year"),
        "date": best.get("date"),
        "incident_type": primary_type(best.get("incident_type","")),
        "incident_type_raw": best.get("incident_type"),
        "severity": best.get("severity"),
        "summary": best.get("summary"),
        "victims_count": best.get("victims_count"),
        "international_law_flag": best.get("international_law_flag", False),
        "sources": sources,
        "source_count": len(sources),
        "cluster_size": len(cluster),
    }


def main():
    rows = load()
    print(f"raw incident records: {len(rows)}")

    clusters = collections.defaultdict(list)
    for r in rows:
        clusters[cluster_key(r)].append(r)
    print(f"clusters: {len(clusters)}")

    canonical_list = [canonical(c) for c in clusters.values()]
    # Drop empty-name canonicals
    canonical_list = [c for c in canonical_list if (c.get("perpetrator_name") or "").strip()]
    canonical_list.sort(key=lambda c: (-c["source_count"], -c["cluster_size"]))

    OUT.write_text(json.dumps(canonical_list, ensure_ascii=False, indent=2))
    print(f"canonical incidents: {len(canonical_list)}")
    print(f"-> {OUT}")

    # quick stats
    multi = [c for c in canonical_list if c["cluster_size"] > 1]
    print(f"  clusters with multi-article support: {len(multi)}")
    print("  top 10 by source_count:")
    for c in canonical_list[:10]:
        print(f"    [{c['source_count']}srcs / {c['cluster_size']}arts] {c['perpetrator_name']} — {c['incident_type']} ({c['severity']})")

if __name__ == "__main__":
    main()
