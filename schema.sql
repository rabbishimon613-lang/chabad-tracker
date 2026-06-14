-- Chabad Tracker — internal DB schema
-- Layer 1: base directory (houses + people + roles)
-- Layer 2: family graph
-- Layer 3: misdeeds / incidents (designed-in seam, populated later)

PRAGMA foreign_keys = ON;

-- ============================================================
-- Sources (cited by everything)
-- ============================================================
CREATE TABLE sources (
  id           INTEGER PRIMARY KEY,
  url          TEXT NOT NULL,
  type         TEXT,                -- 'directory' | 'news' | 'court' | 'social' | 'other'
  title        TEXT,
  accessed_at  TEXT NOT NULL,       -- ISO8601
  notes        TEXT
);
CREATE INDEX idx_sources_url ON sources(url);

-- ============================================================
-- Houses / institutions
-- ============================================================
CREATE TABLE houses (
  id           INTEGER PRIMARY KEY,
  mosad_aid    INTEGER UNIQUE,      -- chabad.org's stable house id
  name         TEXT NOT NULL,
  slug         TEXT UNIQUE,
  country      TEXT,
  region       TEXT,                -- 'New England', 'Northeast', etc. (analytic, not from source)
  state        TEXT,
  city         TEXT,
  address      TEXT,
  lat          REAL,
  lng          REAL,
  website      TEXT,
  phone        TEXT,
  email        TEXT,
  parent_org   TEXT,                -- e.g. 'Chabad-Lubavitch'
  status       TEXT DEFAULT 'active', -- active | closed | unknown
  source_url   TEXT,                -- the chabad.org page we scraped
  scraped_at   TEXT,
  notes        TEXT
);
CREATE INDEX idx_houses_state ON houses(state);
CREATE INDEX idx_houses_country ON houses(country);

-- ============================================================
-- People (one row per distinct person, ideally — but scrape
-- creates one row per occurrence; matching collapses later)
-- ============================================================
CREATE TABLE people (
  id            INTEGER PRIMARY KEY,
  shliach_aid   INTEGER UNIQUE,     -- chabad.org's stable person id (null for non-API people)
  full_name     TEXT NOT NULL,
  given_name    TEXT,
  surname       TEXT,
  hebrew_name   TEXT,
  gender        TEXT,               -- m | f | unknown
  dob_year      INTEGER,
  status        TEXT DEFAULT 'active',
  notes         TEXT,
  -- Provenance: where did we first see this person?
  first_seen_house_id INTEGER REFERENCES houses(id),
  first_seen_at TEXT
);
CREATE INDEX idx_people_surname ON people(surname);
CREATE INDEX idx_people_full_name ON people(full_name);

-- ============================================================
-- House roles (M:N person<->house with role & dates)
-- A person legitimately may hold roles at multiple houses.
-- ============================================================
CREATE TABLE house_roles (
  id          INTEGER PRIMARY KEY,
  house_id    INTEGER NOT NULL REFERENCES houses(id),
  person_id   INTEGER NOT NULL REFERENCES people(id),
  role        TEXT NOT NULL,        -- 'shliach' | 'shlucha' | 'rabbi' | 'co-director' | 'director' | 'child' | etc.
  start_year  INTEGER,
  end_year    INTEGER,
  is_primary  INTEGER DEFAULT 0,    -- bool: are they the main face of the house (is-director from API)
  is_deceased INTEGER DEFAULT 0,
  notes       TEXT,
  UNIQUE(house_id, person_id, role)
);
CREATE INDEX idx_roles_house ON house_roles(house_id);
CREATE INDEX idx_roles_person ON house_roles(person_id);

-- ============================================================
-- Person matching — proposed merges, NEVER auto-applied
-- ============================================================
CREATE TABLE person_match_candidates (
  id          INTEGER PRIMARY KEY,
  person_a    INTEGER NOT NULL REFERENCES people(id),
  person_b    INTEGER NOT NULL REFERENCES people(id),
  score       REAL,                 -- 0..1
  signals     TEXT,                 -- JSON: {"same_email":true,"same_surname":true,...}
  status      TEXT DEFAULT 'pending', -- pending | confirmed | rejected
  reviewed_at TEXT,
  reviewer    TEXT,
  CHECK (person_a < person_b)
);
CREATE INDEX idx_match_status ON person_match_candidates(status);

-- ============================================================
-- Families — gejj vs baal teshuva distinction lives here
-- ============================================================
CREATE TABLE families (
  id            INTEGER PRIMARY KEY,
  surname       TEXT NOT NULL,
  display_name  TEXT,               -- 'Krinsky family', 'Shemtov dynasty', etc.
  lineage_type  TEXT,               -- 'gejj' | 'baal_teshuva' | 'mixed' | 'unknown'
  origin_notes  TEXT,               -- founding shliach, region of origin
  notes         TEXT
);
CREATE INDEX idx_families_surname ON families(surname);

CREATE TABLE family_members (
  id           INTEGER PRIMARY KEY,
  family_id    INTEGER NOT NULL REFERENCES families(id),
  person_id    INTEGER NOT NULL REFERENCES people(id),
  relation     TEXT,                -- 'head' | 'spouse' | 'child' | 'sibling' | 'in_law' | 'descendant'
  by_marriage  INTEGER DEFAULT 0,
  notes        TEXT,
  UNIQUE(family_id, person_id)
);

-- Person<->person graph (for the cross-family marriage network
-- that makes shluchim dynasties visible)
CREATE TABLE family_relations (
  id          INTEGER PRIMARY KEY,
  person_a    INTEGER NOT NULL REFERENCES people(id),
  person_b    INTEGER NOT NULL REFERENCES people(id),
  relation    TEXT NOT NULL,        -- 'parent_of' | 'spouse_of' | 'sibling_of' | 'in_law_of'
  notes       TEXT,
  UNIQUE(person_a, person_b, relation)
);
CREATE INDEX idx_relations_a ON family_relations(person_a);
CREATE INDEX idx_relations_b ON family_relations(person_b);

-- ============================================================
-- Territories — emergent; populated after looking at data
-- ============================================================
CREATE TABLE territories (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL,   -- 'Greater Boston', 'Connecticut shoreline'
  country             TEXT,
  dominant_family_id  INTEGER REFERENCES families(id),
  notes               TEXT
);

CREATE TABLE house_territories (
  house_id     INTEGER NOT NULL REFERENCES houses(id),
  territory_id INTEGER NOT NULL REFERENCES territories(id),
  PRIMARY KEY (house_id, territory_id)
);

-- ============================================================
-- Misdeeds layer (Layer 3) — seam designed in now, populated later
-- ============================================================
CREATE TABLE incidents (
  id           INTEGER PRIMARY KEY,
  occurred_on  TEXT,                -- ISO date (may be partial: YYYY or YYYY-MM)
  reported_on  TEXT,
  type         TEXT,                -- 'sexual_abuse' | 'financial_fraud' | 'trafficking' | 'cover_up' | etc.
  severity     TEXT,                -- 'allegation' | 'investigation' | 'charged' | 'convicted' | 'settled' | 'acquitted'
  jurisdiction TEXT,
  location     TEXT,
  summary      TEXT,
  notes        TEXT,
  -- Phase 1: Verifier audit state.
  -- unaudited / passed / passed_partial / quarantined / no_source
  audit_status      TEXT DEFAULT 'unaudited',
  audit_score       INTEGER,        -- 0-100 confidence (Layer 11)
  audit_at          TEXT,
  quarantine_reason TEXT
);
CREATE INDEX idx_incidents_type ON incidents(type);
CREATE INDEX idx_incidents_severity ON incidents(severity);
CREATE INDEX idx_incidents_audit_status ON incidents(audit_status);

CREATE TABLE incident_people (
  id          INTEGER PRIMARY KEY,
  incident_id INTEGER NOT NULL REFERENCES incidents(id),
  person_id   INTEGER NOT NULL REFERENCES people(id),
  role        TEXT NOT NULL,        -- 'perpetrator' | 'enabler' | 'victim' | 'witness' | 'covered_up_by'
  notes       TEXT
);
CREATE INDEX idx_ip_incident ON incident_people(incident_id);
CREATE INDEX idx_ip_person ON incident_people(person_id);

CREATE TABLE incident_houses (
  id          INTEGER PRIMARY KEY,
  incident_id INTEGER NOT NULL REFERENCES incidents(id),
  house_id    INTEGER NOT NULL REFERENCES houses(id),
  relation    TEXT NOT NULL,        -- 'occurred_at' | 'affiliated' | 'covered_up'
  notes       TEXT
);

CREATE TABLE incident_sources (
  incident_id    INTEGER NOT NULL REFERENCES incidents(id),
  source_id      INTEGER NOT NULL REFERENCES sources(id),
  -- Phase 1: per-source artifacts used by the Verifier.
  verbatim_quote TEXT,           -- 10-30 word quote the Researcher extracted
  wayback_url    TEXT,           -- snapshot URL after Layer 10 fire-and-forget
  wayback_at     TEXT,
  PRIMARY KEY (incident_id, source_id)
);

-- Phase 1: quarantine — full per-failure record (preserved forever).
CREATE TABLE quarantine (
  id           INTEGER PRIMARY KEY,
  incident_id  INTEGER NOT NULL REFERENCES incidents(id),
  layer        INTEGER NOT NULL,   -- 1..12 — which layer rejected
  layer_name   TEXT NOT NULL,      -- e.g. 'url_liveness'
  reason       TEXT NOT NULL,      -- plain English, public-facing
  details      TEXT,               -- JSON: layer-specific failure metadata
  redact_name  INTEGER NOT NULL DEFAULT 0, -- 1 → public quarantine redacts name
  failed_at    TEXT NOT NULL
);
CREATE INDEX idx_quarantine_incident ON quarantine(incident_id);
CREATE INDEX idx_quarantine_layer    ON quarantine(layer);

-- Phase 2 forward-decl: meta_publish lets the UI self-check post-load.
CREATE TABLE meta_publish (
  id              INTEGER PRIMARY KEY,
  sha256          TEXT NOT NULL,
  snapshot_count  INTEGER NOT NULL,
  published_at    TEXT NOT NULL,
  cycle_id        TEXT
);
