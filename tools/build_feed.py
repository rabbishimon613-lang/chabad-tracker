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
        name = (r["perp_name"] or "").strip() or "(unnamed)"
        loc  = (r["location"] or "").split(",")[0].strip()
        year = (r["occurred_on"] or "")[:4]
        bits = [name, _safe(r["type"], 24).replace("_", " "), " ".join(filter(None, [loc, year]))]
        text = " · ".join(filter(None, bits))
        if r["audit_score"]:
            text += f" · score {r['audit_score']}"
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
        loc  = (r["location"] or "").split(",")[0].strip()
        year = (r["occurred_on"] or "")[:4]
        bits = [
            f"L{r['layer']}",
            _safe(r["reason"], 90),
            " · ".join(filter(None, [(r["type"] or "").replace("_", " "), loc, year])),
        ]
        text = " · ".join(filter(None, bits))
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
        is_dead = (r["status"] == "dead")
        kind_pretty = (r["kind"] or "lead").replace("_", " ")
        if is_dead:
            note = (r["notes"] or "").strip().split("\n")[-1][:80] if r["notes"] else "no detail"
            events.append({
                "at":       r["resolved_at"],
                "type":     "lead_dead",
                "category": "leads",
                "icon":     "–",
                "color":    "mute",
                "text":     f"Lead dead · {kind_pretty} · {note}",
                "details":  {"lead_id": r["id"], "kind": r["kind"]},
            })
        else:
            note = (r["notes"] or "").strip().split("\n")[-1][:80] if r["notes"] else ""
            events.append({
                "at":       r["resolved_at"],
                "type":     "lead_resolved",
                "category": "leads",
                "icon":     "▸",
                "color":    "amber",
                "text":     f"Lead resolved · {kind_pretty}{' · ' + note if note else ''}",
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
        short = (r["sha256"] or "")[:12]
        events.append({
            "at":       r["published_at"],
            "type":     "publish",
            "category": "cycles",
            "icon":     "◇",
            "color":    "mute",
            "text":     f"Publish · db-{short} → {r['snapshot_count']} incidents",
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
        dom = _domain(r["original_url"]) or "(unknown source)"
        events.append({
            "at":       r["wayback_at"],
            "type":     "wayback_save",
            "category": "routine",
            "icon":     "☆",
            "color":    "mute",
            "text":     f"Wayback snapshot stored · {dom}",
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
        bits = []
        for key, label in (("incidents", "incidents"), ("leads_pending", "leads pending"),
                            ("quarantine", "quarantine")):
            v = obj.get(key)
            if v is not None:
                bits.append(f"{v} {label}")
        text = f"Cycle #{obj.get('run_id', '?')} closed · " + " · ".join(bits)
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
