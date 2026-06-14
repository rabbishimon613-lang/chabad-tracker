"""Export snapshot.json + quarantine.json from the live DB.

This is the Phase 0/1 stopgap; the *atomic* publish ritual lands in Phase 2
(`scrape/atomic_publish.py`). For now this runs from the build script so the
deployed UI always serves fresh counts.

Outputs:
    ui/public/snapshot.json     — top-level counts the status bar reads
    ui/public/quarantine.json   — public quarantine feed (names redacted as needed)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def export(db_path: str, out_dir: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    counts = {
        "houses":    cur.execute("SELECT COUNT(*) FROM houses").fetchone()[0],
        "people":    cur.execute("SELECT COUNT(*) FROM people").fetchone()[0],
        "incidents": cur.execute("SELECT COUNT(*) FROM incidents").fetchone()[0],
        "families":  cur.execute("SELECT COUNT(*) FROM family_relations").fetchone()[0],
    }
    audit_counts = dict(
        cur.execute(
            "SELECT COALESCE(audit_status,'unaudited'), COUNT(*) "
            "FROM incidents GROUP BY audit_status"
        ).fetchall()
    )
    # Leads queue depth — surfaces in the pixel office Investigator mindbox.
    try:
        leads_pending = cur.execute(
            "SELECT COUNT(*) FROM leads WHERE status='pending'"
        ).fetchone()[0]
        leads_claimed = cur.execute(
            "SELECT COUNT(*) FROM leads WHERE status='claimed'"
        ).fetchone()[0]
    except Exception:
        leads_pending = None
        leads_claimed = None

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        **counts,
        "generated_at":  now,
        "audit":         audit_counts,
        "leads_pending": leads_pending,
        "leads_claimed": leads_claimed,
    }
    Path(out_dir, "snapshot.json").write_text(json.dumps(snapshot, indent=2))

    # Public quarantine feed — each row carries plain-English reason. Names
    # redacted when the failure was Layer 2 (name-on-page). Photos never
    # appear; this feed is text-only by design.
    q_rows = cur.execute(
        """
        SELECT q.id, q.incident_id, q.layer, q.layer_name, q.reason,
               q.redact_name, q.failed_at,
               i.type, i.severity, i.occurred_on, i.location,
               i.summary, i.audit_status
        FROM quarantine q
        JOIN incidents i ON i.id = q.incident_id
        ORDER BY q.failed_at DESC
        LIMIT 1000
        """
    ).fetchall()

    feed = []
    for r in q_rows:
        # If Layer 2 caught the row, suppress any name field that might have
        # been carried over from elsewhere. For this feed we never include
        # the perpetrator name anyway — just the incident + reason.
        feed.append({
            "id":            r["id"],
            "incident_id":   r["incident_id"],
            "layer":         r["layer"],
            "layer_name":    r["layer_name"],
            "reason":        r["reason"],
            "type":          r["type"],
            "severity":      r["severity"],
            "occurred_on":   r["occurred_on"],
            "location":      r["location"],
            "summary_preview": (r["summary"] or "")[:240] if not r["redact_name"] else None,
            "failed_at":     r["failed_at"],
            "audit_status":  r["audit_status"],
            "name_redacted": bool(r["redact_name"]),
        })
    Path(out_dir, "quarantine.json").write_text(json.dumps({
        "generated_at": now,
        "count": len(feed),
        "items": feed,
    }, indent=2))

    print(
        f"snapshot.json: {snapshot['incidents']} incidents · "
        f"quarantine.json: {len(feed)} rows · audit={audit_counts}"
    )


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chabad.db")
    p.add_argument("--out", default="ui/public")
    args = p.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    export(args.db, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
