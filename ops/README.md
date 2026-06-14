# ops/

Operational state for the autonomous research bureau.

## `OPS_HALT` — the only manual brake

Touch `ops/OPS_HALT` from any device (`gh api ...` or web UI), commit + push, and every workflow early-exits on its next tick. No secrets revoked, no infra torn down. Delete the file to resume.

```bash
# halt
echo "halt reason: investigating quarantine spike" > ops/OPS_HALT
git add ops/OPS_HALT && git commit -m "ops: halt" && git push

# resume
git rm ops/OPS_HALT && git commit -m "ops: resume" && git push
```

Every workflow contains an `OPS_HALT pre-flight` step that checks for this file and exits 0 cleanly if present. See `.github/workflows/_template.yml.example`.

## Files that will land here in later phases

- `ops/budget.json` (Phase 5) — per-day search + fleet call counters, daily reset.
- `ops/cycles.jsonl` (Phase 9) — one line per cycle, committed at end of cycle so even crashes record what they did before dying.
- `ops/weekly.md` (Phase 9) — `ops-weekly.yml` writes this every Sunday.

## What `/ops` is (Phase 9)

Internal Vercel route — reads `ops/cycles.jsonl` + `ops/budget.json`. No login, just unlinked from public nav. The engine view; the public sees the pixel office.
