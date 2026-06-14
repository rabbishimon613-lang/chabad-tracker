-- Layer 3c — analytic views
-- These are the API the future map UI will hit. Don't query base tables directly
-- from the frontend; query these.

DROP VIEW IF EXISTS v_house_summary;
DROP VIEW IF EXISTS v_person_dossier;
DROP VIEW IF EXISTS v_family_network;
DROP VIEW IF EXISTS v_incident_full;

-- ============================================================
-- v_house_summary
-- One row per house. Everything the map needs for a dot + popup.
-- ============================================================
CREATE VIEW v_house_summary AS
SELECT
  h.id              AS house_id,
  h.mosad_aid,
  h.name,
  h.country,
  h.state,
  h.city,
  h.address,
  h.lat,
  h.lng,
  h.website,
  h.phone,
  h.email,
  h.status,
  h.severity_score,
  h.incident_count,
  h.color_band,
  -- personnel count
  (SELECT COUNT(*) FROM house_roles WHERE house_id = h.id) AS personnel_count,
  -- distinct families present at this house (via surname match)
  (SELECT COUNT(DISTINCT fm.family_id)
     FROM house_roles hr
     JOIN family_members fm ON fm.person_id = hr.person_id
    WHERE hr.house_id = h.id) AS families_present,
  -- top severity recorded
  (SELECT MAX(CASE i.severity
        WHEN 'convicted'    THEN 6
        WHEN 'indicted'     THEN 5
        WHEN 'charged'      THEN 4
        WHEN 'settled'      THEN 3
        WHEN 'investigation' THEN 2
        WHEN 'allegation'   THEN 1
        ELSE 0 END)
     FROM incidents i
     JOIN incident_people ip ON ip.incident_id = i.id
     JOIN house_roles hr ON hr.person_id = ip.person_id
    WHERE hr.house_id = h.id) AS worst_severity_rank
FROM houses h;


-- ============================================================
-- v_person_dossier
-- One row per person. For map popups + person detail pages.
-- ============================================================
CREATE VIEW v_person_dossier AS
SELECT
  p.id            AS person_id,
  p.shliach_aid,
  p.full_name,
  p.given_name,
  p.surname,
  p.gender,
  p.status,
  -- in-directory flag (shliach_aid != null means came from chabad.org API)
  CASE WHEN p.shliach_aid IS NOT NULL THEN 1 ELSE 0 END AS in_directory,
  -- house count + names
  (SELECT COUNT(*) FROM house_roles WHERE person_id = p.id) AS house_count,
  (SELECT GROUP_CONCAT(h.name, ' | ')
     FROM house_roles hr JOIN houses h ON h.id = hr.house_id
    WHERE hr.person_id = p.id) AS houses,
  -- primary role
  (SELECT role FROM house_roles WHERE person_id = p.id AND is_primary = 1 LIMIT 1) AS primary_role,
  -- incident count + worst severity
  (SELECT COUNT(*) FROM incident_people WHERE person_id = p.id) AS incident_count,
  (SELECT MAX(CASE i.severity
        WHEN 'convicted'    THEN 6
        WHEN 'indicted'     THEN 5
        WHEN 'charged'      THEN 4
        WHEN 'settled'      THEN 3
        WHEN 'investigation' THEN 2
        WHEN 'allegation'   THEN 1
        ELSE 0 END)
     FROM incidents i JOIN incident_people ip ON ip.incident_id=i.id
    WHERE ip.person_id = p.id) AS worst_severity_rank,
  -- family
  (SELECT f.surname FROM family_members fm JOIN families f ON f.id = fm.family_id
    WHERE fm.person_id = p.id LIMIT 1) AS family_surname,
  -- spouse (if any inferred)
  (SELECT p2.full_name
     FROM family_relations fr
     JOIN people p2 ON p2.id = CASE WHEN fr.person_a = p.id THEN fr.person_b ELSE fr.person_a END
    WHERE (fr.person_a = p.id OR fr.person_b = p.id) AND fr.relation = 'spouse_of'
    LIMIT 1) AS spouse_name
FROM people p;


-- ============================================================
-- v_family_network
-- One row per family. Aggregated metrics for graph overlay.
-- ============================================================
CREATE VIEW v_family_network AS
SELECT
  f.id              AS family_id,
  f.surname,
  f.display_name,
  f.lineage_type,
  (SELECT COUNT(*) FROM family_members WHERE family_id = f.id) AS member_count,
  -- houses touched by this family
  (SELECT COUNT(DISTINCT hr.house_id)
     FROM family_members fm
     JOIN house_roles hr ON hr.person_id = fm.person_id
    WHERE fm.family_id = f.id) AS house_count,
  -- countries touched
  (SELECT COUNT(DISTINCT h.country)
     FROM family_members fm
     JOIN house_roles hr ON hr.person_id = fm.person_id
     JOIN houses h ON h.id = hr.house_id
    WHERE fm.family_id = f.id) AS country_count,
  -- aggregated severity across all members
  (SELECT COALESCE(SUM(CASE i.severity
        WHEN 'allegation'    THEN 1
        WHEN 'investigation' THEN 2
        WHEN 'settled'       THEN 4
        WHEN 'charged'       THEN 5
        WHEN 'indicted'      THEN 6
        WHEN 'convicted'     THEN 10
        ELSE 0 END), 0)
     FROM family_members fm
     JOIN incident_people ip ON ip.person_id = fm.person_id
     JOIN incidents i ON i.id = ip.incident_id
    WHERE fm.family_id = f.id) AS severity_score,
  -- incidents tied to this family
  (SELECT COUNT(DISTINCT ip.incident_id)
     FROM family_members fm
     JOIN incident_people ip ON ip.person_id = fm.person_id
    WHERE fm.family_id = f.id) AS incident_count
FROM families f;


-- ============================================================
-- v_incident_full
-- One row per incident with denormalised perp/house info for quick rendering.
-- ============================================================
CREATE VIEW v_incident_full AS
SELECT
  i.id              AS incident_id,
  i.occurred_on,
  i.type,
  i.severity,
  i.location,
  i.summary,
  i.review_status,
  -- perpetrators
  (SELECT GROUP_CONCAT(p.full_name, ' | ')
     FROM incident_people ip JOIN people p ON p.id = ip.person_id
    WHERE ip.incident_id = i.id AND ip.role = 'perpetrator') AS perpetrators,
  (SELECT COUNT(*) FROM incident_people WHERE incident_id = i.id AND role='perpetrator') AS perp_count,
  -- houses
  (SELECT GROUP_CONCAT(h.name, ' | ')
     FROM incident_houses ih JOIN houses h ON h.id = ih.house_id
    WHERE ih.incident_id = i.id) AS direct_houses,
  -- sources
  (SELECT COUNT(*) FROM incident_sources WHERE incident_id = i.id) AS source_count,
  -- first source URL (for click-through)
  (SELECT s.url FROM incident_sources isc JOIN sources s ON s.id = isc.source_id
    WHERE isc.incident_id = i.id LIMIT 1) AS first_source_url
FROM incidents i;
