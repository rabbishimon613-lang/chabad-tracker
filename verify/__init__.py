"""Chabad Tracker Verifier.

12-layer verification stack per notes/buildroad.md §"Phase 1".
Strict from day one; lower yield is acceptable, unverified-feeling DB is not.

Public entry:
    from verify.runner import verify_incident
    result = verify_incident(conn, incident_id)
    # result.passed, result.score, result.layers, result.quarantine_rows

Layers are added in phases (buildroad order):
    Week 1 (spine):    1 url_liveness, 2 name_on_page, 3 verbatim_quote, 10 wayback
    Week 2 (gates):    5 role_check, 6 severity_ladder, 7 source_class, 12 doctrine
    Week 3 (calib):    4 triangulation, 8 cross_source, 9 second_pass_llm, 11 confidence
"""

__all__ = ["verify_incident", "VerifyResult", "LayerResult"]
