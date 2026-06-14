"""SQL-only lead generators. No API calls, no LLM. Cheap.

Generators run periodically and seed the `leads` queue with `pending` rows.
Researcher pops them. Per buildroad §"Lead generators":

    Cold-path relatives       — relatives of named perps we haven't searched
    Hot-house rosters         — full personnel sweep of 4+ incident houses
    Institution-hoppers       — same person, multiple high-severity houses
    Long-tenure anomalies     — people at one house for very long
    Amount collisions         — same dollar amount across multiple cases
    Family bridges            — families spanning hot+ cold houses

Each generator returns rows to INSERT into leads. Idempotency: leads are
deduped by (kind, payload_hash) — same lead never created twice while
status is pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_hash(kind: str, payload: dict) -> str:
    # Canonical JSON ⇒ stable hash ⇒ idempotent inserts.
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{kind}|{s}".encode()).hexdigest()[:24]


def _existing_hashes(cur: sqlite3.Cursor, kind: str) -> set[str]:
    """Hashes of leads already in queue for this kind (pending or claimed)."""
    rows = cur.execute(
        "SELECT payload_json FROM leads WHERE kind = ? AND status IN ('pending','claimed')",
        (kind,),
    ).fetchall()
    return {_payload_hash(kind, json.loads(r[0])) for r in rows}


def _insert_leads(cur: sqlite3.Cursor, kind: str, rows: list[tuple[dict, float]]) -> int:
    existing = _existing_hashes(cur, kind)
    now = _now()
    inserted = 0
    for payload, score in rows:
        if _payload_hash(kind, payload) in existing:
            continue
        cur.execute(
            "INSERT INTO leads (kind, payload_json, score, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (kind, json.dumps(payload, sort_keys=True), score, now),
        )
        inserted += 1
    return inserted


# ===========================================================================
# Generators
# ===========================================================================

def cold_path_relatives(conn: sqlite3.Connection) -> int:
    """Relatives of named perpetrators we have NOT yet searched for.

    Score: 1.0 base + 0.2 per known incident on the original perp + 0.3 if
    the perp is severity-red.
    """
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute("""
        WITH perps AS (
          SELECT DISTINCT ip.person_id
          FROM incident_people ip
          WHERE LOWER(COALESCE(ip.role,'')) IN ('perpetrator','enabler','covered_up_by')
        ),
        perp_severity AS (
          SELECT ip.person_id,
                 SUM(CASE WHEN i.severity IN ('convicted','indicted') THEN 1 ELSE 0 END) AS hard_count,
                 COUNT(*) AS incident_count
          FROM incident_people ip
          JOIN incidents i ON i.id = ip.incident_id
          WHERE LOWER(COALESCE(ip.role,'')) IN ('perpetrator','enabler','covered_up_by')
          GROUP BY ip.person_id
        )
        SELECT fr.person_a, fr.person_b, fr.relation,
               ps.hard_count, ps.incident_count
        FROM family_relations fr
        JOIN perps p ON p.person_id = fr.person_a
        JOIN perp_severity ps ON ps.person_id = fr.person_a
        LEFT JOIN incident_people relative_in_incidents
               ON relative_in_incidents.person_id = fr.person_b
        WHERE relative_in_incidents.id IS NULL    -- relative has no incidents → cold path
        LIMIT 2000
    """).fetchall()

    leads = []
    for r in rows:
        score = 1.0 + 0.2 * (r["incident_count"] or 0) + (0.3 if r["hard_count"] else 0)
        leads.append((
            {
                "perp_person_id":     r["person_a"],
                "relative_person_id": r["person_b"],
                "relation":           r["relation"],
            },
            score,
        ))
    return _insert_leads(cur, "cold_path_relative", leads)


def hot_house_rosters(conn: sqlite3.Connection, *, min_incidents: int = 4) -> int:
    """Full personnel sweep of any house with >= N documented incidents."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute("""
        SELECT h.id, h.name, COUNT(DISTINCT ih.incident_id) AS n
        FROM houses h
        JOIN incident_houses ih ON ih.house_id = h.id
        GROUP BY h.id
        HAVING n >= ?
        ORDER BY n DESC
    """, (min_incidents,)).fetchall()

    leads = []
    for r in rows:
        score = 2.0 + 0.1 * r["n"]
        leads.append((
            {"house_id": r["id"], "house_name": r["name"], "incident_count": r["n"]},
            score,
        ))
    return _insert_leads(cur, "hot_house_roster", leads)


def institution_hoppers(conn: sqlite3.Connection) -> int:
    """Same person tied to >=2 high-severity houses."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute("""
        WITH severity AS (
          SELECT ih.house_id,
                 SUM(CASE WHEN i.severity IN ('convicted','indicted') THEN 1 ELSE 0 END) AS hard_count
          FROM incident_houses ih
          JOIN incidents i ON i.id = ih.incident_id
          GROUP BY ih.house_id
          HAVING hard_count >= 1
        )
        SELECT ip.person_id, COUNT(DISTINCT ih.house_id) AS house_count,
               GROUP_CONCAT(ih.house_id) AS house_ids
        FROM incident_people ip
        JOIN incident_houses ih ON ih.incident_id = ip.incident_id
        JOIN severity s ON s.house_id = ih.house_id
        GROUP BY ip.person_id
        HAVING house_count >= 2
        LIMIT 500
    """).fetchall()

    leads = []
    for r in rows:
        score = 1.5 + 0.2 * r["house_count"]
        leads.append((
            {
                "person_id":  r["person_id"],
                "house_ids":  [int(x) for x in (r["house_ids"] or "").split(",") if x],
            },
            score,
        ))
    return _insert_leads(cur, "institution_hopper", leads)


def amount_collisions(conn: sqlite3.Connection, *, min_amount: int = 100_000) -> int:
    """Same dollar amount across multiple incidents — possible same scheme."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute("""
        SELECT amount_usd, COUNT(*) AS n, GROUP_CONCAT(id) AS ids
        FROM incidents
        WHERE amount_usd IS NOT NULL AND amount_usd >= ?
        GROUP BY amount_usd
        HAVING n >= 2
        ORDER BY amount_usd DESC
        LIMIT 200
    """, (min_amount,)).fetchall()

    leads = []
    for r in rows:
        score = 1.2 + 0.1 * r["n"]
        leads.append((
            {
                "amount_usd":    r["amount_usd"],
                "incident_ids":  [int(x) for x in r["ids"].split(",") if x],
            },
            score,
        ))
    return _insert_leads(cur, "amount_collision", leads)


def family_bridges(conn: sqlite3.Connection) -> int:
    """Families with members at >=2 hot houses — bridges across institutions."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute("""
        WITH hot AS (
          SELECT ih.house_id
          FROM incident_houses ih
          GROUP BY ih.house_id HAVING COUNT(*) >= 2
        ),
        family_houses AS (
          SELECT fm.family_id, hr.house_id
          FROM family_members fm
          JOIN house_roles hr ON hr.person_id = fm.person_id
          WHERE hr.house_id IN (SELECT house_id FROM hot)
          GROUP BY fm.family_id, hr.house_id
        )
        SELECT family_id, COUNT(DISTINCT house_id) AS n_houses,
               GROUP_CONCAT(DISTINCT house_id) AS house_ids
        FROM family_houses
        GROUP BY family_id
        HAVING n_houses >= 2
        LIMIT 200
    """).fetchall()

    leads = []
    for r in rows:
        score = 1.4 + 0.15 * r["n_houses"]
        leads.append((
            {
                "family_id":  r["family_id"],
                "house_ids":  [int(x) for x in (r["house_ids"] or "").split(",") if x],
            },
            score,
        ))
    return _insert_leads(cur, "family_bridge", leads)


# ===========================================================================
# CLI
# ===========================================================================

GENERATORS = {
    "cold_path_relatives":  cold_path_relatives,
    "hot_house_rosters":    hot_house_rosters,
    "institution_hoppers":  institution_hoppers,
    "amount_collisions":    amount_collisions,
    "family_bridges":       family_bridges,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chabad.db")
    p.add_argument("--only", nargs="+", choices=list(GENERATORS), default=list(GENERATORS))
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    totals: dict[str, int] = {}
    for name in args.only:
        n = GENERATORS[name](conn)
        totals[name] = n
        print(f"  {name:<22} +{n}")
    conn.commit()
    conn.close()

    summary = ", ".join(f"{k}={v}" for k, v in totals.items())
    print(f"\nTotal new leads: {sum(totals.values())} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
