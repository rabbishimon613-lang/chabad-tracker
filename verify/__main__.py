"""CLI: python -m verify <incident_id> [--db data/chabad.db]

Or, batch:    python -m verify --batch 50
              python -m verify --status unaudited --limit 50
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from .runner import verify_incident


def main() -> int:
    p = argparse.ArgumentParser(prog="verify")
    p.add_argument("incident_id", type=int, nargs="?", help="single incident to audit")
    p.add_argument("--db", default="data/chabad.db")
    p.add_argument("--status", default="unaudited",
                   help="audit_status to draw batch from (unaudited|passed|passed_partial)")
    p.add_argument("--batch", "--limit", dest="batch", type=int, default=0,
                   help="if set, run that many incidents from the queue")
    p.add_argument("--no-wayback", action="store_true",
                   help="skip Layer 10 (useful for tests + local dev)")
    p.add_argument("--no-persist", action="store_true",
                   help="dry-run; don't write to DB")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)

    if args.incident_id and not args.batch:
        result = verify_incident(
            conn, args.incident_id,
            persist=not args.no_persist,
            do_wayback=not args.no_wayback,
        )
        if not args.quiet:
            _report(result)
        return 0 if result.audit_status in ("passed", "passed_partial") else 1

    # Batch mode.
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id FROM incidents WHERE audit_status = ? ORDER BY id LIMIT ?",
        (args.status, args.batch or 50),
    ).fetchall()
    if not rows:
        print(f"queue '{args.status}' is empty")
        return 0

    t0 = time.monotonic()
    counts: dict[str, int] = {}
    for (incident_id,) in rows:
        result = verify_incident(
            conn, incident_id,
            persist=not args.no_persist,
            do_wayback=not args.no_wayback,
        )
        counts[result.audit_status] = counts.get(result.audit_status, 0) + 1
        if not args.quiet:
            print(f"  #{incident_id:>5} → {result.audit_status:<14}  {result.quarantine_reason or ''}")

    elapsed = int(time.monotonic() - t0)
    print(f"\nDone in {elapsed}s. " + " · ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


def _report(result) -> None:
    print(f"#{result.incident_id} → {result.audit_status}")
    if result.quarantine_reason:
        print(f"  reason: {result.quarantine_reason}")
    for r in result.layer_results:
        mark = "·" if r.skipped else ("✓" if r.passed else "✗")
        print(f"  {mark} L{r.layer} {r.name:<16} {r.reason}")


if __name__ == "__main__":
    sys.exit(main())
