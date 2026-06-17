"""Build ui/public/feed.json — the everything-feed for /about.

Sources, all merged into one chronological stream:
    incident_filed       incidents where audit_status passed / passed_partial
    quarantined          one row per quarantine.* failure
    lead_resolved        leads resolved with non-empty result
    lead_dead            leads ended with no result
    cycle_complete       last N lines of ops/cycles.jsonl
    publish              meta_publish entries
    wayback_save         incident_sources where wayback_at is set

Each event in the JSON has:
    at        ISO timestamp (sort key)
    type      machine type, used by filter chips
    category  one of: new | quarantined | leads | cycles | routine
    icon      single char shown on the row
    color     ok | bad | amber | mute
    text      one-line summary
    link      optional, e.g. "#incident=1443"
    details   optional dict for hover
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


# Cap per source so we don't blow up the JSON; client sorts to a global top-N.
PER_SOURCE_CAP = 60
GLOBAL_CAP = 250


# ---------------------------------------------------------------------------
# Voice — every event reads like a newsroom dispatch in plain English.
# No raw IDs (run_id, sha), no L# codes, no snake_case, no ISO blobs in text.
# ---------------------------------------------------------------------------

CRIME_PRETTY = {
    "sexual_abuse":      "sexual abuse",
    "financial_fraud":   "financial fraud",
    "cover_up":          "cover-up",
    "money_laundering":  "money laundering",
    "tax_evasion":       "tax evasion",
    "immigration_fraud": "immigration fraud",
    "drug_trafficking":  "drug trafficking",
    "child_exploitation":"child exploitation",
    "child_abuse":       "child abuse",
    "extortion_coercion":"extortion / coercion",
    "assault":           "assault",
    "other":             None,   # unclassified — skip crime adjective
}

LEAD_KIND_PRETTY = {
    "hot_house_roster":   "Chabad personnel sweep",
    "hot-house-roster":   "Chabad personnel sweep",
    "cold_path_relative": "relative-of-known-perp trace",
    "cold-path-relative": "relative-of-known-perp trace",
    "cold_path_codef":    "co-defendant trace",
    "cold-path-codef":    "co-defendant trace",
    "hot_codef":          "co-defendant follow-up",
    "hot-codef":          "co-defendant follow-up",
}

def _crime(s):
    if not s: return None
    if s in CRIME_PRETTY: return CRIME_PRETTY[s]
    return s.replace("_", " ").replace("-", " ")

def _lead_kind(s):
    if not s: return "a tip"
    return LEAD_KIND_PRETTY.get(s, s.replace("_", " ").replace("-", " "))

def _place_year(loc, occ):
    """Render 'Crown Heights, 2018' or 'Crown Heights' or '2018' or ''."""
    city = (loc or "").split(",")[0].strip()
    year = (occ or "")[:4]
    parts = [p for p in (city, year) if p]
    return ", ".join(parts)

def _humanize_reason(reason):
    """Quarantine reasons are already English. Lowercase the first letter,
    drop the trailing period so it embeds in a larger sentence."""
    if not reason: return ""
    r = reason.strip()
    if r and r[0].isupper():
        r = r[0].lower() + r[1:]
    return r.rstrip(".")


def _safe(s, n=120):
    if s is None:
        return ""
    return str(s)[:n]


def _domain(url):
    try:
        d = urlparse(url).netloc
        return d.lstrip("www.")
    except Exception:
        return ""


# ===========================================================================
# Source queries — each returns a list[dict] of events
# ===========================================================================

def q_incidents_filed(cur):
    rows = cur.execute(f"""
        SELECT i.id, i.audit_at, i.audit_status, i.audit_score,
               i.type, i.severity, i.occurred_on, i.location, i.summary,
               (SELECT TRIM(p.full_name)
                  FROM incident_people ip
                  JOIN people p ON p.id = ip.person_id
                 WHERE ip.incident_id = i.id
                   AND LOWER(COALESCE(ip.role,'')) = 'perpetrator'
                 LIMIT 1) AS perp_name
        FROM incidents i
        WHERE i.audit_status IN ('passed', 'passed_partial')
          AND i.audit_at IS NOT NULL
        ORDER BY i.audit_at DESC
        LIMIT {PER_SOURCE_CAP}
    """).fetchall()
    events = []
    for r in rows:
        name  = (r["perp_name"] or "").strip()
        who   = name or "an unnamed person"
        crime = _crime(r["type"])
        where = _place_year(r["location"], r["occurred_on"])
        text  = f"Archivist closed the file on {who}."
        crime_cap = crime[0].upper() + crime[1:] if crime else None
        tail  = " — ".join(filter(None, [crime_cap, where]))
        if tail:
            text += f" {tail}."
        if r["audit_score"]:
            text += f" Confidence: {r['audit_score']}/100."
        events.append({
            "at":       r["audit_at"],
            "type":     "incident_filed",
            "category": "new",
            "icon":     "✓",
            "color":    "ok",
            "text":     text,
            "link":     f"#incident={r['id']}",
            "details": {
                "incident_id": r["id"],
                "audit_status": r["audit_status"],
                "audit_score": r["audit_score"],
            },
        })
    return events


def q_quarantined(cur):
    rows = cur.execute(f"""
        SELECT q.id, q.incident_id, q.layer, q.layer_name, q.reason,
               q.redact_name, q.failed_at,
               i.type, i.severity, i.occurred_on, i.location
        FROM quarantine q
        JOIN incidents i ON i.id = q.incident_id
        ORDER BY q.failed_at DESC
        LIMIT {PER_SOURCE_CAP}
    """).fetchall()
    events = []
    for r in rows:
        crime  = _crime(r["type"])
        where  = _place_year(r["location"], r["occurred_on"])
        reason = _humanize_reason(r["reason"])
        if crime:
            text = f"Verifier set aside one {crime} row"
        else:
            text = "Verifier set aside one row"
        if where:
            text += f" from {where}"
        text += f" — {reason}." if reason else "."
        events.append({
            "at":       r["failed_at"],
            "type":     "quarantined",
            "category": "quarantined",
            "icon":     "✗",
            "color":    "bad",
            "text":     text,
            "details": {
                "layer":     r["layer"],
                "layer_name": r["layer_name"],
                "redacted":  bool(r["redact_name"]),
            },
        })
    return events


def q_lead_transitions(cur):
    try:
        rows = cur.execute(f"""
            SELECT id, kind, status, score, resolved_at, notes
            FROM leads
            WHERE resolved_at IS NOT NULL
            ORDER BY resolved_at DESC
            LIMIT {PER_SOURCE_CAP}
        """).fetchall()
    except sqlite3.OperationalError:
        return []
    events = []
    for r in rows:
        kind = _lead_kind(r["kind"])
        if r["status"] == "dead":
            text = f"Investigator's {kind} came up empty."
            events.append({
                "at":       r["resolved_at"],
                "type":     "lead_dead",
                "category": "leads",
                "icon":     "–",
                "color":    "mute",
                "text":     text,
                "details":  {"lead_id": r["id"], "kind": r["kind"]},
            })
        else:
            text = f"Researcher closed out a {kind}."
            events.append({
                "at":       r["resolved_at"],
                "type":     "lead_resolved",
                "category": "leads",
                "icon":     "▸",
                "color":    "amber",
                "text":     text,
                "details":  {"lead_id": r["id"], "kind": r["kind"]},
            })
    return events


def q_publishes(cur):
    try:
        rows = cur.execute(f"""
            SELECT sha256, snapshot_count, published_at, cycle_id
            FROM meta_publish
            ORDER BY published_at DESC
            LIMIT {PER_SOURCE_CAP}
        """).fetchall()
    except sqlite3.OperationalError:
        return []
    events = []
    for r in rows:
        events.append({
            "at":       r["published_at"],
            "type":     "publish",
            "category": "cycles",
            "icon":     "◇",
            "color":    "mute",
            "text":     f"Publisher sent a new edition to press — {r['snapshot_count']} stories on the wire.",
            "details":  {"sha": r["sha256"], "cycle_id": r["cycle_id"]},
        })
    return events


def q_waybacks(cur):
    try:
        rows = cur.execute(f"""
            SELECT isrc.wayback_at, isrc.wayback_url, s.url AS original_url
            FROM incident_sources isrc
            JOIN sources s ON s.id = isrc.source_id
            WHERE isrc.wayback_at IS NOT NULL
            ORDER BY isrc.wayback_at DESC
            LIMIT {PER_SOURCE_CAP}
        """).fetchall()
    except sqlite3.OperationalError:
        return []
    events = []
    for r in rows:
        dom = _domain(r["original_url"]) or "an unknown source"
        events.append({
            "at":       r["wayback_at"],
            "type":     "wayback_save",
            "category": "routine",
            "icon":     "☆",
            "color":    "mute",
            "text":     f"Tucked a copy of {dom} into the Wayback Machine before it could disappear.",
            "details":  {"original": r["original_url"], "snapshot": r["wayback_url"]},
        })
    return events


def read_cycles_jsonl(path: Path):
    """Tail the cycles log; each line is one cycle_complete event."""
    if not path.exists():
        return []
    lines = path.read_text(errors="ignore").splitlines()[-PER_SOURCE_CAP:]
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        at = obj.get("at")
        if not at:
            continue
        inc  = obj.get("incidents")
        lp   = obj.get("leads_pending")
        quar = obj.get("quarantine")
        parts = []
        if inc  is not None: parts.append(f"archive at {inc:,}")
        if lp   is not None: parts.append(f"{lp} tip{'s' if lp != 1 else ''} on the desk")
        if quar is not None: parts.append(f"{quar} row{'s' if quar != 1 else ''} set aside")
        text = "The shift wrapped: " + ", ".join(parts) + "."
        events.append({
            "at":       at,
            "type":     "cycle_complete",
            "category": "cycles",
            "icon":     "↻",
            "color":    "mute",
            "text":     text,
            "details":  obj,
        })
    return events


# ===========================================================================
# Main
# ===========================================================================

def build(db_path: str, cycles_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    events = []
    events += q_incidents_filed(cur)
    events += q_quarantined(cur)
    events += q_lead_transitions(cur)
    events += q_publishes(cur)
    events += q_waybacks(cur)
    events += read_cycles_jsonl(cycles_path)

    # Sort newest first, cap globally so the JSON stays light.
    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    events = events[:GLOBAL_CAP]

    # Per-category counts for the chip badges.
    counts = {"all": len(events)}
    for e in events:
        c = e.get("category", "routine")
        counts[c] = counts.get(c, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts":       counts,
        "events":       events,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chabad.db")
    p.add_argument("--out", default="ui/public/feed.json")
    p.add_argument("--cycles", default="ops/cycles.jsonl",
                   help="path to the cycle log JSONL")
    args = p.parse_args()
    out = build(args.db, Path(args.cycles))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"feed.json: {out['counts']['all']} events · {out['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
