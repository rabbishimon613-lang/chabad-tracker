#!/usr/bin/env python3
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths
BASE = Path("/Volumes/EOS_DIGITAL/chabad-tracker")
SRC_DB = BASE / "data" / "chabad.db"
DST_DB = BASE / "ui" / "public" / "chabad.db"
VIEWS_SQL = BASE / "views.sql"
SIDECARE = BASE / "ui" / "public" / "snapshot.json"

def ensure_views(db_path: Path, sql_path: Path):
    """Re-run views.sql against the database (idempotent)."""
    try:
        with sqlite3.connect(db_path) as conn:
            with open(sql_path, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
    except Exception as e:
        sys.exit(f"Failed to apply views: {e}")

def vacuum_into(src: Path, dst: Path):
    """Create a vacuum copy of the source DB at dst."""
    try:
        with sqlite3.connect(src) as conn:
            conn.execute(f"VACUUM INTO '{dst.as_posix()}'")
    except Exception as e:
        sys.exit(f"VACUUM failed: {e}")

def gather_counts(db_path: Path):
    """Return row counts for houses, people, incidents, families."""
    query_map = {
        "houses": "SELECT COUNT(*) FROM houses;",
        "people": "SELECT COUNT(*) FROM people;",
        "incidents": "SELECT COUNT(*) FROM incidents;",
        "families": "SELECT COUNT(*) FROM families;",
    }
    counts = {}
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for key, q in query_map.items():
            try:
                cur.execute(q)
                counts[key] = cur.fetchone()[0]
            except Exception:
                counts[key] = None
    return counts

def main():
    # Ensure analytic views are present
    ensure_views(SRC_DB, VIEWS_SQL)

    # Make vacuum copy
    vacuum_into(SRC_DB, DST_DB)

    # Gather status
    status = gather_counts(SRC_DB)
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {**status, "generated_at": generated_at}

    # Print JSON summary to stdout
    print(json.dumps(status, ensure_ascii=False))

    # Write sidecar file for UI
    try:
        SIDECARE.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as e:
        sys.exit(f"Failed to write sidecar: {e}")

if __name__ == "__main__":
    main()
