# Devlog — Chabad Tracker Build

Running notes on what got built, what got decided, and what hit a wall. Append-only.

---

## 2026-06-14 — Phase 0 kickoff

### Decisions taken on my own

- **Photos (84MB / 787 files in `ui/public/photos/`) ship in the git repo.** Option (a) from the Phase 0 plan. Rationale: photos aren't churning, the clone hit is one-time, and Phase 0 already has enough moving parts. Migrating to R2 is a Phase 2 candidate if it actually bites.
- **CODEOWNERS deferred to Phase 9.** No real bot identity yet; branch protection on `main` is enough for now. Will revisit when cloud cycles start opening PRs.
- **R2 bucket = public-read.** Matches the "curl it and own it" doctrine in researchteam.md. DB and (eventually) photos are intentionally public.
- **Repo name = `rabbishimon613-lang/chabad-tracker`, public.**

### Step 1 — git init + repo creation ✅

- `.gitignore` extended to block `.env`, `.vercel/`, node_modules, `__pycache__/`, `*.db`, `*.db-shm/-wal`, scratch `data/*.json|*.jsonl|*.tsv`.
- Verified `.env`, DBs, and node_modules NOT staged.
- Initial commit: **893 files, 83.6 MB** (most of it `ui/public/photos/`). Commit `dc5d0d8`.
- Repo created: https://github.com/rabbishimon613-lang/chabad-tracker (public).
- Branch protection on `main`: no force-push, no deletion. Status checks deferred to Phase 9.

### Step 2 — Cloud-pool API keys into Actions secrets ⏸️ BLOCKED

Blocked on user supplying:
- Cerebras × 5 key values (the buildroad calls for 4 cloud + 1 local; I need all 5 to know which goes where, or the user to pre-split).
- Groq × 3 key values (2 cloud + 1 local).
- OpenRouter × 5 key values (3 cloud + 2 local).
- Which 3 of the 5 Tavily keys in `.env` are cloud-pool, which 2 are local. (`TAVILY_KEYS` is currently comma-joined.)
- Which 3 of the 5 Exa keys in `.env` are cloud-pool, which 2 are local. (`EXA_KEYS` same.)

Will load into Actions secrets as `CEREBRAS_KEY_1..4`, `GROQ_KEY_1..2`, `OPENROUTER_KEY_1..3`, `TAVILY_KEY_1..3`, `EXA_KEY_1..3` per cloud-pool sizing.

### Step 5 — Workflows with concurrency + OPS_HALT discipline ✅

- `.github/workflows/_template.yml.example` — every workflow boilerplate (`timeout-minutes: 10`, `concurrency` group, OPS_HALT pre-flight).
- `.github/workflows/ci.yml` — runs schema.sql + views.sql sanity, fails PR if any DB blob or `.env` gets committed.
- `ops/README.md` documents the OPS_HALT convention.

### Step 6 — UI honesty pass ✅

Edits in `ui/index.html` and `ui/about.html`:
- **Status bar** (3rd `#topbar` row) — `data as of <ts> · <N> incidents · cycle <X> ago` with a colored freshness dot (green / yellow / red). Polls `snapshot.json` every 5 min; offers a soft-reload link when newer data arrives. Never auto-refreshes.
- **Freshness banner** — yellow strip below header when snapshot is >24h old.
- **Reflection mismatch warning** — red footer banner that fires when `snapshot.json.incidents !== rowcount(loaded chabad.db)`. Currently fires immediately on this deploy: snapshot says 357, DB has 976. The system is now honest about its own drift. Underlying drift gets fixed in Phase 2 (atomic publish).
- **Stats relocation** — moved the 4 high-level counts (incidents / houses / people / families) from DB-page Stats subtab to the top of About, fed by `snapshot.json` (no DB load needed on About). The deeper analytical Stats subtab on the DB page stays for now; pure relocation would require porting sql.js to about.html, which is Phase 1+ scope.
- **Dead back button** — explicitly hidden on DB landing via `renderTopList()`. The `setSheetHeader` path already hid it; this is defense-in-depth.
- **Left filters fix** — `refreshAll()` no longer gates the home-list re-render on `!location.hash`. Filter clicks now always re-query the home list. (Couldn't reproduce the exact bug in the local preview sandbox — the inline module script doesn't execute there; verified about.html instead and will verify index.html post-deploy.)
- **Confidence chip skeleton** — `window.renderConfidenceChip({ score, passedChecks, failedChecks })` returns chip HTML with band-colored border + hover popover. Not wired anywhere yet; Phase 1's Verifier feeds it.

Local preview verified: about.html renders correctly — status bar shows "data as of 2026-06-08 03:35 UTC · 357 incidents · cycle 6 d ago" with stale dot; banner reads "data is 6 days old — researcher cycle may be paused"; 4-card stats grid shows 357 / 4,173 / 9,687 / 837.

### Step 7 — Deploy + verify exit criteria — in progress

**Phase 0 bridge:** committed `ui/public/chabad.db` (the live 976-incident DB) to git so the Vercel auto-deploy doesn't break before R2 is wired. `.gitignore` has the line commented with a TODO. **Remove this commit when Step 3 (R2) lands.**

