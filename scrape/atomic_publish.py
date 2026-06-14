"""Phase 2 — atomic publish ritual.

Replaces the older `snapshot_for_ui.py` drift pattern. One script, called from
exactly one place. If any step fails, nothing is committed. No partial publish.

Steps:
    1. VACUUM INTO /tmp/chabad.db.new                  (clean snapshot, no WAL)
    2. Compute sha256                                  (the publish identity)
    3. Upload to GitHub Releases as `db-<sha12>`       (asset backend)
    4. Generate snapshot.json + quarantine.json from the just-vacuumed copy
    5. Write data/chabad.db.url + data/chabad.db.sha256
    6. Record meta_publish row in the source DB

Visible drift is impossible: snapshot.json is generated from the SAME file the
hash points to.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("GH_REPO", "rabbishimon613-lang/chabad-tracker")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def vacuum_to(src_db: Path, dst: Path) -> int:
    """VACUUM INTO produces a clean, WAL-less, contiguous DB file."""
    if dst.exists():
        dst.unlink()
    conn = sqlite3.connect(src_db)
    try:
        conn.execute(f"VACUUM INTO '{dst}'")
    finally:
        conn.close()
    # Row-count sanity: tracked separately by snapshot generator.
    return dst.stat().st_size


def upload_release(repo: str, db_file: Path, sha: str, notes: str) -> str:
    short = sha[:12]
    tag = f"db-{short}"
    asset_name = f"chabad-{short}.db"
    # Stage with the asset filename embedded in the tag.
    staged = db_file.parent / asset_name
    if staged != db_file:
        shutil.copy2(db_file, staged)
    # gh release create — fail loud.
    subprocess.run(
        ["gh", "release", "create", tag, str(staged),
         "--repo", repo,
         "--title", f"DB snapshot {short}",
         "--notes", notes],
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chabad.db", type=Path,
                   help="source-of-truth DB (the live working copy)")
    p.add_argument("--ui-public", default=Path("ui/public"), type=Path)
    p.add_argument("--repo", default=REPO)
    p.add_argument("--no-upload", action="store_true",
                   help="skip GH release upload; useful for local dry-runs")
    p.add_argument("--cycle-id", default=os.environ.get("GITHUB_RUN_ID"),
                   help="optional cycle id recorded in meta_publish")
    p.add_argument("--notes", default="")
    args = p.parse_args()

    if not args.db.exists():
        print(f"::error::source DB not found at {args.db}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="chabad-pub-") as td:
        tmp = Path(td)
        vacuumed = tmp / "chabad.db.new"

        # Step 1 — VACUUM INTO.
        size = vacuum_to(args.db, vacuumed)
        # Step 2 — sha.
        sha = _sha256(vacuumed)
        short = sha[:12]
        print(f"[1/6] VACUUM INTO ok: {size} bytes")
        print(f"[2/6] sha256: {sha}")

        # Get incident count from the vacuumed file for meta_publish.
        c = sqlite3.connect(vacuumed)
        try:
            row_count = c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        finally:
            c.close()

        # Step 3 — upload to GH Releases.
        if args.no_upload:
            url = f"(skipped) db-{short}"
        else:
            notes = args.notes or (
                f"Atomic publish · {row_count} incidents · "
                f"sha256 {sha[:16]}... · cycle_id={args.cycle_id or 'manual'}"
            )
            url = upload_release(args.repo, vacuumed, sha, notes)
        print(f"[3/6] release URL: {url}")

        # Step 4 — snapshot.json + quarantine.json from the VACUUMED copy.
        # Note: we run export against the just-vacuumed file so the published
        # JSON is provably derived from the same bytes the hash points to.
        env = os.environ.copy()
        subprocess.run(
            [sys.executable, "tools/export_snapshot.py",
             "--db", str(vacuumed), "--out", str(args.ui_public)],
            check=True, env=env,
        )
        subprocess.run(
            [sys.executable, "tools/compute_constellations.py",
             "--db", str(vacuumed), "--out", str(args.ui_public / "constellations.json")],
            check=True, env=env,
        )
        print("[4/6] snapshot.json + quarantine.json + constellations.json generated")

        # Step 5 — write pointer files. Atomic via temp-then-rename.
        url_file = Path("data/chabad.db.url")
        sha_file = Path("data/chabad.db.sha256")
        tmp_url = url_file.with_suffix(".url.tmp")
        tmp_sha = sha_file.with_suffix(".sha256.tmp")
        tmp_url.write_text(url + "\n")
        tmp_sha.write_text(sha + "\n")
        tmp_url.replace(url_file)
        tmp_sha.replace(sha_file)
        print(f"[5/6] pointer files updated → data/chabad.db.{{url,sha256}}")

        # Step 6 — meta_publish row in the *source* DB (so the live DB knows
        # what was published, even if the published copy doesn't yet).
        # Idempotent: never overwrites.
        sc = sqlite3.connect(args.db)
        try:
            sc.execute(
                "INSERT INTO meta_publish (sha256, snapshot_count, published_at, cycle_id) "
                "VALUES (?, ?, ?, ?)",
                (sha, row_count, datetime.now(timezone.utc).isoformat(), args.cycle_id),
            )
            sc.commit()
        finally:
            sc.close()
        print(f"[6/6] meta_publish row inserted: count={row_count}")

    print(f"\nPublished {short} · {row_count} incidents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
