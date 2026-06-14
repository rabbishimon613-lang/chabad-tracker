# Fleet Charts Library
## Chabad Tracker — Search & Research Playbook

Last updated: 2026-06-13 | DB at 742 incidents

---

## DOCTRINE (never changes)
- Track Chabad/Lubavitch as **PERPETRATOR only** — never victim
- "Chabad" or "Lubavitch" must appear **explicitly** in the source
- "Jewish," "Hasidic," "Orthodox" alone = EXCLUDE
- Cover-ups of Chabad crimes = INCLUDE (perpetration by institutional protection)
- Co-conspirators who are NOT themselves Chabad = EXCLUDE

---

## HARD-LEARNED RULES (from expedition log)

### What works
- Named-person + "Chabad" + court action = highest precision
- Exa for multilingual, temporal, content-rich extraction
- Tavily for broad news coverage
- Max **5 queries per batch** with `include_content=true` (overflow at 6+)
- Max **8 queries per batch** without content (safe ceiling)
- Always delegate large result files to subagent with explicit path
- Pre-check DB before writing — ~40% of finds are already in DB
- Write Python directly to `snippet_extracts.jsonl`, run `load_snippet_extracts.py`

### What fails
- `site:justice.gov` direct → SSL errors, use search instead
- WebFetch on paywalled sites (LAT, TOI, Haaretz) → blocked
- `include_content=true` on batches >5 → context overflow every time
- Broad geographic sweeps (Africa, Latin America) → near-zero yield, confirmed sparse
- Country-by-country global sweep → diminishing returns, trap
- PACER direct → costs money per page

### Pre-dedup (run before every write)
```bash
sqlite3 data/chabad.db "SELECT id, summary FROM incidents WHERE summary LIKE '%<name>%';"
```

---

## CHART LIBRARY

---

### CHART A — "Source-First Sweep" (Wave 3 — run FIRST)
**Purpose:** Harvest untapped sources before doing keyword mining
**Engine:** Exa for Hebrew/multilingual; Tavily for English news
**Batch size:** 5 max with content, 8 without

```
BATCH A1 — US Government Sources (Tavily, no content)
"site:justice.gov chabad fraud indictment"
"site:justice.gov lubavitch rabbi guilty plea"
"site:justice.gov chabad rabbi convicted sentenced"
"site:ag.ny.gov chabad rabbi fraud"
"site:njoag.gov chabad rabbi arrested convicted"

BATCH A2 — Internal Chabad Media (Tavily, no content)
"site:collive.com chabad rabbi arrested convicted"
"site:crownheights.info rabbi arrested charged crime"
"site:vinnews.com chabad rabbi convicted sentenced"
"site:matzav.com chabad rabbi arrested fraud abuse"
"site:yeshivaworld.com chabad rabbi arrested charged"

BATCH A3 — Israeli Hebrew Sources (Exa, no content)
"חב\"ד רב נעצר הורשע הונאה"          [Chabad rabbi arrested convicted fraud]
"חב\"ד רב עצור אשמה מעצר"             [Chabad rabbi detained charge arrest]
"חב\"ד ניצול מיני הרשעה"              [Chabad sexual exploitation conviction]
"חב\"ד הונאה מס כתב אישום"            [Chabad tax fraud indictment]
"חב\"ד הלבנת הון הרשעה"               [Chabad money laundering conviction]

BATCH A4 — Court Records (Exa, no content)
"site:courtlistener.com chabad fraud conviction"
"site:courtlistener.com chabad rabbi guilty plea"
"site:courtlistener.com lubavitch money laundering"
"site:courtlistener.com chabad sexual abuse"
"site:courtlistener.com lubavitch fraud sentenced"
```

**Yield:** +25–40 new cases (Israeli sources = biggest untapped vein)
**Note:** courtlistener.com returns PDFs with no snippets — fetch the most promising URLs individually

---

### CHART B — "Crime-Type Gaps" (Wave 2)
**Purpose:** Mine underrepresented crime types across full date range
**Engine:** Tavily (broad news coverage)
**Batch size:** 5 per batch

```
BATCH B1 — Immigration & Visa Fraud
"Chabad rabbi \"immigration fraud\" convicted sentenced"
"Chabad rabbi \"visa fraud\" convicted sentenced"
"Lubavitch rabbi immigration fraud guilty plea"
"Chabad \"green card fraud\" OR \"fake visa\" arrested"
"Chabad rabbi smuggling aliens convicted"

BATCH B2 — Insurance & Property Fraud
"Chabad rabbi \"insurance fraud\" convicted sentenced"
"Chabad \"arson\" building fire arrested convicted"
"Chabad rabbi \"insurance\" fraud guilty plea sentenced"
"Lubavitch arson fire insurance investigation"
"Chabad house fire suspicious insurance claim"

BATCH B3 — Welfare & Benefits Fraud
"Chabad rabbi \"welfare fraud\" convicted sentenced"
"Chabad \"Medicaid fraud\" convicted sentenced"
"Lubavitch rabbi food stamps welfare fraud arrested"
"Chabad school \"Medicaid fraud\" OR \"Medicare fraud\""
"Chabad nonprofit benefits fraud indictment"

BATCH B4 — Kidnapping, Extortion, Get-Coercion
"Chabad rabbi kidnapping extortion convicted sentenced"
"Chabad rabbi get coercion kidnapping guilty plea"
"Lubavitch rabbi extortion ransom arrested"
"Chabad rabbi \"forced get\" kidnapping convicted"
"Chabad extortion scheme indicted sentenced"

BATCH B5 — Drug Trafficking (beyond Crown Heights 2014 cluster)
"Chabad rabbi drug trafficking convicted sentenced"
"Lubavitch rabbi narcotics drug dealing arrested"
"Chabad emissary drug trafficking arrested convicted"
"Chabad rabbi cocaine heroin sentenced"
"Lubavitch drug ring money laundering convicted"
```

**Yield:** +15–25 new cases
**Key gap:** Immigration fraud and arson are near-zero in DB — high upside

---

### CHART C — "Time-Gap Fill" (Wave 1)
**Purpose:** Mine pre-1995 historical cases and 2023–2026 recent cases
**Engine:** Exa (better temporal indexing with date filters)
**Batch size:** 5 max

```
BATCH C1 — Recent Cases (2023–2026)
"Chabad rabbi arrested convicted 2024 2025"
"Chabad rabbi indicted sentenced 2023 2024"
"Lubavitch rabbi charged guilty 2024 2025 2026"
"Chabad director arrested fraud 2023 2024 2025"
"Chabad emissary shliach arrested convicted 2024 2025"

BATCH C2 — Historical Cases (pre-1995)
"Chabad rabbi convicted sentenced 1985 1986 1987 1988 1989 1990"
"Chabad rabbi convicted sentenced 1991 1992 1993 1994 1995"
"Lubavitch rabbi fraud abuse crime convicted 1980s 1990s"
"Chabad money laundering indicted 1987 1988 1989 1990"
"Chabad rabbi sexual abuse convicted 1990 1991 1992 1993 1994"
```

**Yield:** +20–35 new cases
**Note:** 1988 ring (UPI archives, NJ indictment) is promising — 16 indicted, Chabad-linked

---

### CHART D — "PPP & Federal Aid Fraud" (Wave 4 — always-on enrichment)
**Purpose:** Cross-reference SBA loans and federal grants against known Chabad entities
**Engine:** Tavily
**Batch size:** 5

```
BATCH D1 — COVID/PPP Fraud
"Chabad PPP loan fraud indicted convicted"
"Chabad \"PPP\" OR \"CARES Act\" fraud arrested sentenced"
"Lubavitch \"Paycheck Protection\" fraud indictment"
"Chabad school PPP fraud guilty plea"
"Chabad nonprofit COVID relief fraud convicted"

BATCH D2 — Education & Grant Fraud
"Chabad school \"Title IV\" fraud convicted indicted"
"Chabad yeshiva federal grant fraud arrested"
"Chabad \"student aid\" fraud convicted sentenced"
"Lubavitch school federal funds fraud indicted"
"Chabad education fraud guilty plea sentenced"
```

**Yield:** +10–20 new cases
**Key tool:** ProPublica Nonprofit API — `https://projects.propublica.org/nonprofits/api/v2/search.json?q=chabad` for EINs with legal flags

---

### CHART E — "Super-Query Dragnet" (cross-domain)
**Purpose:** Catch cases that slip through source-specific searches
**Engine:** Exa (site-restricted to .gov and court domains)
**Batch size:** 5

```
BATCH E1 — .gov Court Domains
"(chabad OR lubavitch) (indictment OR \"pleaded guilty\" OR convicted) site:gov"
"(chabad OR lubavitch) (fraud OR \"money laundering\") site:justice.gov"
"chabad rabbi arrested convicted sentenced site:nycourts.gov"
"lubavitch fraud conviction site:courts.ca.gov"
"chabad rabbi sentenced prison site:uscourts.gov"
```

**Yield:** +10–15 new cases
**Note:** Returns PDF links — need individual fetch to extract names

---

### CHART F — "ProPublica + OFAC Enrichment"
**Purpose:** Systematic nonprofit and sanctions cross-reference
**No search API needed — direct API calls**

```python
# ProPublica — get all Chabad EINs with legal flags
import requests
url = "https://projects.propublica.org/nonprofits/api/v2/search.json?q=chabad&page=0"
data = requests.get(url).json()
# Filter for organizations with 'lawsuit' or 'penalty' in 990 schedules

# OFAC sanctions — check for Chabad entities
ofac_url = "https://api.treasury.gov/ofac/sanctions/v2/sdn-list?program=SDNLIST&keyword=chabad"
```

**Yield:** +5–10 new cases
**Note:** Most useful for identifying PPP fraud targets by EIN

---

### CHART G — "Registry of Convicted-Persons Cross-Reference"
**Purpose:** Surface principals already on public conviction registries — strongest possible confidence signal (sentencing record on the state's own server)
**Engine:** `search_batch` (Tavily) for the discovery layer, `Claude_in_Chrome` for the registry query layer (most state registries require form submission, no clean URL pattern)
**Batch size:** 5 per batch (Tavily); chrome runs serially per state
**Status:** NOT BUILT — no script yet, no bucket file

```
BATCH G1 — National Sex Offender Public Website (NSOPW federal aggregator)
Submit each of the 467 named principals as a name query.
Endpoint: https://www.nsopw.gov/  (form-based, JS-rendered — chrome required)
For each hit: capture jurisdiction, registration date, offense statute, photo.

BATCH G2 — State Criminal History Portals (where free)
- NY DOCCS Inmate Lookup — https://nysdoccslookup.doccs.ny.gov/
- NJ DOC Offender Search — https://www20.state.nj.us/DOC_Inmate/inmatesearch
- FL DOC Offender Search — http://www.dc.state.fl.us/offendersearch/
- CA DOC Inmate Locator — https://inmatelocator.cdcr.ca.gov/
- IL DOC Inmate Search — https://www2.illinois.gov/idoc/Offender/Pages/InmateSearch.aspx
Submit principals located in each state (use chabad_houses join).

BATCH G3 — Tavily discovery for unfamiliar registries
"<state> registered offender search portal site:.gov"
"<state> department of corrections inmate search"
"<state> public conviction record search free"
```

**Yield:** Estimated +30–60 confirmed-conviction hits with sentencing data. Highest-confidence signal in the entire library.
**Note:** Output gets a new column `registry_hit` on incidents (jurisdiction, statute, registration date). Do NOT publish photos; record reference only.

---

### CHART H — "CourtListener REST + PACER Expansion"
**Purpose:** Move beyond Chart A4 (Exa `site:courtlistener.com`) to the structured REST API and selectively into PACER for high-value dockets
**Engine:** `WebFetch` against CourtListener REST v4 (free, no key needed for read); `Claude_in_Chrome` for PACER docket pages (login required, $0.10/page cap)
**Batch size:** 10 API calls per fanout — REST is cheap
**Status:** SCAFFOLDED — `scrape/courtlistener_sweep.py` and `scrape/bucket_aa_court_records.py` exist; chart documents the query strategy

```
BATCH H1 — Docket search by entity name
GET https://www.courtlistener.com/api/rest/v4/search/?type=r&q=<entity>
Iterate over: each chabad house name, each principal name, each related nonprofit.
Returns docket ID, court, date filed, nature of suit, parties.

BATCH H2 — Opinion search for written rulings
GET https://www.courtlistener.com/api/rest/v4/search/?type=o&q=<entity>
Returns appellate opinions naming the entity — narrative facts often cite the underlying case.

BATCH H3 — RECAP archive (free PACER mirror) for high-value dockets
GET https://www.courtlistener.com/api/rest/v4/recap-documents/?docket=<id>
Pull complaints, indictments, plea agreements, sentencing memoranda.

BATCH H4 — Targeted PACER (chrome, gated)
ONLY for dockets where RECAP returns no documents AND H1/H2 confirmed entity match.
One docket = one tab in chrome; cap at 10 dockets/session to control cost.
```

**Yield:** Estimated +40–80 cases with full docket evidence; replaces brittle Exa scraping for court records.
**Note:** Output writes to a new `dockets` table (docket_id, court, parties, nature_of_suit, key_documents); join to incidents via party-name match.

---

### CHART I — "Public Inquiry Transcript Mining"
**Purpose:** Extract structured evidence from long-form public inquiries that named the organization
**Engine:** `WebFetch` for PDF retrieval; `fleet_batch` with `longcontext` role for chunked extraction
**Batch size:** 1 inquiry at a time; 50-page chunks to longcontext
**Status:** PARTIAL — `scrape/bucket_t_aussie_royal.py` exists for AUS; other jurisdictions unchartered

```
BATCH I1 — AUS Royal Commission into Institutional Responses (DONE — confirm exhausted)
URL: https://www.childabuseroyalcommission.gov.au/case-studies
Case Study 22 (Yeshivah Melbourne/Yeshivah Bondi) — 5,000+ pages
Verify scrape/bucket_t_aussie_royal.py has covered transcripts AND tendered exhibits.

BATCH I2 — UK Independent Inquiry into Child Sexual Abuse (IICSA)
URL: https://www.iicsa.org.uk/reports-recommendations/publications
Search published reports for "Chabad" / "Lubavitch"; pull transcripts of named hearings.

BATCH I3 — Canadian inquiries
- Cornwall Public Inquiry archive
- Provincial inquiries into religious-institutional abuse (Quebec, Ontario)
Tavily discovery: "Canada public inquiry religious institutional abuse Chabad"

BATCH I4 — Israeli State Comptroller reports
URL: https://www.mevaker.gov.il/  (Hebrew — Exa with Hebrew queries)
"מבקר המדינה חב\"ד דוח"  [State Comptroller Chabad report]
Often surfaces financial irregularity findings against religious institutions.

BATCH I5 — US Congressional hearings
URL: https://www.congress.gov/  REST API or `Claude_in_Chrome`
Search: "Chabad" hearings in Judiciary, Oversight, Foreign Affairs committees.
```

**Yield:** Estimated +15–25 deeply-documented cases. Inquiry findings carry near-court-level evidentiary weight.
**Note:** Long PDFs go through `mcp__llm-fleet__worker_longcontext` for entity extraction; schema = (inquiry_name, page_range, named_principal, finding_text, exhibit_refs).

---

### CHART J — "Wayback CDX Bio Recovery"
**Purpose:** Recover deleted staff/biography pages from chabad.org subdomains and individual house sites — captures the moment of suppression
**Engine:** `WebFetch` against Wayback CDX JSON API (no scraping, no key); `fleet_batch` fast role for diff extraction
**Batch size:** 20+ domain queries in parallel
**Status:** PARTIAL — `scrape/fasttrack_wayback.py` and `scrape/fetch_wayback_gentle.py` exist; chart documents which surfaces to walk

```
BATCH J1 — Staff/about pages on all known house domains
For each domain in chabad_houses.website:
GET https://web.archive.org/cdx/search/cdx?url=<domain>/staff/*&output=json&collapse=urlkey
GET https://web.archive.org/cdx/search/cdx?url=<domain>/about/*&output=json
GET https://web.archive.org/cdx/search/cdx?url=<domain>/team/*&output=json
Returns all archived snapshots — identify URLs that EXISTED THEN but 404 NOW.

BATCH J2 — chabad.org central directory snapshots
GET https://web.archive.org/cdx/search/cdx?url=chabad.org/centers/*&output=json
Build a year-by-year map of which houses listed which directors.
Diff against current chabad.org directory — captures quiet removals.

BATCH J3 — Press-release & news subdomains
GET https://web.archive.org/cdx/search/cdx?url=chabad.org/news/*&output=json
GET https://web.archive.org/cdx/search/cdx?url=collive.com/*&output=json&from=20100101
Retracted articles often survive as Wayback captures.

BATCH J4 — Diff extractor (fleet_batch fast role)
For each (old_snapshot, missing_now) pair:
prompt = "Extract names, titles, photos from this archived staff page. Format as JSON."
```

**Yield:** Estimated +50–100 principal-to-house mappings recovered, +unknown number of retracted articles. Highest value for the cover-up signal.
**Note:** Output adds a `wayback_snapshot` column to chabad_house_staff (snapshot_url, capture_date, removed_by_date_if_known). Critical for "deleted bios" suppression evidence.

---

### CHART K — "State AG Press-Release Real-Time Monitor"
**Purpose:** Catch new cases at announcement, not 6 months later via news cycle. Extends CHART A1 (one-shot AG search) into a standing cron.
**Engine:** `scheduled-tasks` cron firing `search_batch` against each AG press-release portal
**Batch size:** 1 query per AG, fired hourly or 12-hourly
**Status:** NOT BUILT — `scrape/sidecar_doj_rss.py` exists for federal DOJ; state AGs unmonitored

```
BATCH K1 — Tier-1 AG monitors (densest Chabad presence)
Cron: every 6h
For each AG below, search press releases since last-run timestamp:
- NY AG     https://ag.ny.gov/press-releases     keyword: chabad OR lubavitch OR rabbi
- NJ AG     https://www.nj.gov/oag/newsreleases  keyword: chabad OR lubavitch OR rabbi
- FL AG     http://myfloridalegal.com/newsrel.nsf  keyword: chabad OR lubavitch OR rabbi
- CA AG     https://oag.ca.gov/news               keyword: chabad OR lubavitch OR rabbi
- IL AG     https://www.illinoisattorneygeneral.gov/pressroom  keyword: chabad OR lubavitch OR rabbi
- MA AG     https://www.mass.gov/news             keyword: chabad OR lubavitch OR rabbi

BATCH K2 — Federal monitors (extend sidecar_doj_rss.py)
- DOJ Public Integrity Section press feed
- DOJ Tax Division indictments feed
- IRS Criminal Investigation press feed
- SEC litigation releases

BATCH K3 — Staging table workflow
Each hit → staging_ag_hits table (ag_office, release_date, url, headline, matched_keyword)
Twice daily: triage staging → fleet_batch reasoning role → promote to incidents if confidence ≥ 0.6
```

**Yield:** Estimated +1–3 new cases per month, captured 1–6 months earlier than passive news monitoring. Compounds.
**Note:** Implement via `mcp__scheduled-tasks__create_scheduled_task`. Output is the only chart designed to never be "exhausted" — runs forever.

---

## INTERNAL-DB METHODS (not chart work — listed here for completeness)

These came up in the methods audit but live as Python scripts against the existing DB, NOT as fleet charts:

- **Family cold-path graph walk** — pure SQL on chabad_house_staff + family_inference views. Query is sketched in `notes/expert_roundtable.md`.
- **Co-defendant centrality** — `scrape/snowball_coperps.py` exists; extend with networkx betweenness on incident-co-defendant graph.
- **Hot-house full coverage** — a strategy applied to existing charts (filter `chabad_houses` by badness_score > threshold, fan out CHARTS A/B/E queries against principals at those houses), not a new chart.

---

## EXPEDITION LOG — What Each Wave Actually Yielded

| Expedition | Date | Wave | Queries Fired | New Cases Found | Already in DB | Notes |
|------------|------|------|---------------|-----------------|---------------|-------|
| Session 1 (this session) | 2026-06 | Geographic | ~20 | 8 new | ~60% dupes | Latin America sparse confirmed |
| Tier 1 fleet sweep | 2026-06 | Mixed | ~30 | 12 found | 10 already in DB | Exa better than Tavily for content |
| Optimized expedition | 2026-06 | All waves | ~35 | 1 new (Israel extortion 35) | ~95% dupes | Strong saturation signal on known sources |

**Saturation signal:** When >90% of finds are already in DB on a given source, that source is exhausted. Move to next chart.

---

## DEDUP PROTOCOL

Before writing any record:
```bash
# Name check
sqlite3 data/chabad.db "SELECT id, summary FROM incidents WHERE summary LIKE '%<name>%';"

# Batch pre-check (Python)
python3 -c "
import sqlite3, json
con = sqlite3.connect('data/chabad.db')
known = set(r[0][:80].lower() for r in con.execute('SELECT summary FROM incidents'))
candidate = '<first 80 chars of new summary>'.lower()
print('DUPLICATE' if candidate in known else 'NEW')
"
```

## CONFIDENCE TIERS

| Score | Source Type | Action |
|-------|-------------|--------|
| 1.0 | DOJ/FBI press release, state AG, court record | Auto-write |
| 0.8 | Haaretz, Forward, JTA, TOI | Auto-write |
| 0.6 | COLlive, VINnews, CrownHeights.info | Write with note |
| 0.4 | Community blogs, powerbase.info | Verify with second source first |
| 0.2 | Social media, anonymous tips | Do not write |

---

## PIPELINE (how every new record flows)

```
Search batch → subagent parses → DB pre-check → Python writes to snippet_extracts.jsonl
→ load_snippet_extracts.py → cp data/chabad.db ui/public/chabad.db → vercel deploy
```

```bash
# Full deploy pipeline
cd /Volumes/EOS_DIGITAL/chabad-tracker
python3 scrape/load_snippet_extracts.py
cp data/chabad.db ui/public/chabad.db
cd ui && ~/.bun/bin/vercel --prod --archive=tgz
```

---

## REMAINING VEINS (ordered by estimated yield — re-ranked 2026-06-13)

1. **Wayback CDX bio recovery** (CHART J) — +50–100 principal/house mappings, captures suppression — UNTAPPED, scripts scaffolded
2. **CourtListener REST + RECAP** (CHART H) — +40–80 cases with full docket evidence, replaces brittle Exa scraping — UNTAPPED, scripts scaffolded
3. **Registry of convicted-persons cross-ref** (CHART G) — +30–60 sentencing-confirmed hits, highest possible confidence — NOT BUILT
4. **Israeli Hebrew press** — Maariv, Ynet, Calcalist, Kikar HaShabbat (CHART A3) — UNTAPPED
5. **State AG real-time monitor** (CHART K) — +1–3/month, compounds forever — NOT BUILT
6. **Public-inquiry transcripts** (CHART I) — IICSA/Canadian/Israeli/Congressional — PARTIAL (AUS only)
7. **Time gaps** — pre-1995 historical (1988 NJ ring promising) and 2023-2026 recent (CHART C) — MOSTLY UNTAPPED
8. **Crime-type gaps** — immigration fraud, insurance fraud, welfare fraud (CHART B) — MOSTLY UNTAPPED
9. **PPP/COVID fraud** — ProPublica EIN cross-ref (CHART D / F) — UNTAPPED
10. **German/French/Spanish sources** — Exa multilingual on European Chabad cases — MOSTLY UNTAPPED
