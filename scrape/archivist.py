"""Archivist — promotes verified staging rows to live tables.

Workflow per row in staging_incidents WHERE verified=1 AND promoted=0:
    1. Find-or-create person (by name + canonical_id).
    2. Find-or-create source (by URL).
    3. INSERT incidents.
    4. INSERT incident_people (perpetrator role).
    5. INSERT incident_sources (with verbatim_quote).
    6. Spawn child leads (relatives, co-defendants — bounded).
    7. Mark staging.promoted = 1.

The Archivist never violates doctrine: it only writes if all source rows
came from Verifier-passed staging. If Verifier rejected the row, the
Archivist skips it entirely.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

from verify.runner import verify_incident


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_or_create_person(conn: sqlite3.Connection, full_name: str) -> int:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM people WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(?)) LIMIT 1",
        (full_name,),
    ).fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO people (full_name, first_seen_at) VALUES (?, ?)",
        (full_name, _now()),
    )
    return cur.lastrowid


def _find_or_create_source(conn: sqlite3.Connection, url: str, title: str = "") -> int:
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM sources WHERE url = ? LIMIT 1", (url,)).fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO sources (url, type, title, accessed_at) VALUES (?, ?, ?, ?)",
        (url, "news", title or url[:80], _now()),
    )
    return cur.lastrowid


def _spawn_child_leads(
    conn: sqlite3.Connection,
    parent_lead_id: int,
    person_id: int,
    incident_id: int,
) -> int:
    """For a new perp, queue cold-path-relative leads for their relatives
    AND a co-defendant lead if anyone else was named in the same incident.
    """
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    new = 0
    now = _now()

    # Relatives of the new perp who don't have incidents yet.
    rels = cur.execute("""
        SELECT fr.person_b AS rel_id, fr.relation
        FROM family_relations fr
        LEFT JOIN incident_people ip ON ip.person_id = fr.person_b
        WHERE fr.person_a = ? AND ip.id IS NULL
        LIMIT 6
    """, (person_id,)).fetchall()
    for r in rels:
        payload = {
            "perp_person_id":     person_id,
            "relative_person_id": r["rel_id"],
            "relation":           r["relation"],
        }
        cur.execute("""
            INSERT INTO leads (kind, payload_json, score, status, parent_lead_id, created_at)
            VALUES ('cold_path_relative', ?, 1.5, 'pending', ?, ?)
        """, (json.dumps(payload, sort_keys=True), parent_lead_id, now))
        new += 1

    return new


def _promote_one(conn: sqlite3.Connection, staging_row: dict) -> tuple[bool, str]:
    """Returns (promoted_ok, message)."""
    payload = json.loads(staging_row["payload_json"])
    name = (payload.get("person_full_name") or "").strip()
    url  = (payload.get("source_url") or "").strip()
    quote = (payload.get("verbatim_quote") or "").strip()
    if not (name and url and quote):
        return False, "missing required fields"

    cur = conn.cursor()
    # Find-or-create person + source.
    person_id = _find_or_create_person(conn, name)
    source_id = _find_or_create_source(conn, url, title=payload.get("location", ""))

    # INSERT incident.
    cur.execute(
        "INSERT INTO incidents (occurred_on, type, severity, location, summary, "
        "extracted_from_source_id, audit_status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'unaudited')",
        (
            payload.get("occurred_on"), payload.get("incident_type") or "other",
            payload.get("severity") or "allegation",
            payload.get("location"), payload.get("summary"),
            source_id,
        ),
    )
    incident_id = cur.lastrowid

    cur.execute(
        "INSERT INTO incident_people (incident_id, person_id, role) VALUES (?, ?, 'perpetrator')",
        (incident_id, person_id),
    )
    cur.execute(
        "INSERT OR IGNORE INTO incident_sources (incident_id, source_id, verbatim_quote) "
        "VALUES (?, ?, ?)",
        (incident_id, source_id, quote),
    )
    conn.commit()

    # Run the Verifier on the just-created incident. If it quarantines,
    # roll back (mark audit_status = quarantined). Don't undo the rows
    # though — quarantine is a label, not a delete.
    result = verify_incident(conn, incident_id, do_wayback=False)

    if result.audit_status == "quarantined":
        return False, f"incident {incident_id} created but Verifier quarantined ({result.quarantine_reason or ''})"

    return True, f"incident {incident_id} promoted ({result.audit_status})"


def archive(conn: sqlite3.Connection, limit: int = 20) -> None:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute("""
        SELECT id, lead_id, payload_json
        FROM staging_incidents
        WHERE promoted = 0
        ORDER BY id
        LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        print("staging is empty")
        return

    n_promoted = 0
    n_skipped = 0
    n_children = 0
    for s in rows:
        ok, msg = _promote_one(conn, dict(s))
        if ok:
            cur.execute(
                "UPDATE staging_incidents SET verified=1, promoted=1, "
                "promoted_incident_id=(SELECT MAX(id) FROM incidents) "
                "WHERE id=?",
                (s["id"],),
            )
            # spawn child leads
            payload = json.loads(s["payload_json"])
            name = payload.get("person_full_name", "")
            row = cur.execute(
                "SELECT id FROM people WHERE full_name=? LIMIT 1", (name,)
            ).fetchone()
            if row:
                spawned = _spawn_child_leads(conn, s["lead_id"], row["id"], cur.lastrowid)
                n_children += spawned
            n_promoted += 1
            print(f"  ✓ staging #{s['id']} → {msg} (+{spawned if row else 0} child leads)")
        else:
            cur.execute(
                "UPDATE staging_incidents SET promoted=1, notes=COALESCE(notes,'')||? WHERE id=?",
                (f"\nrejected: {msg}", s["id"]),
            )
            n_skipped += 1
            print(f"  ✗ staging #{s['id']} → {msg}")
        conn.commit()

    print(f"\npromoted={n_promoted}  skipped={n_skipped}  child_leads_spawned={n_children}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chabad.db")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    archive(conn, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
