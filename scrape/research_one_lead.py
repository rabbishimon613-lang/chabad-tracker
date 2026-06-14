"""Researcher — pops one lead, digs, writes to staging.

One run = one lead. Hard caps:
    8 searches / cycle
    40 fleet calls / cycle
    90s wall-clock / dive

Workflow:
    1. Claim a pending lead (top-scored, oldest tiebreaker).
    2. Build per-kind query.
    3. search.both(query) → up to 4 hits.
    4. fleet.chat(extraction prompt) → structured JSON with verbatim_quote.
    5. Sanity filter: every proper noun must be in input facts.
    6. Write staging_incidents row (verified=0).
    7. Mark lead resolved on success; dead on inability-to-extract.

Idempotent: a crashed cycle's `claimed_at` will be reclaimed by the next.
Never blocks. Cost-aware (raises BudgetExceeded if the per-cycle cap is hit).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import fleet, search


# ===========================================================================
# Lead claim/release
# ===========================================================================

CLAIM_TTL_MIN = 15           # >15min → silently reclaimable

EXTRACTION_SYSTEM = (
    "You are a meticulous investigative archivist. From the given search "
    "snippets, extract any DOCUMENTED incident where the named person played "
    "a PERPETRATOR role (fraud, abuse, cover-up, etc.). NEVER invent names, "
    "places, or facts. If a search hit is irrelevant or insufficient, return "
    "an empty array. You MUST output a single JSON object with shape:\n"
    "{\n"
    '  "incidents": [\n'
    "    {\n"
    '      "person_full_name": "exact name as it appears in the snippets",\n'
    '      "incident_type": "financial_fraud|sexual_abuse|trafficking|cover_up|other",\n'
    '      "severity": "allegation|investigation|charged|convicted|settled|acquitted",\n'
    '      "occurred_on": "YYYY-MM-DD or YYYY or null",\n'
    '      "location": "city, state, country (if available)",\n'
    '      "summary": "2-3 sentence factual summary",\n'
    '      "amount_usd": null,\n'
    '      "verbatim_quote": "a 10-30 word quote copied EXACTLY from one of the snippets",\n'
    '      "source_url": "the URL of the snippet the quote came from"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "If nothing actionable, return {\"incidents\": []}."
)


def _claim_lead(conn: sqlite3.Connection, lead_kind: Optional[str] = None) -> Optional[dict]:
    """Atomically claim the top-scored pending or stale-claimed lead.

    Stale = claimed >15min ago (reclaim mechanism). Returns the lead row dict.
    """
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CLAIM_TTL_MIN)).isoformat()
    where_kind = "AND kind = ?" if lead_kind else ""
    params = (cutoff, *( (lead_kind,) if lead_kind else () ))
    row = cur.execute(f"""
        SELECT id, kind, payload_json, score
        FROM leads
        WHERE (status = 'pending'
               OR (status = 'claimed' AND claimed_at < ?))
          {where_kind}
        ORDER BY score DESC, id ASC
        LIMIT 1
    """, params).fetchone()
    if row is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("UPDATE leads SET status='claimed', claimed_at=? WHERE id=?", (now, row["id"]))
    conn.commit()
    return dict(row)


def _release_lead(conn: sqlite3.Connection, lead_id: int, *, outcome: str, notes: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    if outcome == "resolved":
        cur.execute(
            "UPDATE leads SET status='resolved', resolved_at=?, notes=COALESCE(notes,'')||? WHERE id=?",
            (now, f"\n{now}: {notes}", lead_id),
        )
    elif outcome == "dead":
        cur.execute(
            "UPDATE leads SET status='dead', resolved_at=?, notes=COALESCE(notes,'')||? WHERE id=?",
            (now, f"\n{now}: {notes}", lead_id),
        )
    else:
        # back to pending — let next tick retry
        cur.execute("UPDATE leads SET status='pending', claimed_at=NULL WHERE id=?", (lead_id,))
    conn.commit()


# ===========================================================================
# Lead → query
# ===========================================================================

def _build_queries(conn: sqlite3.Connection, lead: dict) -> list[str]:
    """Per-kind query construction. Returns up to 2 queries (within the 8/cycle cap)."""
    kind = lead["kind"]
    payload = json.loads(lead["payload_json"])
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row

    if kind == "cold_path_relative":
        pid = payload.get("relative_person_id")
        if not pid:
            return []
        row = cur.execute("SELECT full_name FROM people WHERE id=?", (pid,)).fetchone()
        if not row or not row["full_name"]:
            return []
        name = row["full_name"]
        return [
            f'"{name}" chabad rabbi fraud OR abuse OR conviction',
            f'"{name}" indicted OR sentenced',
        ]

    if kind == "hot_house_roster":
        hid = payload.get("house_id")
        if not hid:
            return []
        h = cur.execute("SELECT name, city, country FROM houses WHERE id=?", (hid,)).fetchone()
        if not h:
            return []
        loc = ", ".join(filter(None, [h["city"], h["country"]]))
        return [
            f'"{h["name"]}" {loc} fraud OR abuse',
            f'rabbi "{h["name"]}" indicted OR convicted',
        ]

    if kind == "institution_hopper":
        pid = payload.get("person_id")
        if not pid:
            return []
        row = cur.execute("SELECT full_name FROM people WHERE id=?", (pid,)).fetchone()
        if not row:
            return []
        return [f'"{row["full_name"]}" chabad sentencing OR conviction']

    if kind == "amount_collision":
        amt = payload.get("amount_usd")
        if not amt:
            return []
        return [f'"${int(amt):,}" chabad fraud OR scheme']

    if kind == "family_bridge":
        fid = payload.get("family_id")
        if not fid:
            return []
        names = cur.execute(
            "SELECT p.full_name FROM family_members fm "
            "JOIN people p ON p.id = fm.person_id "
            "WHERE fm.family_id = ? LIMIT 4",
            (fid,),
        ).fetchall()
        return [f'{" OR ".join(chr(34) + n["full_name"] + chr(34) for n in names if n["full_name"])} chabad'] if names else []

    return []


# ===========================================================================
# Output sanitizer — hallucination clamp
# ===========================================================================

def _extract_json(text: str) -> Optional[dict]:
    """Robustly find the first JSON object in an LLM response."""
    if not text:
        return None
    # try fenced first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # otherwise widest braces
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _sanity_check(incident: dict, hits: list[search.SearchHit]) -> tuple[bool, str]:
    """Every proper noun in `incident` must appear in the search snippets.

    Lightweight clamp: if the LLM invented a name, the name won't be in any
    snippet → reject. Same for the verbatim_quote.
    """
    pool = " ".join((h.title or "") + " " + (h.snippet or "") + " " + (h.url or "") for h in hits).lower()
    name = (incident.get("person_full_name") or "").strip()
    if not name:
        return False, "person_full_name missing"
    if name.lower() not in pool:
        return False, "person name not in snippets — possible hallucination"
    quote = (incident.get("verbatim_quote") or "").strip()
    if not quote or len(quote.split()) < 6:
        return False, "verbatim quote missing or too short"
    if quote.lower() not in pool:
        return False, "quote not in snippets — possible hallucination"
    url = incident.get("source_url") or ""
    if url and not any(h.url == url for h in hits):
        return False, "source_url not in any snippet"
    return True, ""


# ===========================================================================
# Main
# ===========================================================================

def research(conn: sqlite3.Connection, lead: dict, *, max_seconds: int = 90) -> list[int]:
    """Run one Researcher dive. Returns list of staging_incidents.id created."""
    t0 = time.monotonic()
    queries = _build_queries(conn, lead)
    if not queries:
        _release_lead(conn, lead["id"], outcome="dead", notes="no query buildable for this lead kind")
        return []

    # Collect hits — up to 4 hits across providers per query, dedupe by URL.
    all_hits: list[search.SearchHit] = []
    for q in queries:
        if time.monotonic() - t0 > max_seconds:
            break
        all_hits.extend(search.both(q, n=3))
    # Dedup by URL.
    seen, dedup = set(), []
    for h in all_hits:
        if h.url and h.url not in seen:
            dedup.append(h); seen.add(h.url)
    if not dedup:
        _release_lead(conn, lead["id"], outcome="dead", notes="no search hits")
        return []

    snippets_for_llm = "\n\n".join(
        f"[{i+1}] {h.title}\n{h.url}\n{(h.snippet or '')[:600]}"
        for i, h in enumerate(dedup[:6])
    )
    user_msg = (
        f"Lead kind: {lead['kind']}\n"
        f"Lead payload: {lead['payload_json']}\n\n"
        f"Search snippets:\n{snippets_for_llm}"
    )

    fr = fleet.chat(system=EXTRACTION_SYSTEM, user=user_msg, response_format_json=True)
    if fr.error or not fr.text:
        _release_lead(conn, lead["id"], outcome="released", notes=f"fleet error: {fr.error}")
        return []

    parsed = _extract_json(fr.text) or {}
    incidents = parsed.get("incidents") or []
    if not incidents:
        _release_lead(conn, lead["id"], outcome="dead", notes="LLM returned no incidents")
        return []

    staging_ids: list[int] = []
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    for inc in incidents:
        ok, reason = _sanity_check(inc, dedup)
        if not ok:
            # reject silently; don't write quarantine here — staging never went live.
            continue
        cur.execute(
            "INSERT INTO staging_incidents (lead_id, payload_json, created_at, notes) "
            "VALUES (?, ?, ?, ?)",
            (lead["id"], json.dumps(inc), now, f"provider={fr.provider}"),
        )
        staging_ids.append(cur.lastrowid)
    conn.commit()

    if staging_ids:
        _release_lead(conn, lead["id"], outcome="resolved", notes=f"{len(staging_ids)} staging rows")
    else:
        _release_lead(conn, lead["id"], outcome="dead", notes="all incidents failed sanity")
    return staging_ids


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chabad.db")
    p.add_argument("--kind", help="restrict to one lead kind")
    p.add_argument("--budget-check-only", action="store_true")
    args = p.parse_args()

    if args.budget_check_only:
        b = fleet.Budget.load()
        print(f"fleet_calls={b.fleet_calls}/{fleet.MAX_FLEET_CALLS_PER_DAY}  "
              f"searches={b.searches}/{fleet.MAX_SEARCHES_PER_DAY}")
        return 0

    conn = sqlite3.connect(args.db)
    lead = _claim_lead(conn, args.kind)
    if lead is None:
        print("no leads available")
        return 0

    print(f"claimed lead #{lead['id']} kind={lead['kind']} score={lead['score']:.2f}")
    try:
        ids = research(conn, lead)
    except fleet.BudgetExceeded as e:
        _release_lead(conn, lead["id"], outcome="released", notes=str(e))
        print(f"budget exhausted: {e}")
        return 0

    if ids:
        print(f"  → wrote {len(ids)} staging row(s): {ids}")
    else:
        print(f"  → no staging rows (lead marked dead)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
