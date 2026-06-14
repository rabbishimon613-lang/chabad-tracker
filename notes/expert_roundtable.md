# Expert Roundtable: Expanding the Knowledge Base
*Five specialist consultants on how to grow, enrich, and connect the tracker.*
*DB state at time of consultation: 971 incidents · 743 linked · 228 orphans · 467 named perps · 71 anchored (15%) · 3,050 family edges · 354 co-defendant edges*

---

## The Panel

| Name | Background | Specialty |
|---|---|---|
| **Sarah Chen** | Ex-Bellingcat, built Yemen arms-tracking DB | OSINT, digital footprints, Wayback Machine forensics, corporate registry mining |
| **Michael Torrence** | Ex-ICIJ/ProPublica, Nonprofit Networks investigation | Database journalism, PACER, 990 forms, structured court records |
| **Ravi Kowalski** | Ex-FinCEN analyst | Financial forensics, follow-the-money, real estate records, SAR cross-reference |
| **Dr. Lena Hartmann** | Institutional abuse researcher, Royal Commission published | Survivor networks, clergy abuse databases, cover-up pattern analysis |
| **Jake Morrow** | Ex-law enforcement, co-defendant analysis methodology | Link intelligence, graph theory, network centrality, criminal network mapping |

---

## Core Diagnosis

> *"Your 971 incidents is more like a 25–30% sample of the actual universe. The Royal Commission found Yeshivah Centre's actual case count was roughly 3–4x what had been publicly reported. That ratio probably holds across the dataset. You're building a documented record, not a comprehensive one — and that distinction matters for how you interpret the connections."*
> — Dr. Hartmann

Three structural weaknesses identified unanimously:

1. **Graph underuse** — 3,050 family edges and 354 co-defendant edges exist but are almost never queried graph-to-graph. The social network is built; it's just not being walked.
2. **Pre-digital blind spot** — Dragnet scraping finds post-2000 cases. The 1980s and 1990s exist only in newspaper archives, court records, and survivor organization files.
3. **Coverage bias** — Cases resolved internally through rabbinical courts, community pressure, or NDAs are systematically absent. Documented suppression is its own signal and should be tracked.

---

## Methods, Ranked by ROI

### Tier 1 — Do First (1 day or less, high yield)

#### 1. Sex Offender Registry Cross-Reference
**Champion: Chen**

Every US state has a public sex offender registry. Most support bulk download or structured scraping. Cross-reference all 467 named perpetrators against:
- California Megan's Law: `meganslaw.ca.gov`
- New York DCJS: `criminaljustice.ny.gov/SomsSufa`
- New Jersey: `njsp.org/sex-offender-registry`
- National: `nsopw.gov` (federated search)

**What you get:** Current addresses → house anchoring. Registry offense descriptions → additional incident details. Registry entries for people *already in your DB* who have incidents you haven't found.

**Implementation:** Python script, one request per person, rate-limited. Output: `data/sex_offender_matches.json`. Link confirmed matches back to house_roles via address→city→houses.

---

#### 2. PACER / CourtListener Systematic Query
**Champion: Torrence**

The RECAP Archive at `courtlistener.com` indexes federal court documents full-text, free. Query:

```
organization:"Chabad" criminal
"Lubavitch" indicted OR convicted OR sentenced
"rabbi" fraud OR abuse site:courtlistener.com
```

Sentencing memoranda and plea agreements name co-conspirators not named in press coverage. Each docket entry is structured: case number, judge, district, charges, defendants.

**Also run civil side:** qui tam whistleblower filings, civil RICO, SEC enforcement actions. Financial fraud in religious institutions frequently settles civilly and never appears in criminal databases.

**Implementation:** CourtListener has a REST API with free tier. Pull criminal cases, extract defendant names and case metadata, cross-reference against `people` table.

---

#### 3. Family Cold-Path Graph Walk
**Champion: Morrow**

Currently 28 relatives of known perpetrators are not linked to any incident. These are the highest-probability unexamined leads — you already have the relationship data.

```sql
-- Cold-path relatives
SELECT DISTINCT
    p_cold.id, p_cold.full_name,
    p_perp.full_name AS related_perp,
    fr.relation,
    COUNT(ip.incident_id) AS perp_incident_count
FROM family_relations fr
JOIN people p_perp ON p_perp.id = fr.person_a
JOIN incident_people ip ON ip.person_id = fr.person_a
JOIN people p_cold ON p_cold.id = fr.person_b
WHERE fr.person_b NOT IN (SELECT person_id FROM incident_people)
  AND p_cold.canonical_id IS NULL
GROUP BY fr.person_b
ORDER BY perp_incident_count DESC;
```

Each returned name is a targeted search — not broad dragnet, but a specific person known to be close to a high-incident actor.

---

#### 4. Hot-House Full Coverage Sweep
**Champion: Morrow**

Houses with 4+ incidents have near-certain undocumented cases. For each, pull every person ever in house_roles and search each name.

Current hot-house roster:
| House | City | Incidents |
|---|---|---|
| Yeshivah Centre - Lubavitch | East St. Kilda, AU | 18 |
| The Aleph Institute | Surfside, USA | 13 |
| Lubavitch of Hungary | Budapest | 11 |
| Tzerei Agudat Chabad H.Q. | Kfar Chabad, IL | 11 |
| Chabad West Coast HQ | Los Angeles | 8 |

Directed search hit rate is estimated at 3–5x better than broad dragnet because you're not fishing blind.

---

### Tier 2 — High Connection Value (1 week of work)

#### 5. IRS Form 990 Mining
**Champion: Torrence / Kowalski**

Every Chabad house incorporated as a 501(c)(3) files a Form 990 annually. ProPublica Nonprofit Explorer has them all, searchable via API:

```
https://projects.propublica.org/nonprofits/api/v2/search.json?q=chabad
```

Each 990 contains:
- **Officers and directors by name** → house anchoring with tenure dates
- **Key employee compensation** → identifies who actually ran the house
- **Part IX expense schedule** → where financial fraud is visible across years
- **Related organizations** → surfaces affiliated entities not in your houses table

**What you get for free:** Every person named as an officer of a Chabad house from ~2001 onward, with year-by-year tenure. Perpetrators disappearing from 990 filings correlates with incident dates. Financial fraud cases where the embezzlement dollar amount matches 990 expense line changes.

---

#### 6. Australian Royal Commission Transcript Mining
**Champion: Hartmann**

Case Study 29 (Yeshivah Centre Melbourne) of the Royal Commission into Institutional Responses to Child Sexual Abuse is the single most structured public source on the Australian cluster. Available at:

`childabuseroyalcommission.gov.au/case-studies/case-study-29`

Contains:
- Sworn testimony naming accused, victims, and institutional leaders
- Timeline of who knew what and when
- Formal findings with confidence levels
- Cross-references to other cases

Your Australia count is 179 incidents — the largest geographic cluster. The Commission transcripts should anchor every Australian case with authoritative perpetrator identity, institutional affiliation, and timeline.

**Implementation:** Download transcript PDFs, extract named entities with Python/spaCy, cross-reference against people and houses tables. Commission findings are citable as authoritative sources.

---

#### 7. Co-Defendant Betweenness Centrality
**Champion: Morrow**

The 354 co-defendant edges form a graph. High-betweenness nodes are *connectors* — people who appear in otherwise unconnected clusters. These are cover-up architects, institutional protectors, or serial actors spanning multiple case networks.

```python
import sqlite3, networkx as nx

conn = sqlite3.connect('data/chabad.db')
edges = conn.execute("SELECT person_a, person_b FROM person_relations").fetchall()
G = nx.Graph()
G.add_edges_from(edges)

centrality = nx.betweenness_centrality(G)
top = sorted(centrality.items(), key=lambda x: -x[1])[:20]
# Cross-reference top nodes against people table
```

People with high betweenness who are not themselves high-incident perpetrators may be:
- Institutional leaders who appeared in multiple co-defendant relationships
- Lawyers or rabbis who mediated between cases
- Family members who enabled multiple perpetrators

---

#### 8. Institution-Hopper Detection
**Champion: Chen**

In clergy abuse networks, perpetrators frequently move between institutions after internal complaints. People with house_roles at 3+ different houses, especially across cities, warrant targeted investigation.

```sql
SELECT p.id, p.full_name,
    COUNT(DISTINCT hr.house_id) as house_count,
    GROUP_CONCAT(h.name || ' (' || h.city || ')', ' → ') as houses
FROM people p
JOIN house_roles hr ON hr.person_id = p.id
JOIN houses h ON h.id = hr.house_id
WHERE p.canonical_id IS NULL
GROUP BY p.id HAVING house_count >= 3
ORDER BY house_count DESC;
```

Cross-reference the mobile people list against incident_people. Gap between first house_role and first incident is the investigation window.

---

#### 9. Pre-Digital Archive Mining (1980–2000)
**Champion: Torrence**

Systematic query of newspaper archives for cases predating the web:
- **ProQuest Historical Newspapers** — LA Times, Chicago Tribune, Washington Post back to their founding
- **Newspapers.com** — broad US regional coverage
- **The Forward** — Jewish press, primary source for community-internal cases since 1897, partially digitized
- **Awareness Center archive** (`awarenessnetwork.org`) — expert-curated, cites sources your scraper missed

Query structure: `"rabbi" AND ("convicted" OR "sentenced" OR "arrested" OR "pleaded guilty") AND ("Chabad" OR "Lubavitch")` filtered by date range 1980–2000.

---

#### 10. Amount-USD Case Unification
**Champion: Kowalski**

The same dollar figure in two incidents with different source URLs is often the same event covered twice — or two incidents that should be linked as a conspiracy.

```sql
-- Find incidents sharing dollar amounts that aren't already co-defendant-linked
SELECT i1.id, i1.summary, i2.id, i2.summary, i1.amount_usd
FROM incidents i1 JOIN incidents i2 ON i1.amount_usd = i2.amount_usd
WHERE i1.id < i2.id
  AND i1.amount_usd > 50000
  AND NOT EXISTS (
    SELECT 1 FROM person_relations pr
    JOIN incident_people ip1 ON ip1.person_id = pr.person_a AND ip1.incident_id = i1.id
    JOIN incident_people ip2 ON ip2.person_id = pr.person_b AND ip2.incident_id = i2.id
  )
ORDER BY i1.amount_usd DESC;
```

Matching amounts → investigate whether they're the same case (merge) or a conspiracy (link via person_relations).

---

### Tier 3 — Longer Burn (Weeks to Months)

#### 11. State AG Real-Time Monitor
**Champion: Torrence**

State AGs publish press releases for every major case. Most have RSS feeds. A persistent monitor on NY, NJ, CA, IL, FL, MA AG press release feeds filtered for "rabbi" OR "Jewish" OR "Chabad" catches cases in real time.

**Implementation:** RSS monitor → LLM extraction → auto-insert to staging table → human review queue.

---

#### 12. Wayback Machine Bio Recovery
**Champion: Chen**

When a shliach is arrested, Chabad house websites often scrub the bio. archive.org retains snapshots. For each orphan incident with a known house, query:

```
https://web.archive.org/web/*/[house-domain]/staff
https://web.archive.org/web/*/[house-domain]/about
https://web.archive.org/web/*/[house-domain]/rabbi
```

Compare oldest snapshot against current page. People who disappeared from the page around the incident date are candidates for the orphan link.

**Also applies to:** People in house_roles whose `canonical_id IS NULL` but who have no incident — their bio page deletion history is a signal.

---

#### 13. ICIJ Offshore Leaks Cross-Reference
**Champion: Kowalski**

`offshoreleaks.icij.org` aggregates Panama Papers, Pandora Papers, FinCEN Files, and other leaks. Full-text searchable by name.

Cross-reference your financial fraud perpetrators, especially those with large `amount_usd` values or international jurisdiction. Religious institution fraud frequently uses offshore vehicles.

---

#### 14. Suppression Signal Tracking
**Champions: Chen + Hartmann**

Documented suppression is its own data type. Cases resolved through rabbinical courts, NDAs that became public, survivor accounts where legal proceedings didn't follow — these exist in a documented state even without a court record.

**Proposed schema addition:**
```sql
ALTER TABLE incidents ADD COLUMN suppression_signal TEXT;
-- values: 'nda_confirmed', 'beth_din_settled', 'community_pressure', 
--         'bio_deleted', 'victim_recanted_publicly', 'witness_intimidation'
```

Suppression signals raise severity weight in the UI and flag cases for deeper investigation.

---

#### 15. Survivor Network Outreach
**Champion: Hartmann**

Organizations with case data not in any public record:
- **Jewish Community Watch** (`jewishcommunitywatch.org`) — Wall of Shame, expert-curated
- **Magen** (Israel) — parallel database, Israeli cases systematically undercounted
- **Awareness Center** — oldest Jewish abuse archive, pre-2010 cases especially
- **SNAP Jewish chapter** — survivor reports filed before going public

These are relationship problems, not scraping problems. Academic or journalistic credential helps. Their data fills the institutional-suppression gap that no automated pipeline can reach.

---

## The 228 Orphan Triage Plan

Not all orphans are the same problem. Segment before attacking:

| Segment | Criteria | Method |
|---|---|---|
| **Has source URL** | `source URL present` | Fetch page → NER extraction → auto-link |
| **Has partial name in summary** | Name candidate extractable | Targeted web search + PACER lookup |
| **Has location + type, no name** | Location and crime type known | Hot-house sweep + AG press releases |
| **Vague summary only** | No actionable signals | Suppression signal flag; may be permanently un-nameable |

Estimated recovery: 30–60 additional orphans resolved with Tier 1 methods. ~160–180 may be permanently undocumented from public sources alone.

---

## Graph Queries to Build Now

Three network queries that can run against the existing DB immediately:

### 1. Family Bridge Query
People related to 2+ different named perpetrators who are not themselves in incident_people.

```sql
SELECT p_cold.id, p_cold.full_name,
    COUNT(DISTINCT fr.person_a) AS connected_perps,
    GROUP_CONCAT(DISTINCT p_perp.full_name) AS related_to
FROM family_relations fr
JOIN people p_perp ON p_perp.id = fr.person_a
JOIN incident_people ip ON ip.person_id = fr.person_a
JOIN people p_cold ON p_cold.id = fr.person_b
WHERE fr.person_b NOT IN (SELECT person_id FROM incident_people)
  AND p_cold.canonical_id IS NULL
GROUP BY fr.person_b
HAVING connected_perps >= 2
ORDER BY connected_perps DESC;
```

### 2. Long-Tenure Anomaly
Perpetrators whose incident years span more than 10 years likely have undocumented incidents in between.

```sql
SELECT p.id, p.full_name,
    MIN(CAST(substr(i.occurred_on,1,4) AS INT)) AS first_year,
    MAX(CAST(substr(i.occurred_on,1,4) AS INT)) AS last_year,
    MAX(CAST(substr(i.occurred_on,1,4) AS INT)) - MIN(CAST(substr(i.occurred_on,1,4) AS INT)) AS span_years,
    COUNT(ip.incident_id) AS incident_count
FROM people p
JOIN incident_people ip ON ip.person_id = p.id
JOIN incidents i ON i.id = ip.incident_id
WHERE p.canonical_id IS NULL AND i.occurred_on IS NOT NULL
GROUP BY p.id
HAVING span_years >= 10
ORDER BY span_years DESC;
```

### 3. Institution-Hopper Flag
People with house_roles at 3+ houses, especially across cities.

```sql
SELECT p.id, p.full_name,
    COUNT(DISTINCT hr.house_id) AS house_count,
    COUNT(DISTINCT ip.incident_id) AS known_incidents,
    GROUP_CONCAT(DISTINCT h.city || ', ' || h.country) AS locations
FROM people p
JOIN house_roles hr ON hr.person_id = p.id
JOIN houses h ON h.id = hr.house_id
LEFT JOIN incident_people ip ON ip.person_id = p.id
WHERE p.canonical_id IS NULL
GROUP BY p.id HAVING house_count >= 3
ORDER BY house_count DESC, known_incidents DESC;
```

---

## Key External Sources Summary

| Source | URL | What It Has | Priority |
|---|---|---|---|
| CourtListener / RECAP | `courtlistener.com` | Federal criminal + civil dockets, full text | **High** |
| ProPublica Nonprofit Explorer | `projects.propublica.org/nonprofits` | 990 forms, officer names, financials | **High** |
| National Sex Offender Registry | `nsopw.gov` | Current addresses, offense descriptions | **High** |
| Royal Commission Case Study 29 | `childabuseroyalcommission.gov.au` | AU sworn testimony, structured findings | **High** |
| Jewish Community Watch | `jewishcommunitywatch.org` | Expert-curated Wall of Shame | **Medium** |
| Awareness Center | `awarenessnetwork.org` | Pre-2010 cases, Jewish media sourced | **Medium** |
| ICIJ Offshore Leaks | `offshoreleaks.icij.org` | Panama/Pandora Papers name cross-ref | **Medium** |
| The Forward Archive | `forward.com/search` | Jewish press back to 1897 | **Medium** |
| Wayback Machine | `web.archive.org` | Deleted staff bios, scrubbed pages | **Medium** |
| FinCEN Enforcement | `fincen.gov/news-room/enforcement-actions` | Money services enforcement by name | **Low** |
| State AG press releases | NY/NJ/CA/IL/FL/MA `.gov` feeds | Real-time case monitoring | **Low** |

---

## Immediate Action Checklist

- [ ] Run sex offender registry cross-reference against all 467 named perpetrators
- [ ] Query CourtListener for "Chabad" + "Lubavitch" in criminal dockets
- [ ] Pull family cold-path list (28 relatives) and run targeted searches on each
- [ ] For top 5 hot-house houses: pull all house_roles people, run targeted search on each
- [ ] Download Royal Commission Case Study 29 transcripts and extract structured data
- [ ] Query ProPublica Nonprofit Explorer for 990 data on top 25 houses
- [ ] Run amount_usd deduplication query to find case-unification candidates
- [ ] Run institution-hopper query and investigate top 10 results
- [ ] Add `suppression_signal` field to incidents schema

---

*Roundtable conducted June 2026. DB state: 971 incidents, 467 perpetrators, 3,050 family edges, 354 co-defendant edges.*
