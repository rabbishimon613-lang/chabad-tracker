# Devlog — Chabad Tracker Build

Running notes on what got built, what got decided, and what hit a wall. Append-only.

---

## 2026-06-14 — Phase 0 kickoff

### Decisions taken on my own

- **Photos (84MB / 787 files in `ui/public/photos/`) ship in the git repo.** Option (a) from the Phase 0 plan. Rationale: photos aren't churning, the clone hit is one-time, and Phase 0 already has enough moving parts. Migrating to R2 is a Phase 2 candidate if it actually bites.
- **CODEOWNERS deferred to Phase 9.** No real bot identity yet; branch protection on `main` is enough for now. Will revisit when cloud cycles start opening PRs.
- **R2 bucket = public-read.** Matches the "curl it and own it" doctrine in researchteam.md. DB and (eventually) photos are intentionally public.
- **Repo name = `rabbishimon613-lang/chabad-tracker`, public.**

### Step 1 — git init + repo creation

In progress.

