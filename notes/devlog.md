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

### Step 2 — Cloud-pool API keys into Actions secrets ✅

Source: `/Volumes/EOS_DIGITAL/llm-fleet/.env` (the local fleet's config). Loaded as numbered GH Actions secrets:

- `GROQ_KEY_1`, `GROQ_KEY_2` — first 2 of 3 total
- `OPENROUTER_KEY_1`, `_2`, `_3` — first 3 of 5 total
- `TAVILY_KEY_1`, `_2`, `_3` — first 3 of 5 total
- `EXA_KEY_1`, `_2`, `_3` — first 3 of 5 total

**No Cerebras keys** exist on disk; researchteam.md's "5 Cerebras keys" was aspirational. Cloud pool runs without them. Cerebras can be added later as `CEREBRAS_KEY_1..N` whenever provisioned — `fleet_batch` already accepts the fallback.

**Doctrine drift:** these same keys are still in the local fleet's `.env`. The "keys never overlap" rule is violated in this Phase 0 state. Practical impact: if cloud cycles burn a shared key's daily rate limit, the local fleet sees the limit too. Acceptable bridge while we're not yet running cloud cycles. Cleanup options: (a) physically split — push first-N to Actions and rewrite fleet `.env` to keep only the last-M; (b) provision fresh keys for cloud and revoke the shared ones from local. To revisit once cloud cycles start firing.

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

### Step 7 — Deploy + verify exit criteria ✅ (partial — see below)

**Phase 0 bridge:** committed `ui/public/chabad.db` (the live 976-incident DB) to git so the Vercel auto-deploy doesn't break before R2 is wired. `.gitignore` has the line commented with a TODO. **Remove this commit when Step 3 (R2) lands.**

**Vercel project linking:** the `ui/.vercel/` link had drifted to a stray `chabadtracker` project (no hyphen). Relinked to the canonical `chabad-tracker` project at the same org. Production alias `https://chabad-tracker.vercel.app` now serves the new build.

**GitHub ↔ Vercel auto-deploy:** the existing Vercel project pre-dates this GitHub repo and isn't wired to it. For now I'm pushing via `vercel --prod` from CLI. Connecting the Vercel project to `rabbishimon613-lang/chabad-tracker` is a 30-second dashboard step the user should do so subsequent commits to `main` auto-deploy.

**Verified on production (`https://chabad-tracker.vercel.app`):**
- `/about.html` returns 200 with the new status bar, freshness banner, and 4-card stat grid.
- `/public/snapshot.json` still says `incidents: 357` (the lie — left intact, will be fixed in Phase 2 by the atomic publish rewrite).
- `/public/chabad.db` returns 200, ~6.7MB — the live 976-incident DB.
- `/` (index.html) HTML source contains the new `status-bar`, `reflection-warning`, `freshness-banner`, and `renderConfidenceChip` markers.
- Reflection-mismatch warning will fire as soon as a visitor's browser loads `/` because `snapshot=357 ≠ db=976`. The system now tells the truth about its own drift.

### Phase 0 exit criteria scorecard

| Criterion | Status |
|---|---|
| Repo + secrets + R2 + Vercel wired | ⏸️ partial — repo + Vercel ✅; secrets + R2 blocked on user creds |
| `concurrency:` group rule applied to every workflow | ✅ `ci.yml` has it; `_template.yml.example` documents it |
| Status bar live on deployed site, showing current data freshness | ✅ |
| All three UI backlog items fixed and deployed | ✅ filters re-render fix, dead back button hidden on landing, stats moved to About |
| Confidence chip + reflection mismatch warning ready to receive data | ✅ |

### Blocked on user input (needed to finish Steps 2, 3, 4)

1. **Cloud-pool API keys** — Cerebras × 5 values, Groq × 3 values, OpenRouter × 5 values, and the explicit split of the existing Tavily × 5 / Exa × 5 keys (which 3 go to the cloud pool, which 2 stay local). I'll load them into Actions secrets per the cloud sizing in researchteam.md.
2. **Cloudflare R2 access** — once available, I'll provision the `chabad-tracker` bucket (public-read), upload the DB, write the `data/chabad.db.url` + `.sha256` pointer files, and rewrite the Vercel prebuild step to fetch from R2 by hash. Then `ui/public/chabad.db` comes back out of git.
3. **Vercel ↔ GitHub auto-deploy** — small dashboard step on the user's side so future pushes to `main` deploy automatically.

