# Build Roadmap — Chabad Tracker Research Bureau

*Synthesis of the three-consultant review of [researchteam.md](researchteam.md). This is the source-of-truth doc for the build phase.*

*Compiled 2026-06-14.*

---

## Load-Bearing Decisions

These three calls shape every choice below. They are not revisitable mid-build.

1. **v1 = full vision** — Phases 0–14. Clean DB + cloud researcher loop + pixel office on About page + mindboxes.
2. **Verifier = strict from day one** — all 12 layers active. Lower yield is acceptable; an unverified-feeling DB is not.
3. **Failure mode = watertight, no alerts** — *"If something breaks it just keeps going. No getting stuck ever."* Self-healing is the only failure pattern. No human in the loop. Ever.

---

## Consultant Headline Takeaways

**Platform & Reliability**
- Hash-pointer for the DB, not Git LFS, not raw commits. *(Implementation note: R2 was the original plan but requires a payment card on file even for free-tier; swapped to GitHub Releases as the asset backend. Same pattern — `data/chabad.db.url` + `data/chabad.db.sha256` committed; the DB blob lives at the release URL. See [devlog](devlog.md) 2026-06-14.)*
- `OPS_HALT` kill-switch file as the only manual brake.
- `concurrency:` group on every workflow to serialize writes (SQLite + git cannot survive concurrent writers).
- Lead `claimed_at` + 15min reclaim = the entire self-healing story for in-flight work.
- Atomic 5-step publish so 976/971/357 drift never recurs.
- Verifier uses raw HTTP, not search-pool APIs.

**Editorial Integrity**
- Build the Verifier in dependency order: spine (URL / name / quote / Wayback) week 1, editorial gates week 2, calibration week 3.
- Dual-track Phase 1 — don't pause publishing. Tag legacy rows `unaudited`. Audit as a background beat.
- Two-source minimum + Wayback freeze before any new named living person goes public.
- Quarantine is **public**, plain-English failure reasons. It's the integrity proof.
- Wording table — severity claims locked to source verbs. System can downgrade, never upgrade.
- Photo rules — provenance + license field mandatory, never under confidence 80.

**Frontend / UX**
- Fix the 976/971/357 lie *first* with a status bar + freshness banner. Honesty before features.
- UI backlog (filters, dead back button, stats relocation) ships in Phase 0 — credibility prerequisite.
- Pixel office register: muted palette, no sleeping Z's, no sound default, topic-gravity gate. Newsroom, not Tamagotchi.
- Mindboxes = log lines anchored under sprite on solid card, not floating speech bubbles.
- People Web entry = curated constellations, hairball is a toggle.
- Mobile: pixel office desktop-only, People Web simplified, map + DB fully mobile.
- Accessibility: text mirror of mindboxes ships in the same PR as the canvas. Not after.
- Confidence chip: label + number + popover with passed checks.

---

## Build Sequence — Reordered

The consultants' reordering reorganizes the phases from [researchteam.md](researchteam.md) so prerequisites land before dependents. This sequence is the actual build order.

### Phase 0 — Infrastructure prerequisites + UI honesty (week 1)

**Why first:** reliability infra has to land before the loop that depends on it. The site currently lies about its own freshness; that's the credibility floor for everything else.

**Tasks:**
- GitHub repo created (public). Branch protection on `main`. CODEOWNERS pinning `data/` and `ui/public/` to the bot identity.
- All cloud-pool keys loaded into Actions secrets (Cerebras × 4, Groq × 2, OpenRouter × 3, Tavily × 3, Exa × 3).
- `OPS_HALT` kill-switch file convention defined. (Touch the file from any device → all workflows early-exit.)
- `concurrency:` group rule documented for every workflow file.
- GitHub Releases used as the DB asset backend (R2 declined: requires payment card). Hash-pointer convention: commit only `data/chabad.db.sha256` + `data/chabad.db.url`. The DB itself lives at `https://github.com/rabbishimon613-lang/chabad-tracker/releases/download/db-<sha12>/chabad-<sha12>.db`.
- Vercel build step modified to pull DB by URL into `ui/public/chabad.db` and verify sha256. See [ui/build.sh](../ui/build.sh).
- **UI: status bar + freshness banner.** Every page. `data as of <ts> · <count> incidents · cycle <N> min ago`. Soft-refresh toast on data change, never auto-refresh.
- **UI: backlog fixed** — filters on left work, dead back button removed from DB landing, stats relocated from DB page to About page.
- **UI: confidence chip component** (skeleton — wired in Phase 1).
- **UI: reflection mismatch warning** — UI throws visible warning in footer if snapshot.json and loaded DB disagree on counts.

**Exit criteria:**
- ☐ Repo + secrets + R2 + Vercel wired.
- ☐ `concurrency:` group rule applied to every workflow file (placeholder workflows OK).
- ☐ Status bar live on the deployed site, showing current data freshness.
- ☐ All three UI backlog items fixed and deployed.
- ☐ Confidence chip + reflection mismatch warning ready to receive data.

---

### Phase 1 — Verifier spine + dual-track audit (weeks 2–3)

**Why now:** the Verifier is the load-bearing component, but ships in dependency order. The cheap, high-yield checks come first.

**Verifier build order:**

**Week 1 (spine):**
- Layer 1 — URL liveness (HEAD → 200).
- Layer 2 — name-on-page (exact full name appears).
- Layer 3 — verbatim quote (10-30 word quote from source page; verifier re-fetches + confirms).
- Layer 10 — Wayback freeze (fire-and-forget POST, snapshot URL stored alongside original).

**Week 2 (editorial gates):**
- Layer 5 — doctrine / role check, with role classifier on 200-char window (`perpetrator | victim | witness | bystander | unclear`, confidence ≥0.7).
- Layer 6 — severity ladder auto-downgrade (scan source for tier-above verbs; if absent, downgrade and re-verify).
- Layer 7 — source-class weighting (court / .gov / mainstream / Substack / anonymous).
- Layer 12 — perpetrator-only hard reject + known-victim allowlist.

**Week 3 (calibration):**
- Layer 4 — fact triangulation (name + 3 of 4 facts within 500 chars).
- Layer 8 — cross-source agreement.
- Layer 9 — independent second-pass LLM (different fleet model). Only fires on *new* perpetrator rows.
- Layer 11 — confidence score (0-100). 80+ archive, 50-79 archive flagged, <50 quarantine.

**Verifier infra rules:**
- All page-fetch layers (1, 2, 3, 4, 5, 6, 10) use **raw HTTP**, never Tavily/Exa. Search budget is preserved for discovery.
- Per-cycle page cache in `/tmp` keyed by URL — one fetch satisfies multiple layers.
- Wayback submission fire-and-forget.

**Dual-track audit of existing 976 incidents:**
- Add `audit_status` column to incidents: `unaudited | passed | quarantined`. Default all to `unaudited`.
- Verifier runs as a background beat — ~50 legacy rows/day. Pile clears in ~3 weeks.
- UI shows small gray "legacy, pending review" tag on `unaudited` rows.
- About page disclosure once: *"This dataset is undergoing a 12-layer re-verification pass through July 2026."*

**Quarantine table — public:**
- New route `/quarantine`. Robots.txt no-index.
- Rows show plain-English failure reason. ("Source URL doesn't mention this name." / "Conviction claim but source only says alleged.")
- Names redacted if the row failed at the name-on-page check.
- No photos on quarantine.

**Exit criteria:**
- ☐ All 12 layers implemented and unit-tested.
- ☐ Verifier runs against synthetic test cases (10 known-good, 10 known-bad) with expected outcomes.
- ☐ Dual-track audit beat scheduled and running.
- ☐ Public `/quarantine` route live.
- ☐ Confidence score appears in dossier UI.

---

### Phase 2 — Snapshot atomicity + freshness mechanism (week 4)

**Why now:** before the cycle starts writing live, the publish step has to be atomic, or the 976/971/357 drift recurs in the cloud.

**The atomic publish ritual (one script, called from exactly one place):**

```
1. VACUUM INTO /tmp/chabad.db.new
2. Generate snapshot.json from /tmp/chabad.db.new (NOT from live DB)
3. Upload /tmp/chabad.db.new to R2 → get sha256
4. Write ui/public/chabad.db.url, .sha256, snapshot.json in one commit
5. Push. Vercel rebuilds against a consistent triple.
```

If any step fails → nothing is committed. No partial publish. DB's `meta_publish` table records `(sha, snapshot_count, timestamp)` so the UI can self-check post-load.

**Exit criteria:**
- ☐ `snapshot_for_ui.py` rewritten as the atomic 5-step ritual.
- ☐ Run manually now to align live DB / published DB / snapshot.json (kill the existing drift).
- ☐ UI status bar reflects the current count after atomic publish.

---

### Phase 3 — Data cleanup (Phases 1–2 from researchteam.md) (week 5)

**Tasks:**
- Walk `person_match_candidates` — confirm or reject pending merges.
- Triage the 228 orphans by signal segment (URL / partial name / location-only / vague).
- Anchor more perps to houses (raise from 15% as high as possible).
- Backfill missing fields via sidecars — only on verified rows.

**Exit criteria:**
- ☐ Pending person_match_candidates = 0.
- ☐ Orphan count meaningfully reduced via targeted triage.
- ☐ House-anchoring rate above 30%.

---

### Phase 4 — Leads table + bootstrap (week 5–6)

**Tasks:**
- Create `leads` table schema:
  - `id`, `kind`, `payload_json`, `score`, `status` (`pending | claimed | resolved | dead`), `claimed_at` (NULLABLE), `parent_lead_id`, `created_at`, `resolved_at`.
- Create `lead_results` table.
- Create `quarantine` table (already in Phase 1).
- Add **edge_reason** as NOT NULL column on `family_relations` and `person_relations`. Every edge must justify itself in one sentence.
- Run all SQL lead generators against the cleaned DB:
  - Cold-path relatives
  - Hot-house rosters
  - Institution-hoppers
  - Long-tenure anomalies
  - Amount collisions
  - Family bridges
- Result: hundreds of starting leads, scored, ready.

**Lead self-healing mechanism (load-bearing):**
- Leads have `claimed_at` column.
- Researcher claims a lead → sets `claimed_at = now()`.
- Any lead with `claimed_at > 15 min ago` is **automatically reclaimable**. The next cycle picks it up. A crashed cycle silently has its work resumed.
- No DLQs. No retries. The DB is the queue.

**Exit criteria:**
- ☐ `leads`, `lead_results`, `quarantine` tables created.
- ☐ Edge-reason column added and populated for existing edges (or those edges go to review).
- ☐ Lead generators bootstrap ≥500 pending leads.

---

### Phase 5 — The Researcher (week 6–7)

**Tasks:**
- Build `research_one_lead.py`:
  - Reads top-scored pending lead.
  - Sets `claimed_at`.
  - Calls `search_batch` (Tavily/Exa) — capped at 3 searches per lead.
  - Calls `fleet_batch` (Cerebras/Groq/OR) — extracts structured JSON.
  - Returns: incidents, severity, co-defendants, sources, **verbatim quotes**, photo URLs.
  - Writes to `staging` table, not live tables.
- LLM extraction prompt requires verbatim quotes for every claim. No exceptions.
- Output filter: every proper noun must appear in the input facts. If LLM invented a name/place, reject and retry once.

**Cost guardrails (mandatory):**
- Per-cycle hard caps: 8 searches, 40 fleet calls, 90s wall-clock per Researcher dive.
- Pre-flight budget check at cycle entry. Exceeded → cycle exits 0 cleanly, commits nothing.
- `ops/budget.json` updated in `finally` block so crashes still record spend.

**Exit criteria:**
- ☐ Researcher runs one lead end-to-end, writes valid staging row.
- ☐ 10 consecutive Researcher runs complete without manual intervention.
- ☐ Budget tracking working (budget.json updates per call).

---

### Phase 6 — The Archivist + the Investigators (week 7–8)

**Tasks:**
- **Archivist**: promote Verifier-passed staging rows into live tables. Run sidecars. Spawn child leads. Mark parent resolved. Update `lead_results`.
- **Investigators**: build beats one at a time.
  - Week 7: family graph (cold-path relatives) — SQL only, no API cost.
  - Week 7: hot-house roster sweep.
  - Week 8: DOJ RSS poller.
  - Week 8: state AG RSS pollers.
  - Week 8: CourtListener new dockets.
  - Later: JCW poller, orphan triage.

**Movement choreography (visible in pixel office later):**
- Investigators → meeting table (drop lead).
- Researcher: meeting table → desk → meeting table (drop row).
- Verifier: seated, stamps → routes to Archivist or quarantine.
- Archivist: walks to desk, files.
- Publisher: mostly seated, occasionally pins to wall.

**Exit criteria:**
- ☐ Archivist promotes staging → live correctly.
- ☐ At least 3 Investigator beats running.
- ☐ Child leads spawn on every confirmed row.
- ☐ 10 consecutive full cycles run locally without intervention.

---

### Phase 7 — The Publisher (week 8)

**Tasks:**
- Build the atomic publish step (already exists from Phase 2 — call it).
- At end of each cycle:
  - Run `score_houses` (severity bands, color, color_band).
  - Run `compute_graph_metrics` (centrality, betweenness).
  - Run constellation scoring (interest score per sub-graph).
  - Run atomic publish ritual.
- Extend `snapshot.json` schema to include:
  - per-character last activity (for pixel office mindboxes)
  - per-node update timestamp (for People Web live heat)
  - cycle counters, budget remaining, last_cycle_at

**Exit criteria:**
- ☐ Publisher runs at end of every cycle.
- ☐ snapshot.json carries all data the UI needs (office + web + map).
- ☐ Three reflections always agree after publish.

---

### Phase 8 — Local soak test (week 9)

**Don't move to cloud yet.** Run the loop on your machine for at least 50 full cycles.

**Watch for:**
- Race conditions on lead claiming.
- Memory leaks across cycles.
- LLM extraction quality drift.
- Verifier false positives / negatives (calibrate confidence thresholds).
- snapshot.json + DB count agreement after every publish.
- Cost tracking accuracy.

**Exit criteria:**
- ☐ 50 consecutive cycles run cleanly.
- ☐ At least 100 confirmed new incidents added.
- ☐ Quarantine rate stable (~10-30%).
- ☐ No manual intervention needed.

---

### Phase 9 — Move to cloud (week 10)

**Tasks:**
- Write GitHub Actions workflows:
  - `researcher-cycle.yml` (full cycle, every hour, `concurrency: { group: cycle }`).
  - `investigator-rss.yml` (every 15 min, cheap, `concurrency: { group: rss }`).
  - `investigator-graph-walk.yml` (every 6 hours).
  - `audit-legacy.yml` (every 2 hours, 50 rows per run).
  - `ops-weekly.yml` (Sunday, writes `ops/weekly.md`).
- Every workflow has:
  - `timeout-minutes: 10`
  - `concurrency:` group (cycle / rss / graph / audit)
  - Pre-flight `OPS_HALT` check (`if test -f ops/OPS_HALT; then exit 0; fi`)
  - Pre-flight budget check
  - Ephemeral working branch: `cycle/<run_id>`
  - `post:` step that force-deletes branch + checkout on any non-zero exit
  - PR auto-merge on green CI
- CI gates on PRs:
  - Schema valid (views.sql applies cleanly)
  - No row deletions (counts only go up)
  - Foreign keys intact
  - Doctrine check (no Chabad-as-victim rows)
  - Budget sanity (cycle used < cap)
- Observability:
  - `ops/cycles.jsonl` — one line per cycle, committed at end of cycle.
  - Internal `/ops` route on Vercel — reads last 200 lines + budget.json. No login, just unlinked from public nav.

**Exit criteria:**
- ☐ First successful cloud cycle merged automatically.
- ☐ 10 consecutive cloud cycles run without manual intervention.
- ☐ `/ops` dashboard live and updating.
- ☐ `OPS_HALT` kill-switch tested.

---

### Phase 10 — People Web constellations (week 11–12)

**Tasks:**
- Build constellation scoring (runs at snapshot time):
  - +N for each named anchored perp
  - +N for each incident, severity-weighted
  - +N for each edge between two named people
  - +N for % nodes with photos
  - −N for % ghost nodes
- Curated entry page: top 10 constellations as cards with name + one-line + node count + photo mosaic.
- Constellation permalinks: `/web/shaft`, `/web/lazar`, `/web/yeshivah-centre`, etc.
- Each constellation has a name + one-line story (LLM-drafted, human-locked).
- Filter chips: hide unphotographed, only named perps, only convicted, min incidents ≥ 2, hide cold paths.
- Edge hover = one-sentence reason (uses `edge_reason` column).
- "Show full web" toggle (hairball is one click away, never the landing).
- "Show bridges" toggle — dashed amber lines, betweenness > 0.1 only.
- Live heat: soft pulse on recently-updated nodes, capped to ≤5 simultaneous.

**Time slider (Phase 10b, after constellations stable):**
- Each node/edge needs `first_documented_at` — sidecar populates.
- Drag handle pulls constellation back in time.

**Mobile People Web:**
- Constellation cards are list-friendly.
- Tap → simplified force graph (≤30 nodes).
- Full hairball desktop-only with explicit notice.

**Exit criteria:**
- ☐ Top 10 constellations visible on People Web entry page.
- ☐ Each top constellation has a name + permalink + one-line.
- ☐ Filter chips work.
- ☐ Edge reason shows on hover.
- ☐ Mobile fallback ships.

---

### Phase 11 — Pixel office shell (week 13)

**Tasks:**
- Fork [rolandal/pixel-agents-standalone](https://github.com/rolandal/pixel-agents-standalone).
- Strip Express server + JSONL session watcher.
- Replace with `setInterval` poller that fetches `/snapshot.json` every 5 seconds.
- Map cycle state → engine's `agentStatuses` dictionary.
- Edit layout JSON for 9 stations (3 Investigators, 3 Researchers, 1 Verifier, 1 Archivist, 1 Publisher + meeting table).
- Drop in free Penzilla + Anokolisa packs.
- CSS desaturation pass: global filter `saturate(0.6)`.
- Strip sleeping Z's, hearts, sparkles from sprite frames.
- Sound default off.
- Credit footer mandatory: Penzilla credit + doctrine note (*"This office depicts an automated research process. The work it represents is real."*)

**Exit criteria:**
- ☐ Pixel office renders on `/about` desktop view.
- ☐ Polls `snapshot.json`, no server dependency.
- ☐ 9 characters in 9 stations.
- ☐ Muted palette, no cute affordances.

---

### Phase 12 — Mindboxes + topic-gravity gate (week 14)

**Tasks:**
- Mindboxes = terminal log lines anchored below each sprite. Not floating speech bubbles.
- Monospace (JetBrains Mono / IBM Plex Mono), 12-13px desktop, 11px mobile.
- Solid card background `rgba(20,20,24,0.92)` behind every mindbox. 4px border-radius.
- Hard cap 140 chars, wraps 2 lines max. Truncate with ellipsis, full on hover/tap.
- Color coding via typed token system (LLM can't paint outside the lines).
- LLM-generated flavor with hallucination clamp (every proper noun must appear in input facts).
- Phrase pool fallback for filter failures.
- **Topic-gravity gate**: when latest cycle touched a high-severity claim (CSA, conviction), suppress "playful" mindbox candidates for next 10 min.
- 24-hour cache by (role + event type + fact hash).
- Weekly human sample: last 100 generated lines dumped to private gist for review.

**Live heat in People Web** (wires into the same poller):
- Recently-updated nodes pulse softly (≤5 simultaneous).
- Hooked to snapshot.json's per-node timestamp.

**Pixel office entry pattern (desktop + mobile, same UX):**
- About page loads light: stats at top → existing about text → big button at bottom labeled *"Step into the office →"* (or similar).
- A small "live" dot pulses next to the button so visitors know it's active right now.
- Click → loads the live canvas inline (or full-screen takeover on mobile).
- Polling starts only after click. Stops when leaving the page.
- Same engine on both desktop and mobile. Mobile users pinch-zoom + pan to explore the bureau.
- Saves bandwidth + battery + first-paint time for visitors who don't engage. Click is the intent signal.

**Accessibility (mandatory, ships with each component):**
- `aria-live="polite"` region mirroring all mindboxes in plain text.
- Canvas: `role="img" aria-label="autonomous research office, currently active"`.
- "Text-only office" link in footer renders same mindboxes without canvas.
- `prefers-reduced-motion` kills sprite animation + live heat.

**Exit criteria:**
- ☐ Mindboxes render with terminal log-line style.
- ☐ LLM flavor passes filter ≥95% of the time.
- ☐ Topic-gravity gate verified on a high-severity test case.
- ☐ Screen reader can navigate office state without canvas.
- ☐ Mobile fallback ships.

---

### Phase 13 — Soak + tune (week 15+, forever)

- Let it run.
- Monitor `/ops` dashboard once a week.
- Tune Verifier thresholds based on quarantine outcomes.
- Add Investigator beats as needed (multilingual, ICIJ, etc.).
- Curate constellation names + stories as they emerge.
- Watch the dataset grow.

---

## The Watertight Self-Healing Pattern (the spine)

The user's #3 decision — *"no getting stuck ever"* — is enforced by these mechanisms working together:

1. **Per-workflow `timeout-minutes: 10`** + `concurrency:` group. Hung cycle dies on its own. Queued cycle waits, doesn't pile up.
2. **Ephemeral branches** (`cycle/<run_id>`). Non-zero exit → branch force-deleted in `post:`. Main never touched.
3. **State lives in the DB, not branch.** Next cycle reads `leads` from main, picks up where dead cycle left off.
4. **Lead reclaim** — `claimed_at > 15 min ago` is reclaimable. Crashed cycle's work resumed silently.
5. **Per-row verification filtering**, not per-PR blocking. Bad rows quarantine. Good rows always merge. PR never fails.
6. **Auto-retry once** at Researcher level with stricter prompt. Then quarantine.
7. **Crash = no PR opens.** Next cron tick retries cleanly.
8. **Cost overrun = clean abort.** Commits nothing. Doesn't burn budget on a doomed cycle.
9. **`OPS_HALT` file** in repo = manual brake without revoking secrets. Touch the file → all workflows early-exit on next tick.
10. **Per-cycle JSONL log** in `ops/cycles.jsonl` — committed at end of cycle. Even crashes record what they did before dying.

No alerts. No human notifications. The system absorbs failure as a normal state of operation.

---

## Cost Guardrails

**Per-cycle hard caps:**
- 8 searches max (Tavily + Exa combined)
- 40 fleet calls max
- 90s wall-clock max per Researcher dive

**Per-day soft caps:**
- 80 Tavily calls (leaves 20 headroom for backfill)
- 80 Exa calls (same)
- Cerebras + Groq + OR: pooled, fail-over, generous

**Enforcement:**
- `ops/budget.json` checked at cycle entry. Insufficient → exit 0 cleanly.
- Every API client wrapped in counter. Flushed to budget.json in `finally`.
- `BudgetExceeded` exception aborts cycle, commits nothing.

**Daily reset:** first cycle each day resets `budget.json`.

---

## Risk Register

| Risk | Mitigation | Phase |
|---|---|---|
| **Concurrent DB writers corrupt SQLite** | `concurrency:` group on every workflow | 0 |
| **DB-in-git bloats repo over months** | R2 hash-pointer, not LFS | 0 |
| **Three reflections drift** | Atomic 5-step publish ritual | 2 |
| **Hallucinated person at real institution** | Layer 2 + 3 + 4 (name + quote + triangulation) | 1 |
| **Severity inflation** | Hard downgrade rule, locked wording table | 1 |
| **Victim catalogued as perpetrator** | Role classifier + headline test + known-victim allowlist | 1 |
| **Link rot erodes evidence** | Wayback freeze on insertion | 1 |
| **Same-name collision** | Geographic + temporal anchoring required | 1 |
| **Search budget burn from Verifier** | Verifier uses raw HTTP, never search APIs | 1 |
| **Lead orphaned by crashed cycle** | `claimed_at` + 15min reclaim | 4 |
| **Cycle budget runaway** | Pre-flight check + `finally` flush | 5 |
| **Pixel office reads as cute** | Desaturation + sound off + topic-gravity gate + credit doctrine | 11–12 |
| **People Web lands as hairball** | Curated constellations as only public entry point | 10 |
| **Accessibility shipped as afterthought** | a11y in same PR as canvas, not later | 12 |
| **Defamation exposure** | 2-source minimum + Wayback + wording lock + right-of-reply column | 1 |

---

## Definition of Done (v1 ships when)

- ☐ All Phase 0–12 exit criteria checked.
- ☐ Cloud researcher loop has run unattended for 7 consecutive days.
- ☐ ≥100 new confirmed incidents added since deployment.
- ☐ Quarantine rate stable (10-30%).
- ☐ Three reflections always agree after every publish.
- ☐ `/ops` dashboard accessible and updating.
- ☐ Pixel office on About page renders the live state.
- ☐ People Web shows ≥5 named constellations.
- ☐ Mobile fallback ships for every desktop-only view.
- ☐ Accessibility checklist passes for every shipped component.
- ☐ `OPS_HALT` kill-switch tested and working.

---

## What v2+ looks like (not in scope for v1, parked here)

- Photo collection beat (dedicated Investigator on Wayback bios + JCW photos + court press pool).
- Time-slider on People Web (after constellations stable).
- Multilingual Investigator beats (Hebrew, Yiddish, Portuguese, French).
- ICIJ Offshore Leaks cross-reference.
- Royal Commission transcript NER pass.
- Survivor-network outreach data integration (separate trust track).
- Hot-house cluster pages (dedicated permalinks per major institution).
- Per-region landing pages (Australia, Crown Heights, Israel, Russia, etc.).
- Right-of-reply public submission form.

---

*Compiled from researchteam.md + three-consultant review, 2026-06-14. This is the build spec.*
