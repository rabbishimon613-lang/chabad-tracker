# Chabad Tracker — Cleanup Plan
Generated: 2026-06-10 | DB at 745 incidents

---

## PRIORITY 1 — Redeploy (2 min)
UI shows 357 incidents; DB has 745. snapshot.json is stale (generated Jun 8).

```bash
cd /Volumes/EOS_DIGITAL/chabad-tracker
python3 scrape/load_snippet_extracts.py
cp data/chabad.db ui/public/chabad.db
cd ui && ~/.bun/bin/vercel --prod --archive=tgz
```

---

## PRIORITY 2 — Delete Doctrine Violations (10 min)
These are non-Chabad perpetrators that leaked into the DB.

```sql
-- Lakewood (Litvish/yeshivish, NOT Chabad):
DELETE FROM incidents WHERE id IN (1005, 1095);

-- Mendel Epstein "get" coercion ring (NOT Chabad):
DELETE FROM incidents WHERE id IN (854, 1132);

-- Also clean orphaned incident_people links:
DELETE FROM incident_people WHERE incident_id NOT IN (SELECT id FROM incidents);
```

After deleting, verify with:
```bash
sqlite3 data/chabad.db "SELECT id, summary FROM incidents WHERE id IN (1005,1095,854,1132);"
# Should return empty
sqlite3 data/chabad.db "SELECT COUNT(*) FROM incidents;"
```

### Also review these borderline Agriprocessors records:
These are corporate regulatory/environmental actions — may not be "Chabad crimes":
```sql
SELECT id, summary FROM incidents WHERE id IN (146, 147, 155);
```
Decide: keep or delete based on whether they involve individual Chabad perpetrators.

---

## PRIORITY 3 — Fix Bad Date Values (5 min)
Five records have `occurred_on='unknown'` (not ISO) which breaks sorting.

```sql
-- See them:
SELECT id, occurred_on, summary FROM incidents WHERE occurred_on = 'unknown';
-- IDs: 62, 116, 117, 118, 119

-- Fix: set to NULL (unknown date) rather than invalid string:
UPDATE incidents SET occurred_on = NULL WHERE occurred_on = 'unknown';
```

Also check the 1820 outlier:
```sql
SELECT id, occurred_on, summary FROM incidents WHERE occurred_on < '1900-01-01';
```
If it's a typo/hallucination, either fix the date or delete.

---

## PRIORITY 4 — Normalize type/severity Enums (30 min)
No CHECK constraints exist; 16+ non-canonical type values are in the DB.

### Current canonical sets (from docs + loader):
**type:** financial_fraud, tax_evasion, money_laundering, sexual_abuse, assault, cover_up, drug_trafficking, immigration_fraud, insurance_fraud, welfare_fraud, other

**severity:** allegation, investigation, charged, indicted, convicted, settled

### Non-canonical values found in DB and their mappings:
```sql
-- See all type values in use:
SELECT type, COUNT(*) FROM incidents GROUP BY type ORDER BY COUNT(*) DESC;

-- Remap:
UPDATE incidents SET type = 'sexual_abuse'     WHERE type IN ('csa', 'sexual_assault');
UPDATE incidents SET type = 'cover_up'          WHERE type = 'obstruction';
UPDATE incidents SET type = 'financial_fraud'   WHERE type = 'embezzlement';
UPDATE incidents SET type = 'drug_trafficking'  WHERE type = 'trafficking_drugs';
UPDATE incidents SET type = 'other'             WHERE type IN ('shlichus_dispute', 'settler_violence', 'murder');

-- severity:
-- 'dismissed' and 'acquitted' are meaningful — add them to canonical set, OR:
-- UPDATE incidents SET severity = 'acquitted' WHERE severity = 'dismissed';  -- if you want to collapse

-- After remapping, add CHECK constraints:
-- (SQLite doesn't support ADD CONSTRAINT; need to recreate table or use triggers)
-- Simplest: add to schema.sql for documentation, enforce in load_snippet_extracts.py
```

---

## PRIORITY 5 — Fix find_or_create_person Over-matching (15 min)
File: `scrape/load_snippet_extracts.py`

### Problem:
```python
# Current (BROKEN for short/anonymous names):
cur.execute("SELECT id FROM people WHERE full_name LIKE ?", (f"%{clean}%",))
```
For `clean = "A."` this matches everyone.

### Fix:
```python
# Option A — exact match only:
cur.execute("SELECT id FROM people WHERE LOWER(full_name) = LOWER(?)", (name,))

# Option B — exact match first, LIKE fallback only for names >6 chars:
cur.execute("SELECT id FROM people WHERE LOWER(full_name) = LOWER(?)", (name,))
row = cur.fetchone()
if not row and len(clean) > 6:
    cur.execute("SELECT id FROM people WHERE full_name LIKE ?", (f"%{clean}%",))
```

### Clean up existing duplicates:
```sql
-- See worst offenders:
SELECT full_name, COUNT(*) as n FROM people 
GROUP BY LOWER(full_name) HAVING n > 1 ORDER BY n DESC LIMIT 20;

-- Merge duplicates: keep lowest id, remap incident_people, delete dupes
-- (write a small Python script for this)
```

---

## REFERENCE — Enum Quick-Check Queries

```sql
-- All type values:
SELECT type, COUNT(*) FROM incidents GROUP BY type ORDER BY COUNT(*) DESC;

-- All severity values:
SELECT severity, COUNT(*) FROM incidents GROUP BY severity ORDER BY COUNT(*) DESC;

-- Incidents with no 'Chabad' or 'Lubavitch' in summary:
SELECT COUNT(*) FROM incidents 
WHERE summary NOT LIKE '%Chabad%' AND summary NOT LIKE '%Lubavitch%' 
AND notes NOT LIKE '%Chabad%' AND notes NOT LIKE '%Lubavitch%';

-- Doctrine check sample:
SELECT id, summary FROM incidents 
WHERE summary NOT LIKE '%Chabad%' AND summary NOT LIKE '%Lubavitch%'
LIMIT 30;
```

---

## Deploy Pipeline (run after any DB changes)
```bash
cd /Volumes/EOS_DIGITAL/chabad-tracker
python3 scrape/load_snippet_extracts.py
cp data/chabad.db ui/public/chabad.db
cd ui && ~/.bun/bin/vercel --prod --archive=tgz
```
