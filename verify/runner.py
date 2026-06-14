"""Verifier runner — orchestrates a single incident through the layers and
writes the result back to the DB.

Public entry:
    from verify.runner import verify_incident
    result = verify_incident(conn, incident_id)
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import layers
from .layers import IncidentRow, IncidentSource, LayerContext, LayerResult


# Hard-failing layers: if any of these return passed=False AND skipped=False,
# the incident is quarantined.
HARD_LAYERS = {1, 2, 3, 12}


@dataclass
class VerifyResult:
    incident_id: int
    audit_status: str           # passed | passed_partial | quarantined | no_source
    quarantine_reason: Optional[str] = None
    layer_results: list[LayerResult] = field(default_factory=list)

    @property
    def passed_layers(self) -> list[str]:
        return [r.name for r in self.layer_results if r.passed and not r.skipped]

    @property
    def failed_layers(self) -> list[str]:
        return [r.name for r in self.layer_results if not r.passed]

    @property
    def skipped_layers(self) -> list[str]:
        return [r.name for r in self.layer_results if r.skipped]


def _load_incident(conn: sqlite3.Connection, incident_id: int) -> IncidentRow:
    """Fetch all the verifier inputs for one incident in a single shot."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    row = cur.execute(
        "SELECT id, severity, type, location, summary, occurred_on "
        "FROM incidents WHERE id = ?",
        (incident_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"incident {incident_id} not found")

    incident = IncidentRow(
        id=row["id"],
        severity=row["severity"],
        type=row["type"],
        location=row["location"],
        summary=row["summary"],
        occurred_on=row["occurred_on"],
    )

    src_rows = cur.execute(
        """
        SELECT s.id, s.url, s.title, isrc.verbatim_quote, isrc.wayback_url
        FROM incident_sources isrc
        JOIN sources s ON s.id = isrc.source_id
        WHERE isrc.incident_id = ?
        """,
        (incident_id,),
    ).fetchall()
    incident.sources = [
        IncidentSource(
            source_id=r["id"],
            url=r["url"],
            title=r["title"],
            verbatim_quote=r["verbatim_quote"],
            wayback_url=r["wayback_url"],
        )
        for r in src_rows
        if r["url"]
    ]

    # Perpetrator names — only roles flagged as perpetrator/enabler/covered_up_by.
    # Victims/witnesses are excluded from Layer 2 name-on-page (doctrine: we
    # only verify people we're naming as actors, not surfacing victims).
    name_rows = cur.execute(
        """
        SELECT TRIM(p.full_name) AS full_name
        FROM incident_people ip
        JOIN people p ON p.id = ip.person_id
        WHERE ip.incident_id = ?
          AND LOWER(COALESCE(ip.role,'')) IN ('perpetrator','enabler','covered_up_by')
          AND TRIM(COALESCE(p.full_name,'')) != ''
        """,
        (incident_id,),
    ).fetchall()
    incident.perpetrator_names = [r["full_name"] for r in name_rows if r["full_name"]]

    return incident


def _save_result(
    conn: sqlite3.Connection,
    result: VerifyResult,
    layer_results: list[LayerResult],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    # Pull the Layer 11 score (if present) — written alongside audit_status.
    score = None
    for lr in layer_results:
        if lr.layer == 11 and isinstance(lr.details, dict):
            score = lr.details.get("score")
    cur.execute(
        "UPDATE incidents "
        "SET audit_status = ?, audit_at = ?, quarantine_reason = ?, audit_score = ? "
        "WHERE id = ?",
        (result.audit_status, now, result.quarantine_reason, score, result.incident_id),
    )

    # Append quarantine rows for any hard fail. Preserve forever; don't delete
    # prior runs ([[feedback_never_delete_originals]]).
    for lr in layer_results:
        if lr.passed or lr.skipped:
            continue
        cur.execute(
            "INSERT INTO quarantine "
            "(incident_id, layer, layer_name, reason, details, redact_name, failed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                result.incident_id,
                lr.layer,
                lr.name,
                lr.reason,
                json.dumps(lr.details, default=str),
                1 if lr.redact_name else 0,
                now,
            ),
        )

    # Persist Wayback snapshot URLs harvested by Layer 10.
    for lr in layer_results:
        if lr.layer != 10:
            continue
        for sub in lr.details.get("submissions", []):
            sid = sub.get("source_id")
            snap = sub.get("snapshot_url")
            if sid and snap:
                cur.execute(
                    "UPDATE incident_sources "
                    "SET wayback_url = ?, wayback_at = ? "
                    "WHERE incident_id = ? AND source_id = ? "
                    "  AND (wayback_url IS NULL OR wayback_url = '')",
                    (snap, now, result.incident_id, sid),
                )

    conn.commit()


def verify_incident(
    conn: sqlite3.Connection,
    incident_id: int,
    *,
    persist: bool = True,
    do_wayback: bool = True,
) -> VerifyResult:
    """Run the (Week 1 spine) layers against one incident.

    Returns a VerifyResult and (by default) writes the outcome back to the DB.
    Idempotent — re-running on a passed row will re-check liveness; if a URL
    rotted between runs, the row moves to quarantine.
    """
    incident = _load_incident(conn, incident_id)

    if not incident.sources:
        result = VerifyResult(
            incident_id=incident_id,
            audit_status="no_source",
            quarantine_reason="No source URL on file.",
        )
        if persist:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE incidents SET audit_status = ?, audit_at = ?, "
                "quarantine_reason = ? WHERE id = ?",
                (result.audit_status, now, result.quarantine_reason, incident_id),
            )
            conn.commit()
        return result

    ctx = LayerContext(incident=incident)

    # Order matters: liveness first (cheapest); name-on-page second (reuses
    # cached pages); verbatim quote third (same cache); Wayback last so all
    # the pages we *needed* are cached before we add latency from save calls.
    layer_results = [
        layers.layer_1_url_liveness(ctx),
        layers.layer_2_name_on_page(ctx),
        layers.layer_3_verbatim_quote(ctx),
        layers.layer_12_perpetrator_only(ctx),
    ]
    if do_wayback:
        layer_results.append(layers.layer_10_wayback(ctx))
    # Layer 11 synthesises the others — must run last.
    layer_results.append(layers.layer_11_confidence(layer_results))

    hard_fails = [r for r in layer_results if r.layer in HARD_LAYERS and not r.passed and not r.skipped]
    any_skipped = any(r.skipped for r in layer_results if r.layer in HARD_LAYERS)

    if hard_fails:
        status = "quarantined"
        reason = "; ".join(f"L{r.layer}: {r.reason}" for r in hard_fails)
    elif any_skipped:
        status = "passed_partial"
        reason = None
    else:
        status = "passed"
        reason = None

    result = VerifyResult(
        incident_id=incident_id,
        audit_status=status,
        quarantine_reason=reason,
        layer_results=layer_results,
    )

    if persist:
        _save_result(conn, result, layer_results)

    return result
