# Research Team — Cloud-Native Autonomous Researcher

*Design doc from brainstorming session, 2026-06-14. Source of truth for the next build phase.*

---

## Vision

A self-running journalism research bureau that lives in the cloud. It excavates the documented universe of Chabad-as-perpetrator cases, verifies what it finds, files it to a single intel repository, and publishes the result — without a human in the loop except for genuinely novel calls.

The same intel box has **three reflections**: the map, the people web, and the raw downloadable DB. None of them can disagree because they all derive from one file.

A visitor lands on the about page months later, finds the office still working, sees more dots on the map than last time. The system never stops, never asks for permission, and is honest about what it finds and what it sets aside.

---

## Architecture

### One source of truth

```
GitHub repo (public, intel box)
├── data/chabad.db          ← truth
├── leads queue + research code
├── schema.sql + views.sql
└── ui/                     ← Vercel deploys this
```

### Three viewers (all over the same DB)

- **Map** — geographic dots, severity color, click for dossier.
- **People web** — graph view of family + co-defendant networks.
- **DB browser** — raw tables + a big "download chabad.db" button. The receipts.

The DB ships as a static asset. Browser loads it via `sql.js`. No backend. No API. "Curl it and own it" is load-bearing.

### Cloud research team

```
GitHub Actions (cron) ── runs cycles ──→ commits to branch ──→ opens PR
   ↓                                                              ↓
fleet + search APIs (free)                                     CI gates
   ↓                                                              ↓
writes to staging in DB                                       auto-merge
                                                                   ↓
                                                              Vercel rebuilds
                                                                   ↓
                                                              site is live
```

- Public repo → **unlimited Actions minutes** on the free tier.
- API keys live in Actions secrets, never in code.
- Vercel auto-deploys on push to main. No manual step.

---

## The Research Team — Five Roles

Each role corresponds to a stage of the cycle. Pixel-art sprites on the /about page, each with a live "mindbox" showing current activity.

| Role | Headcount | What it does |
|---|---|---|
| **The Investigator** | 5–7 | Lead generation (one per "beat") |
| **The Researcher** | 2–3 | Pops leads, runs fleet + search, extracts JSON |
| **The Verifier** | 1 | Hard-checks every claim against sources |
| **The Archivist** | 1 | Writes verified rows to live DB, spawns child leads |
| **The Publisher** | 1 | Builds snapshot, deploys site |

### The Investigator (lead generation)

Each Investigator runs one beat. Cheap, frequent, varied.

- Investigator on **the family graph** (cold-path relatives — SQL query, every 30 min)
- Investigator on **the DOJ feed** (RSS, every 15 min)
- Investigator on **the state AGs** (NY/NJ/CA/IL/FL/MA RSS, every 15 min)
- Investigator on **the federal courts** (CourtListener new dockets, every hour)
- Investigator on **the survivor archive** (JCW Wall of Shame, every 6 hours)
- Investigator on **the hot houses** (full roster sweep of 4+ incident houses, every 4 hours)
- Investigator on **the orphans** (228 unnamed incidents, segmented triage, every 2 hours)

Each writes scored rows to the `leads` table.

### The Researcher (digging)

Pops top-scored leads, runs:
- `search_batch` against Tavily + Exa
- `fleet_batch` against Cerebras + Groq + OpenRouter
- Returns structured JSON: incidents, severity, co-defendants, sources, verbatim quotes
- Writes to **staging table**, not live tables

Multiple Researchers run in parallel on different batches (high-priority, enrichment, orphan).

### The Verifier (paranoid by design)

See full stack in the **Verification** section below. Promotes clean rows to "confirmed," quarantines the rest. Never blocks — filters.

### The Archivist (writes to truth)

- Promotes confirmed rows into `incidents`, `incident_people`, `incident_houses`, `incident_sources`
- Runs sidecars: extract_numbers, entity_resolution, dedup, stub_resolver
- Adds new family + co-defendant edges
- **Spawns child leads** (every new name/co-def/house → new leads)
- Marks parent lead resolved

### The Publisher (ships)

- Runs `score_houses` (severity bands, color, count)
- Runs `compute_graph_metrics` (centrality, betweenness)
- Re-runs `views.sql` against the snapshot DB
- `VACUUM INTO ui/public/chabad.db`
- Writes fresh `snapshot.json`
- `git commit && push` → triggers Vercel rebuild

---

## The Cycle

Within one cycle, the chain is sequential:

```
Investigator → Researcher → Verifier → Archivist → Publisher
```

Across cycles, beats fire on independent crons. Most of the day, *something* is moving. Mostly old work (excavation), some new work (current monitoring). Estimated split: 80% historical, 20% current.

### Approximate schedule (illustrative, will be tuned)

| Beat | Interval |
|---|---|
| External RSS pollers (DOJ, AGs) | 15 min |
| Researcher high-priority batch | 20 min |
| Cold-path family walk | 30 min |
| CourtListener new dockets | 1 hour |
| Researcher enrichment batch | 30 min |
| Orphan triage | 2 hours |
| Hot-house sweep | 4 hours |
| JCW poller | 6 hours |
| Big graph-walk cycle | 6 hours |

Average user lands on the page during a working window most of the time.

---

## Verification Stack (the load-bearing component)

This is journalism. Hallucination is the biggest exposure. The Verifier runs **all of these** on every claim, not just one gate.

1. **URL liveness** — HEAD returns 200. If 404 → quarantine.
2. **Page-contains-name** — exact `full_name` must appear on the page. Not initials. Not partial. Kills most hallucinations alone.
3. **Verbatim quote requirement** — Researcher must emit a 10-30 word quote from the source. Verifier re-fetches and confirms it's present. If quote not on page, the LLM made it up.
4. **Fact triangulation** — name + 3 of 4 facts (year / location / type / amount) must appear within ~500 chars of the name on the page.
5. **Doctrine / role check** — the 200 chars around the name must contain perpetrator-side keywords. Victim-side keywords → off-doctrine, quarantine.
6. **Severity ladder calibration** — claim of `convicted` requires sentencing/conviction language in source. Otherwise auto-downgrade severity. System never overclaims.
7. **Source-class weighting**:
   - Court docs (courtlistener, .gov) — one source enough for `convicted`
   - Mainstream news — one for `charged`, two for `convicted`
   - Blogs/Substack — never alone, always need corroboration
   - Anonymous/forum/Reddit — never accepted
8. **Cross-source agreement** — multi-source claims must agree on facts. Disagreement → quarantine.
9. **Independent second-pass LLM** — every new-perpetrator row gets re-extracted by a different fleet model. Disagreement → quarantine.
10. **Wayback freeze** — source URL submitted to Wayback on insertion. Snapshot URL stored alongside original. Receipts that outlive link rot.
11. **Confidence score (0-100)** —
    - ≥80 → archive
    - 50-79 → archive, flagged "low-confidence" visible in UI
    - <50 → quarantine
12. **Doctrine enforcement** — hard reject if the page describes the person as victim of an attack on Chabad. Aligned with the existing perpetrator-only doctrine ([[project_chabad_tracker_doctrine]]).

### Quarantine, not rejection

The Verifier never blocks the PR. Bad rows go to a `quarantine` table inside the DB — lives forever, queryable, but the live site only reads clean tables. Every quarantined row stores **why** it failed in plain English. Over time, the quarantine table becomes training data for tightening the Researcher's prompt.

### What this catches
- Hallucinated names (name-on-page check)
- Hallucinated cases at real names (verbatim quote)
- Wrong-person collisions (triangulation)
- Severity inflation (ladder)
- Off-doctrine entries
- Sloppy single-source claims
- Model-specific weirdness (second-pass)

### What it doesn't catch
- A source that's itself wrong. Mitigated by multi-source requirements for severe claims.

---

## No Human Ever — Self-Healing Design

The whole system is designed so a PR **never needs review**.

- **Per-row filtering, not per-PR blocking.** Bad rows quarantine, good rows merge.
- **Auto-retry once.** Failed source-check → fleet re-extracts with stricter "exact quote required" prompt. Still fails → quarantine.
- **Crash = auto-rollback.** Cycle errors out → branch deleted, no PR opens, next cron tick retries cleanly. Main never touched.
- **Cost overrun = hard stop.** Per-cycle budget enforced before the cycle starts. Exceeded → cycle aborts itself, commits nothing.
- **Optional weekly summary** posts what got quarantined to a private gist/email. Informational, never blocking.

The only thing that grows without input is the dataset itself.

---

## Getting Savvier Over Time

Not real ML — just data-driven rule tightening. All auditable in SQL.

1. **Source learning** — track which domains produce confirmed hits. Promote winners, demote losers. New domain shows up → auto-added to watch list.
2. **Trail of names** — every confirmed co-defendant spawns its own lead. Each new person opens new corners of the internet.
3. **Periodic broad sweep** — once a month, a wide-net query. Filters out everything already in DB. Whatever's left is new ground or junk. The sweep narrows over time because the DB knows more.
4. **Query quality tracking** — every search query logged with hit rate. Bias toward winning shapes (city + crime > denomination + crime).
5. **Lead scoring calibration** — ground truth from outcomes. Cold-path relative class = 12% hit rate after 100 tries → score class rebalances.
6. **Source-page pattern learning** — CourtListener docket URL patterns become fast-track. Junk domains become auto-reject.
7. **Negative learning from quarantine** — common failure modes get translated into stricter prompt language.
8. **Co-occurrence mining** — names that co-occur 3+ times in adjacent sources auto-spawn leads even before charged.
9. **Beat expansion** — once stable, add new Investigator beats (Israeli press in Hebrew, Australian press, Yiddish forums, Argentine Jewish papers).

### Long-term shape
- Year 1: broad excavation, learning what works.
- Year 2: 10+ Investigator beats, calibrated scoring, stable source rankings.
- Year 3: documented universe mostly in. Work shifts to monitoring + deep tail (pre-1990, suppressed, non-English).

The office looks the same throughout. The mindbox lines get more specific.

---

## Publishing — All Three Reflections Stay Aligned

### The principle: one source of truth, two derived mirrors.

```
data/chabad.db                          (source of truth)
   ├── ui/public/chabad.db              (mirror 1: static asset)
   └── ui/public/snapshot.json          (mirror 2: counts/manifest)
            ↓ git push
       Vercel rebuilds
            ↓
       site is live (three views over the same file)
```

### Rules

1. Snapshot is not optional — runs at the end of every cycle. No cycle complete without it.
2. `snapshot.json` is generated from the just-VACUUMed mirror, not the live DB. Proves the published DB is what it claims.
3. `views.sql` reruns on the snapshot DB, never polluting truth.
4. Only `snapshot_for_ui.py` writes to `ui/public/`. No other path.
5. Freshness is **visible**: UI shows "data as of [timestamp]." If >24h old → warning.
6. Deploy is part of publish: commit + push happens in the same job.

### Refresh behavior
- Backend: fully automatic on cron tick.
- Frontend (user with page open): soft refresh — UI checks `snapshot.json` every 5 min, shows banner "New data available — reload?" when it changes.

---

## API Key Split — Cloud vs Local

Same providers serve both, but **keys never overlap**.

| Provider | Chabad cloud | Local fleet |
|---|---|---|
| Cerebras (5 keys) | 4 | 1 |
| Groq (3 keys) | 2 | 1 |
| OpenRouter (5 keys) | 3 | 2 |
| Tavily (5 keys) | 3 | 2 |
| Exa (5 keys) | 3 | 2 |

No new keys planned. The chabad cloud pool is fixed — system is sized within these constraints forever.

### Free-tier infra
- **GitHub Actions** — public repo = unlimited minutes. Free.
- **Vercel** — generous hobby tier. Free.
- **Cloudflare** — backup option for hosting/R2 if needed. Free.
- **Source APIs** — CourtListener, ProPublica, Wayback, Wikipedia all free, unlimited.

---

## The Pixel Office (about page UI)

A small bureau scene. Five characters at their stations, each with a live mindbox showing current activity. Newsroom/detective bureau aesthetic — not Tamagotchi. Muted palette. Working-class register.

### Visual rules
- Pixel sprites, ~32-48px per character
- Distinct props per role: corkboard (Investigator), monitor + files (Researcher), magnifier + stamp (Verifier), filing cabinets (Archivist), wall map (Publisher)
- Animation only when their stage of the cycle is active. Otherwise still.
- No mascot names, no speech bubbles, no chirping.

### The mindbox

One per character. Below the sprite. Log-line aesthetic.

Format: `[HH:MM:SS] sentence in present tense.`

Coloring (CSS, terminal-style):
- `dim gray` — timestamp, brackets, field labels
- `bright white` — proper names
- `cyan` — places, counts, amounts
- `amber` — dates, years, warnings
- `green` — PASS / OK / DONE
- `red` — FAIL / quarantine

Each mindbox carries the timestamp in dim gray + the latest action as a natural-language sentence.

### Mindbox flavor — LLM with hard guardrails

LLM-generated (free fleet, ~0.04% of budget — cost is rounding error). Brings unlimited variety and reactive specificity ("That's the seventh case at Yeshivah Centre" only works because the LLM sees the count).

#### Guardrails (layered)

1. **Locked system prompt per character** — tone, register, vocab range, banned list. Heavy few-shot anchoring (10+ example phrases from the curated pool).
2. **Structured input, narrow output** — LLM sees role, event type, facts only. Length cap ≤140 chars, one sentence after timestamp.
3. **Output filter** — regex + word list. Reject if: too long, exclamation marks, banned words (whoops, oops, lol, etc.), sentiment mismatched to event.
4. **Hallucination clamp** — every proper noun in output must appear in input facts. If LLM invented a name/place → reject.
5. **Phrase pool fallback** — if generation fails the filter twice, pull from the curated pool. Visitor never sees a broken line.
6. **24h cache** — same (role + event type + fact hash) reuses the line for short-term consistency within a session.
7. **Weekly human sample** — once a week, last 100 generated lines dumped to private gist. Skim for off-tone, add bad examples to the prompt's "do not say" section. Continuous tuning, no per-cycle babysitting.

#### Voice rules
- Short sentences
- Plain reactions, never exclamations
- Newsroom vernacular ("smells right" / "trail's cold" / "worth a closer look")
- Never cheery, never grim-dark — calm engagement
- Topic gravity always intact

#### Per-role flavor categories
- **Investigator** — new lead promising / dead end / pattern noticed / quiet
- **Researcher** — solid hit / partial / trail cold / surprise
- **Verifier** — clean pass / edge pass / reject / suspicious
- **Archivist** — routine file / connection found / cluster milestone / spawning leads
- **Publisher** — small push / big push / nothing to ship / deploying

The Verifier should have the sharpest voice — terse, suspicious, hard to impress. *"Not enough." "Show me the quote." "Only one source. Holding."*

#### Sample mindboxes

```
THE INVESTIGATOR
[14:45:02] Pulled a name off the family tree — Mendel Goldberg,
           brother of a Brooklyn perpetrator. Smells right.

THE RESEARCHER
[14:46:18] Looking into Mendel Goldberg, Brooklyn. Reading five
           articles and two court filings.

THE VERIFIER
[14:47:01] Checking a 2019 case from Brooklyn. Source confirms
           the name. PASS.

THE ARCHIVIST
[14:47:33] Filing Mendel Goldberg — financial fraud, $1.4M,
           Brooklyn 2019. Linking two co-defendants. Opening
           four new leads.

THE PUBLISHER
[14:48:09] Putting a new dot on Brooklyn. The site is updating now.
```

### Idle states
Every character has an idle/sleeping voice for off-hours. *"Quiet desk. Last lead came in eight minutes ago." / "Night shift. Reading the wires." / "Coffee. Back to the family graph in a minute."*

### Top-bar heartbeat
- `last cycle: 23 min ago · next: 37 min`
- Status dot: 🟢 fresh / 🟡 6h+ / 🔴 stale

---

## What We Have / What's Confirmed

### Logins ready
- GitHub: `rabbishimon613-lang` (full repo + workflow scopes)
- Vercel: `rabbishimon613-lang`
- Cloudflare: `rabbishimon613@gmail.com`

### Keys ready
- 5 Cerebras keys (new), 3 Groq, 5 OpenRouter, 5 Tavily, 5 Exa.
- Split per the table above.
- No new providers planned. The team is sized for what's on hand.

### Repo decisions
- **Public** chabad-tracker repo (matches "open record" doctrine, gets unlimited Actions minutes).
- DB is public-record info, intentional.
- Lead queue + ops scratch lives in the public repo too (it's not sensitive — these are public allegations).
- Secrets via Actions secrets, encrypted at rest.

### Hosting
- **Vercel** for the frontend (chabad tracker is already there).
- Cloudflare as backup/R2 storage if DB-in-git grows too heavy.

---

## What This Document Doesn't Cover (Yet)

- Concrete cron schedule with budget math (which beats × which intervals × which API calls = stays under free tier).
- The exact CI workflow YAML.
- The `leads` and `quarantine` table schemas.
- The Verifier's full code structure.
- The pixel sprite designs.
- The exact prompt templates for the mindbox flavor LLM.

Those come at build time. This doc is the **why** and the **shape**. Build phase fills in the **what** and **how**.

---

## Key Principles (the spine)

1. **One intel box, three reflections.** Map, web, raw — all derived from one file.
2. **Cloud-native, no human in the loop.** GH Actions cron, PR-based, auto-merge, auto-deploy.
3. **Filter, don't block.** Bad rows quarantine. Good rows always merge. PR never fails.
4. **Verification is paranoid.** Twelve layers. Journalism requires it.
5. **The team has personality, the system has gravity.** LLM-generated flavor with hard guardrails. Newsroom voice. Topic respect.
6. **Free tier forever.** Keys fixed, beats budgeted, no scaling-up plans.
7. **The data teaches the system.** Source rankings, query patterns, scoring calibration all derive from outcomes. No black-box ML.
8. **Perpetrator-only doctrine** ([[project_chabad_tracker_doctrine]]) — non-negotiable. Enforced in the Verifier.
9. **Never delete originals** ([[feedback_never_delete_originals]]) — quarantine table preserves everything, even rejects.
10. **The visitor sees the work.** The pixel office is honest about what's happening. Not theater. Not a scoreboard. A window into a real, ongoing investigation.

---

## The Pixel Office — Concrete Build Plan

### The fork: rolandal/pixel-agents-standalone

MIT-licensed standalone web app, fork of pablodelucca/pixel-agents. Top-down 2D pixel office with React + Canvas engine, sprite animation, pathfinding, layout via JSON map file.

**What we keep:** the React/Canvas engine, sprite animation, pathfinding, layout system.

**What we strip:** the Express + WebSocket server, the `~/.claude/projects/` JSONL watcher (5 files: `watcher.ts`, `parser.ts`, `index.ts`, `assetLoader.ts`, `types.ts`).

**What we add:** a poller in the React app that fetches `/snapshot.json` every 5 seconds, maps the latest cycle state onto agent activity states.

### Free asset stack (no drawing, no buying)

- **Penzilla — Top-Down Retro Interior** (primary base). Free for personal use with credit. Desks, chairs, monitors, lamps, bookshelves, plants, tables, rugs, framed paintings.
- **Penzilla — Top-Down Retro House** (companion). Same artist, same style — adds dining table for the meeting/sharing area.
- **Anokolisa — Free Topdown Tileset** (500+ sprites). Free. Extra clutter, papers, scrolls, walls, props.
- **Cup Nooble free packs** — magnifier, small detective props if needed.

All three creators use ~16×16 register and blend cleanly.

### Layout — single open floor plan, 9 stations + meeting table

```
┌──────────────────────────────────────────────────────────┐
│  ARCHIVIST WALL              PUBLISHER WALL              │
│  (bookshelves as filing      (bookshelves recolored as   │
│   cabinets, single desk)      a wall of pinned papers)   │
│                                                          │
│  ─── INVESTIGATOR BULLPEN (top half) ───                 │
│  Investigator desk × 3 — messier, paper-heavy,           │
│  no monitors, multiple desk lamps                        │
│                                                          │
│         ╔══ MEETING TABLE ══╗                            │
│         ║  long table + 4   ║  where leads move          │
│         ║  chairs           ║  between roles             │
│         ╚═══════════════════╝                            │
│                                                          │
│  ─── RESEARCHER ROW (bottom half) ───                    │
│  Researcher desk × 3 — clean, monitors + lamps,          │
│  the "machine room"                                      │
│                                                          │
│         VERIFIER DESK                                    │
│         single station, bright lamp,                     │
│         magnifier prop, paper stack                      │
└──────────────────────────────────────────────────────────┘
```

### Asset substitutions — color-tint reskins, no new pixels drawn

| What we need | Free asset substitute |
|---|---|
| Corkboard | Penzilla bookshelf + Anokolisa paper props pinned on top |
| Wall map | Penzilla framed painting, recolored via CSS hex swap |
| Filing cabinets | Penzilla tall bookshelf, sprite-loader recolor to gray/manila |
| Magnifying glass | Anokolisa or Cup Nooble props pack |
| Ink stamps | Penzilla small object on desk (pottery, box) |
| Wall pin-ups | Penzilla framed paintings, multiplied + recolored |
| Meeting table | Penzilla House pack dining table + chairs |
| Newsroom papers | Anokolisa scrolls/papers everywhere |

Color tinting + flipping + tiling in the engine's layout JSON does all customization. Zero new pixels drawn.

### Visual register per role

- **Investigator** — messy desk, scattered papers, multiple desk lamps, no monitor. Works on paper + the corkboard.
- **Researcher** — clean desk with monitor, lamp, tidy stacks. The "machine room."
- **Verifier** — minimalist single desk, one bright lamp, one paper, magnifier prop. The "inspection table."
- **Archivist** — surrounded by tall bookshelves (= filing cabinets). One chair, always in motion.
- **Publisher** — big wall of pinned papers behind their desk. Phone prop if available.

### Movement choreography (visible data flow)

- **Investigators** walk between desk and meeting table — dropping off a lead.
- **Researchers** walk meeting table → desk (research) → meeting table (drop a row off).
- **Verifier** stays seated, stamps → walks to Archivist or to the quarantine bin (small prop).
- **Archivist** walks to desk, files, occasionally back to the meeting table.
- **Publisher** mostly seated, occasionally walks to wall and "pins" a new dot.

The meeting table at the center makes bot coordination visible. That's where the data flow becomes a scene.

### Build effort estimate

- ~30 min: download free packs (Penzilla Interior, Penzilla House, Anokolisa).
- ~1 hr: edit engine layout JSON to place 9 stations + meeting table.
- ~30 min: configure CSS/sprite color tints for the bookshelf-as-cabinet reskins.
- ~30 min: wire 9 character slots to the 9 roles.
- ~2 hrs: strip server, write `snapshot.json` poller, map cycle state to agent states.

Total: ~half a day to a working office. Upgrade and decorate over time.

### Licensing notes
- Penzilla: free for personal use *with credit*. Commercial use requires paying suggested price. Tracker is non-monetized personal/journalism project — qualifies as personal. Include credit in the about page footer.
- Anokolisa free pack: explicitly royalty-free.
- Engine fork: MIT — fully free.

---

## Phase 0–4 — Straightening the Existing Intel Pile (pre-build cleanup)

Before the researcher loop runs, the existing DB needs cleanup. This is the foundation pass.

### Current state (as of 2026-06-14)
- 976 incidents (live DB) — but only 971 on website (2 days stale), and snapshot.json claims 357 (6 days old, wrong).
- 10,042 people, 4,257 houses.
- 228 orphan incidents (no perpetrator linked).
- 467 named perpetrators, only 71 anchored to houses (15%).
- 3,050 family edges, 354 co-defendant edges — built but barely walked.
- 30+ bucket scripts contributing inconsistently.
- Estimated coverage: 25–30% of the documented universe ([[expert_roundtable]]).

### Phase 0 — Stop the bleeding
- Freeze the bucket sprawl. No more ad-hoc `bucket_*.py` runs.
- Run `snapshot_for_ui.py` immediately so published DB + snapshot.json catch up to live (976).
- Three reflections aligned before we touch anything else.

### Phase 1 — Audit what's already in the DB
- Build the Verifier (12-layer stack from this doc).
- Run it backward against every existing incident — re-check source URLs, names, doctrine, severity ladder.
- Create the `quarantine` table.
- Anything that fails the stack → moved to quarantine. Originals preserved ([[feedback_never_delete_originals]]).
- After this pass: clear separation between *verified* incidents and *suspect* ones from old runs.

### Phase 2 — Resolve the messy data
- Walk `person_match_candidates` — confirm or reject pending merges.
- Triage the 228 orphans, segmented by signal:
  - Has source URL → fetch + NER + auto-link
  - Has partial name → targeted search + PACER
  - Has location + type only → hot-house sweep + AG press releases
  - Vague summary only → suppression_signal flag, may stay un-nameable
- Anchor more perps to houses (raise from 15% → as high as possible). Map dots depend on this.
- Backfill missing fields (`amount_usd`, `prison_years`, severity gaps) via sidecars — but only on verified rows.

### Phase 3 — Bootstrap the new system
- Create the `leads` table (schema in main body of doc).
- Run all SQL lead generators against the cleaned DB:
  - Cold-path relatives
  - Hot-house rosters
  - Institution-hoppers
  - Long-tenure anomalies
  - Amount collisions
  - Family bridges
- Result: hundreds of starting leads, all scored, ready to feed the Researcher.

### Phase 4 — Publish the clean state
- Re-run `snapshot_for_ui.py`.
- Confirm live DB + published DB + snapshot.json all agree.
- `git commit && push` → Vercel deploys.
- Website now shows the *verified* universe, not the raw scraped pile.
- The status bar reflects the cleaned counts.

### Exit criteria — system is ready for the researcher loop when:
- ☐ Three reflections in sync (counts agree across live DB, published DB, snapshot.json)
- ☐ Every live incident has passed the Verifier stack at least once
- ☐ Quarantine table exists and holds the suspect rows
- ☐ Person merge candidates fully resolved (pending = 0)
- ☐ Orphan count meaningfully reduced via targeted triage
- ☐ Leads table populated with bootstrap leads
- ☐ Site shows clean snapshot timestamp

Only then do we wire the cron'd researcher cycle. Building the loop on top of dirty data poisons the loop forever.

---

## Post-Cleanup Build Sequence (Phase 5–10, plain words)

After Phase 0–4 finishes (DB straight, three views in sync), the actual research team gets built in this order:

**5. Get the intake ready** — `leads` and `quarantine` tables. The inboxes. DB is ready to receive work.

**6. Build the Researcher, prove it works** — one worker, one lead. Search + fleet → JSON → staging. Tune until clean.

**7. Build the Verifier** — wire the 12-layer check. Good rows go live, bad rows quarantine. Pipeline becomes honest.

**8. Build the Archivist + Investigators** — Archivist files, Investigators generate leads (start with one beat, add more one at a time). Loop now feeds itself.

**9. Build the Publisher** — snapshot + git push + Vercel deploy at the end of every cycle. Site auto-updates.

**10. Run it locally for a few cycles** — don't move to cloud yet. Watch what happens on your machine. Tune.

**11. Move it to the cloud** — GitHub Actions workflow + secrets + cron. Same code, scheduled runner. PR-based, auto-merge.

**12. Build the pixel office** — fork rolandal/pixel-agents-standalone. Strip server. Poll `snapshot.json`. Drop free assets. Lay out the 9 stations. Wire each role to its character.

**13. Wire the mindboxes** — LLM flavor with guardrails. Phrase pool fallback. Color-coded text.

**14. Walk away** — cron fires, cycles run, site updates, office breathes.

---

## Workload Reality vs Token Budget

**LLM budget is plenty.** The fleet's Cerebras + Groq + OpenRouter pool delivers far more capacity than the loop will use. Never the bottleneck.

**Search budget is the cap.** Tavily + Exa free tiers = ~100 searches/day total cloud-side. Every Researcher dive costs 2–3 searches. So:

- **~30–50 deep leads/day max.**
- Hit rate 25–40% per lead.
- Realistic output: **~200–400 confirmed new incidents/month.**
- At that pace, 976 incidents grows to ~5000 in two years — closes the 25–30% coverage gap.

**Pace is steady, not frantic.** That's actually good — honest journalism cadence, not fake noise.

**Budget enforcement:** every cycle has a hard cap on fleet calls + search calls. Exceeded → cycle aborts itself cleanly (see no-human design). No runaway costs ever.

---

## Key Pool — Pooled, Not Assigned

All cloud-pool keys serve all functions. The fleet round-robins, fails over automatically. No character is tied to a specific key. If a key dies, the office routes around it.

**Cloud pool (fixed, no expansion planned):**
- Cerebras × 4
- Groq × 2
- OpenRouter × 3
- Tavily × 3
- Exa × 3

Same providers as the local fleet, but separate keys ([[reference_movimento_skills_mcps]] split table).

---

## Public-Facing vs Internal Views

The about-page pixel office is **public**. It must read as a working bureau, not as a debug console. So the visualization splits cleanly:

**Public (about page):**
- 9 characters at 9 stations
- Mindboxes (human-language activity)
- Movement and choreography (lead handoffs at the meeting table)
- Wall map, corkboard, files — the work itself
- Cycle heartbeat at top: *"last update 12 min ago"*

**Internal (separate route, not linked from public nav):**
- Fleet key health, rate-limit status, budget burn per provider
- Quarantine queue counts + why each row failed
- Lead queue depth
- Cycle success/failure log
- Per-cycle token usage

Public sees a working bureau. You see the engine when you debug.

---

## Use the Engine As-Is — What's Already Built In

The rolandal/pixel-agents-standalone fork ships with most of what we need. We do not modify the engine — we feed it different data.

**Already supported, no work needed:**
- React + Canvas 2D engine, sprite animation, pathfinding
- Office layout via JSON map file
- Agent state machine (idle / working / waiting)
- **Speech bubbles** above characters — fed by an `agentStatuses` dictionary
- **Sub-agent visualization** — extra characters can spawn (= our 3 Investigators + 3 Researchers as sub-agents under their role)
- Color-tinting system for sprite re-skins
- Floor/wall tile system (re-color for noir aesthetic)
- Sound notifications
- Zoom, pan, settings
- Live layout editor

**Our additions (small):**
- Strip Express server + JSONL session watcher
- Add `setInterval` poller that fetches `/snapshot.json` every 5 seconds
- Map our cycle state into the engine's `agentStatuses` dictionary
- Edit layout JSON for our 9 stations
- Restyle floating labels into bubble shape (~1hr CSS)

~70% of the code stays untouched. We get pathfinding + animation + state machine + speech bubbles for free.

---

## Animation Pacing — Decouple Data from Visible

Real API calls are fast: 0.5s fleet response, 1–2s search. If we animated at that pace the office would seizure for 3 seconds then look dead for an hour.

**Trick: one lead = one ~20–40 second scene of motion.**

A single lead, no matter how fast the underlying compute was, plays as:

```
walk to corkboard → read a card → return to desk →
pick up phone → type → lean back → read monitor →
walk a paper to the Verifier
```

That's 8 distinct animations from one data event.

**Why this works:**
- 30–50 leads/day × 30s = 15–25 minutes of guaranteed busy animation per day.
- Plus Investigator beats firing every 15 min (RSS pollers) = 96 short scenes/day.
- Plus idle behaviors that aren't dead: sharpening pencils, sipping coffee, walking to the meeting table, looking at the wall map.
- Plus occasional crossings (Investigator walks past Verifier, exchanges a folder).

**Net effect:** any 30-second visit to /about will see somebody doing something. Office is never frozen. Never feels fake. Honest to a real workday.

---

## Visual Reference Links

For when the pixel office build phase starts:

- [Threads — Pixel Agents video demo](https://www.threads.com/@sung.kim.mw/post/DVFigTgCYoY/video-pixel-agents-a-vs-code-extension-that-turns-your-ai-coding-agents-like-claude)
- [Restless Brain — Build Your AI Agents Workplace](https://www.restless-brain.com/p/build-your-ai-agents-workplace-in)
- [Fast Company writeup](https://www.fastcompany.com/91497413/this-charming-pixel-art-game-solves-one-of-ai-codings-most-annoying-ux-problems)
- [ddx-510 live demo](https://ddx-510.github.io/opencode-pixel-office/) — interactive in browser
- [pablodelucca/pixel-agents](https://github.com/pablodelucca/pixel-agents) — original repo
- [rolandal/pixel-agents-standalone](https://github.com/rolandal/pixel-agents-standalone) — the fork we'll use

---

## The People Web — Surfacing Real Constellations

The People Web is one of the three reflections (map / web / list). Massive untapped potential. The principle: surface high-density real-person clusters, demote the noise.

### What we want
- High-density named clusters — multiple anchored perps connected by real edges (e.g. the Shaft family, the Lazar circle, the Yeshivah Centre web).
- Each visible node has a photo, real incidents, real severity.
- Each visible edge has a justifiable reason.

### What we don't want
- One real perp surrounded by 15 ghost relatives we know nothing about.
- Generic "unknown rabbi" placeholders.
- Photo-less, incident-less, severity-less nodes treated as equals to real ones.

### Interest score per cluster — auto-curated front page

Every connected sub-graph gets scored:
- + N for each named anchored perp
- + N for each incident, severity-weighted
- + N for each edge *between two named people* (not perp → ghost)
- + N for % of nodes with photos
- − N for % of ghost nodes

Top 10 constellations get featured on the People Web entry page. Visitors do not land on the hairball — they land on the curated set.

### Constellations as named stories

Each top constellation gets a name and a one-line description:
- **The Shaft Constellation** — *"Three generations of the Shaft family across Brooklyn, Crown Heights, and Lubavitch HQ. Seven named perpetrators. Connected by marriage and co-defendant ties."*
- **The Lazar Circle** — *"Berel Lazar at the center. Twelve named figures around him. Russian Federation cluster."*
- **The Yeshivah Centre Web** — *"Australia's largest documented institutional cluster. Royal Commission anchored."*

Curated entry points. Click to enter the constellation's space.

### Filters that hide noise (top-bar chips)
- Hide unphotographed nodes
- Only named perpetrators
- Only convicted / indicted
- Min incident count per node ≥ 2
- Hide cold paths

Click the chips to peel off ghosts. The graph turns into clean constellations.

### Photos as a first-class data type
A dedicated research beat: collect Wayback shul bios, JCW Wall of Shame portraits, court press photos, news article images. Every successful photo find turns a ghost node into a real one. Web densifies over time.

### Edge clarity — every line has a one-sentence reason
Hover an edge → see *why* they're connected:
- *"Co-defendants on docket [X] (2019)"*
- *"Brothers — named in family record"*
- *"Both held roles at Yeshivah Centre 2003–2008"*

If we can't justify an edge in one sentence, it's a junk edge. Flag for review, eventually prune.

### Time slider
Drag handle at the bottom. Pull back to 2010 → constellation shows only people/edges known then. Pull forward to today → watch the documented record fill in around the hub.

### Live "heat" — recently-touched nodes glow
Recently-updated nodes pulse softly. Lines up with the pixel office: when the Archivist files a new edge, that node pulses on the web. Visitors see active parts of the universe.

### Constellation permalinks
Every constellation has its own URL — `/web/shaft`, `/web/lazar`, `/web/yeshivah-centre`. Shareable, stable. Each becomes its own piece of journalism over time.

### Nobody clusters — collapsed by default
Single perp + ghost satellites: the perp shows, the ghosts hide behind a "+12 unnamed relatives" badge. Click to expand. Default view stays clean.

### Lonely-perp warning
A famous-enough perp showing up *with no connections* is its own signal — either the team hasn't found their network yet, or they really were a lone actor. Flag: *"no connections found — investigate?"* Auto-generates a lead for the research team.

### Cross-constellation bridges
The most interesting graph moments: when two big constellations share a single node — an institutional connector who appears in both the Yeshivah Centre web *and* the Crown Heights nexus. Highlight bridges visually. These are Morrow's high-betweenness connectors made visible.

### Is it all one web?
**Mixed — and that's the feature.**

- Some constellations are connected through bridge nodes (institutional connectors).
- Some are genuinely isolated (geography, era, or no documented overlap).

Toggle in the UI:
- Default: curated constellation view.
- "Show bridges" → faded lines stretch out to neighboring constellations, revealing the connectors.
- "Show full web" → the entire hairball, every node, every edge. The receipt.

Visitors can zoom in on one family OR pull out and see how the universe links together. The bridges are some of the most journalistically rich moments — the *"this connects to that?"* reveals.

### Fed by the research team automatically
The People Web reads from `people`, `family_relations`, `person_relations`, `incident_people` — the same tables the Archivist writes to every cycle. So:

- Every new confirmed perp → new node
- Every new co-defendant link → new edge
- Every new family relation → new edge
- Constellation scores re-run at snapshot time
- New clusters can emerge over time
- "Lonely perp" warnings can resolve as the team finds their network
- Bridge discoveries become real-time findings

The web is not a static visualization. It densifies as the team digs.

---

## UI Backlog (outside the research team work, but tracked here)

These are existing chabad-tracker UI issues to fix before launch, separate from the new research/visualization build:

- **Move stats to the top of the About page.** Currently they live on the DB page. The DB page is for browsing records; the About page is the natural home for "what this is, how big it is."
- **Remove the back button from the main DB landing page.** Sub-pages have a back button (correct — they go back to the DB list). The DB landing page itself has nowhere to go back to — the button is dead.
- **Filters on the left don't work.** Bug. Restore filter functionality on the DB browse view.
- **(Future) Add the pixel office to the About page** — once Phase 12 ships.
- **(Future) Add People Web constellation view** — once the web densification work in Phase 5 onward is solid.

---

*Brainstormed 2026-06-14. Ready for build phase on user signal.*
