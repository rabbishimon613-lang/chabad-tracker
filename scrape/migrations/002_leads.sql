-- Phase 4 migration: leads table + lead_results + edge_reason on relations.
-- Idempotent where SQLite allows; otherwise guarded by the migration wrapper.

-- ---------------------------------------------------------------------------
-- leads — the work queue. DB is the queue (no Redis, no DLQs).
--
-- Self-healing mechanism (buildroad §"Lead reclaim"):
--   claimed_at > now() - 15min → automatically reclaimable. A crashed cycle's
--   work is silently resumed on the next tick.
--
-- payload_json is the kind-specific shape. Examples:
--   cold_path_relative:  {"person_id": 123, "via_edge_id": 456, "depth": 2}
--   hot_house_roster:    {"house_id": 789}
--   institution_hopper:  {"person_id": 123, "houses": [789, 456]}
--   amount_collision:    {"amount_usd": 1450000, "candidate_ids": [101,102]}
--   family_bridge:       {"family_id": 333, "between_houses": [11, 22]}
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
  id              INTEGER PRIMARY KEY,
  kind            TEXT NOT NULL,
  payload_json    TEXT NOT NULL,            -- JSON, kind-specific
  score           REAL NOT NULL DEFAULT 0,  -- higher = research first
  status          TEXT NOT NULL DEFAULT 'pending',  -- pending|claimed|resolved|dead
  claimed_at      TEXT,                     -- ISO8601 when a researcher picked it up
  parent_lead_id  INTEGER REFERENCES leads(id),  -- for child leads spawned by Archivist
  created_at      TEXT NOT NULL,
  resolved_at     TEXT,
  notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_status      ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_score       ON leads(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_kind        ON leads(kind);
CREATE INDEX IF NOT EXISTS idx_leads_claimed_at  ON leads(claimed_at);

-- lead_results — what the Researcher found per lead. One row per (lead, result).
-- A lead can spawn many results (multiple incidents from one rabbit hole).
CREATE TABLE IF NOT EXISTS lead_results (
  id           INTEGER PRIMARY KEY,
  lead_id      INTEGER NOT NULL REFERENCES leads(id),
  outcome      TEXT NOT NULL,               -- 'incident'|'person'|'dead_end'|'duplicate'
  incident_id  INTEGER REFERENCES incidents(id),
  person_id    INTEGER REFERENCES people(id),
  details      TEXT,                        -- JSON
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lead_results_lead ON lead_results(lead_id);

-- ---------------------------------------------------------------------------
-- edge_reason on family_relations + person_relations.
-- Buildroad rule: every edge must justify itself in one sentence.
-- We add the column nullable for now; the Archivist enforces NOT NULL on
-- new writes and Phase 3 backfills existing rows.
-- ---------------------------------------------------------------------------
ALTER TABLE family_relations ADD COLUMN edge_reason TEXT;

-- person_relations exists (columns: person_a, person_b, rel_type, rel_detail,
-- source_id). Add edge_reason — nullable for now; new writes set it.
ALTER TABLE person_relations ADD COLUMN edge_reason TEXT;

-- staging — the Researcher writes here; the Archivist promotes to live tables.
-- Never read by the public UI.
CREATE TABLE IF NOT EXISTS staging_incidents (
  id               INTEGER PRIMARY KEY,
  lead_id          INTEGER NOT NULL REFERENCES leads(id),
  payload_json     TEXT NOT NULL,           -- the LLM's structured extraction
  verified         INTEGER NOT NULL DEFAULT 0,
  verify_result    TEXT,                    -- JSON: VerifyResult.layer_results
  promoted         INTEGER NOT NULL DEFAULT 0,
  promoted_incident_id INTEGER REFERENCES incidents(id),
  created_at       TEXT NOT NULL,
  notes            TEXT
);
CREATE INDEX IF NOT EXISTS idx_staging_verified ON staging_incidents(verified, promoted);
