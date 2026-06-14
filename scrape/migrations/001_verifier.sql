-- Phase 1 migration: Verifier audit columns + quarantine table.
-- Idempotent — uses "IF NOT EXISTS" patterns where SQLite allows; otherwise
-- guarded by Python wrapper. Run via:
--   sqlite3 data/chabad.db < scrape/migrations/001_verifier.sql

-- ---------------------------------------------------------------------------
-- incidents.audit_status — tri+ state
--   'unaudited'      → never run through Verifier (default for legacy rows)
--   'passed'         → all applicable layers passed at full strength
--   'passed_partial' → passed all layers that COULD run; some skipped (e.g.
--                      legacy row with no verbatim_quote can't run Layer 3)
--   'quarantined'    → at least one hard layer failed
--   'no_source'      → incident has no source URL; nothing to verify against
-- ---------------------------------------------------------------------------
ALTER TABLE incidents ADD COLUMN audit_status      TEXT DEFAULT 'unaudited';
ALTER TABLE incidents ADD COLUMN audit_score       INTEGER;            -- 0-100 (Layer 11)
ALTER TABLE incidents ADD COLUMN audit_at          TEXT;               -- ISO8601
ALTER TABLE incidents ADD COLUMN quarantine_reason TEXT;               -- short plain-English summary

CREATE INDEX IF NOT EXISTS idx_incidents_audit_status ON incidents(audit_status);

-- incident_sources gains the quote + Wayback snapshot URL.
-- verbatim_quote: a 10-30 word quote the Researcher extracted from the source.
-- wayback_url: the snapshot URL stored after Layer 10's fire-and-forget POST.
ALTER TABLE incident_sources ADD COLUMN verbatim_quote TEXT;
ALTER TABLE incident_sources ADD COLUMN wayback_url    TEXT;
ALTER TABLE incident_sources ADD COLUMN wayback_at     TEXT;

-- ---------------------------------------------------------------------------
-- quarantine — the full per-failure record. Mirrors any incident that ever
-- fails verification. Preserved forever ([[feedback_never_delete_originals]]).
-- One incident can have multiple rows here (one per failed audit run).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quarantine (
  id           INTEGER PRIMARY KEY,
  incident_id  INTEGER NOT NULL REFERENCES incidents(id),
  layer        INTEGER NOT NULL,       -- 1..12 — which layer rejected
  layer_name   TEXT NOT NULL,          -- e.g. 'url_liveness'
  reason       TEXT NOT NULL,          -- plain English, public-facing
  details      TEXT,                   -- JSON: layer-specific failure metadata
  redact_name  INTEGER NOT NULL DEFAULT 0, -- 1 if Layer 2 fail → redact name in public quarantine
  failed_at    TEXT NOT NULL           -- ISO8601
);
CREATE INDEX IF NOT EXISTS idx_quarantine_incident ON quarantine(incident_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_layer    ON quarantine(layer);

-- meta_publish — tracks every atomic publish (Phase 2). Created here so the
-- atomic-publish rewrite can land cleanly.
CREATE TABLE IF NOT EXISTS meta_publish (
  id              INTEGER PRIMARY KEY,
  sha256          TEXT NOT NULL,
  snapshot_count  INTEGER NOT NULL,    -- incident count at publish time
  published_at    TEXT NOT NULL,
  cycle_id        TEXT                 -- GH Actions run_id, when cloud cycle does it
);
