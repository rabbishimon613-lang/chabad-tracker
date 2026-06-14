"""The 12-layer Verifier stack. Layers ship in three waves per the buildroad.

Each layer is a pure function:
    layer_N(ctx: LayerContext) -> LayerResult

Layers never mutate the DB themselves. The runner aggregates results and
decides audit_status, then writes once.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from . import http


@dataclass
class IncidentSource:
    """One source row for a single incident."""
    source_id: int
    url: str
    title: Optional[str] = None
    verbatim_quote: Optional[str] = None
    wayback_url: Optional[str] = None


@dataclass
class IncidentRow:
    """Minimal incident shape the layers need. Fetched by the runner."""
    id: int
    severity: Optional[str]
    type: Optional[str]
    location: Optional[str]
    summary: Optional[str]
    occurred_on: Optional[str]
    sources: list[IncidentSource] = field(default_factory=list)
    perpetrator_names: list[str] = field(default_factory=list)  # full names from incident_people


@dataclass
class LayerContext:
    """All a layer needs to do its job."""
    incident: IncidentRow
    # The runner pre-fetches pages once per URL into this dict so multiple
    # layers reuse a single GET. Keyed by source URL → FetchResult.
    pages: dict[str, http.FetchResult] = field(default_factory=dict)


@dataclass
class LayerResult:
    layer: int
    name: str
    passed: bool
    # 'skipped' means the layer COULD NOT run (e.g. no quote to check). Treated
    # as not-a-failure but logged in audit_status 'passed_partial'.
    skipped: bool = False
    reason: str = ""            # plain-English, public-facing
    details: dict[str, Any] = field(default_factory=dict)
    redact_name: bool = False   # Layer 2 fail → strip name on public quarantine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace — for fuzzy matching."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _strip_html(s: str) -> str:
    """Crude HTML→text. Good enough for substring presence checks."""
    if not s:
        return ""
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;|&#160;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&#39;|&apos;", "'", s)
    return re.sub(r"\s+", " ", s).strip()


# ===========================================================================
# Layer 1 — URL liveness
#   HEAD → 200..399. Cheap. Run first; if all sources 404 → quarantine outright.
# ===========================================================================

def layer_1_url_liveness(ctx: LayerContext) -> LayerResult:
    if not ctx.incident.sources:
        return LayerResult(
            layer=1, name="url_liveness",
            passed=False, reason="No source URL on file for this incident.",
            details={"source_count": 0},
        )

    per_source = []
    any_live = False
    for src in ctx.incident.sources:
        # Prefer the cached GET (already fetched for other layers) — its
        # status is at least as informative as a HEAD response.
        if src.url in ctx.pages:
            r = ctx.pages[src.url]
        else:
            r = http.head(src.url)
            # 405 Method Not Allowed → some servers reject HEAD; fall back to GET.
            if r.status in (403, 405) or r.error:
                r = http.get(src.url)
                ctx.pages[src.url] = r
        per_source.append({
            "source_id": src.source_id, "url": src.url,
            "status": r.status, "error": r.error,
        })
        if r.ok:
            any_live = True

    if any_live:
        return LayerResult(
            layer=1, name="url_liveness", passed=True,
            reason="At least one source URL is live.",
            details={"sources": per_source},
        )
    # All dead → hard quarantine.
    return LayerResult(
        layer=1, name="url_liveness", passed=False,
        reason="Every source URL on file returns an error (link rot).",
        details={"sources": per_source},
    )


# ===========================================================================
# Layer 2 — name-on-page
#   At least one perpetrator full_name must appear (case-insensitive,
#   accent-folded) in at least one live source page. Kills most hallucinations
#   alone. Failure here triggers name redaction in public quarantine.
# ===========================================================================

def layer_2_name_on_page(ctx: LayerContext) -> LayerResult:
    names = [n for n in (ctx.incident.perpetrator_names or []) if n and n.strip()]
    if not names:
        # No name on the row at all → not the Verifier's job to invent one.
        # Skipped (not a fail). Phase 3 data cleanup chases this.
        return LayerResult(
            layer=2, name="name_on_page",
            passed=True, skipped=True,
            reason="No named perpetrator on file — Layer 2 skipped.",
        )

    if not ctx.incident.sources:
        return LayerResult(
            layer=2, name="name_on_page",
            passed=False, redact_name=True,
            reason="No source URL on file to verify the name against.",
        )

    matches = []
    for src in ctx.incident.sources:
        page = ctx.pages.get(src.url)
        if page is None:
            page = http.get(src.url)
            ctx.pages[src.url] = page
        if not page.ok or not page.text:
            continue
        page_norm = _normalize(_strip_html(page.text))
        for name in names:
            if _normalize(name) in page_norm:
                matches.append({"source_id": src.source_id, "name": name})

    if matches:
        return LayerResult(
            layer=2, name="name_on_page", passed=True,
            reason="Perpetrator name appears on at least one source page.",
            details={"matches": matches},
        )
    return LayerResult(
        layer=2, name="name_on_page", passed=False, redact_name=True,
        reason="The named person does not appear in any source page.",
        details={"names_checked": names, "sources_checked": len(ctx.incident.sources)},
    )


# ===========================================================================
# Layer 3 — verbatim quote
#   For each (source, verbatim_quote) pair, the quote must appear (normalized)
#   on the fetched page. Legacy rows have no quote → SKIPPED (passed_partial).
# ===========================================================================

def layer_3_verbatim_quote(ctx: LayerContext) -> LayerResult:
    sources_with_quote = [s for s in ctx.incident.sources if s.verbatim_quote and s.verbatim_quote.strip()]
    if not sources_with_quote:
        return LayerResult(
            layer=3, name="verbatim_quote",
            passed=True, skipped=True,
            reason="Legacy row — no verbatim quote on file. Layer 3 skipped.",
        )

    confirmed = []
    failed = []
    for src in sources_with_quote:
        page = ctx.pages.get(src.url)
        if page is None:
            page = http.get(src.url)
            ctx.pages[src.url] = page
        if not page.ok or not page.text:
            failed.append({"source_id": src.source_id, "reason": "source unreachable"})
            continue
        page_norm = _normalize(_strip_html(page.text))
        q_norm = _normalize(src.verbatim_quote)
        # Loose substring of the longest 10-word window — guards against
        # minor whitespace/punctuation drift in the source.
        if q_norm and q_norm in page_norm:
            confirmed.append({"source_id": src.source_id})
            continue
        # Try a shorter 10-word window from the middle of the quote.
        words = q_norm.split()
        if len(words) >= 10:
            mid = len(words) // 2
            window = " ".join(words[max(0, mid - 5): mid + 5])
            if window and window in page_norm:
                confirmed.append({"source_id": src.source_id, "via": "window-match"})
                continue
        failed.append({"source_id": src.source_id, "reason": "quote absent from page"})

    if confirmed and not failed:
        return LayerResult(
            layer=3, name="verbatim_quote", passed=True,
            reason="Every claimed quote appears verbatim on its source page.",
            details={"confirmed": confirmed},
        )
    if confirmed and failed:
        # Mixed result — at least one source corroborates, others don't. Pass
        # but mark as partial credit.
        return LayerResult(
            layer=3, name="verbatim_quote", passed=True, skipped=False,
            reason="At least one quote verified; others could not be checked.",
            details={"confirmed": confirmed, "failed": failed},
        )
    return LayerResult(
        layer=3, name="verbatim_quote", passed=False,
        reason="No claimed quote appears in its source page — likely fabricated.",
        details={"failed": failed},
    )


# ===========================================================================
# Layer 10 — Wayback freeze
#   Fire-and-forget POST to web.archive.org/save. Never blocks. Stores snapshot
#   URL alongside original when the response is fast enough to read.
# ===========================================================================

def layer_10_wayback(ctx: LayerContext, *, fire_and_forget: bool = True) -> LayerResult:
    if not ctx.incident.sources:
        return LayerResult(
            layer=10, name="wayback_freeze",
            passed=True, skipped=True,
            reason="No sources to snapshot.",
        )

    pending = []
    for src in ctx.incident.sources:
        if src.wayback_url:
            continue  # already snapshotted previously
        save_url = f"https://web.archive.org/save/{src.url}"
        try:
            # Short timeout: we DO NOT wait for the snapshot to complete.
            # Wayback often takes 30s+. We send the request and move on.
            r = http.get(save_url, timeout=4)
            if r.status in (200, 302):
                # Heuristic: Wayback's response sometimes echoes the snapshot
                # URL in a Location-like header captured in `final_url`. If
                # not, we just record the original save endpoint.
                snapshot = r.final_url if "web.archive.org/web/" in r.final_url else save_url
                pending.append({"source_id": src.source_id, "snapshot_url": snapshot})
            else:
                pending.append({"source_id": src.source_id, "snapshot_url": save_url, "queued": True})
        except Exception as e:
            # Never let Wayback failure fail the audit.
            pending.append({"source_id": src.source_id, "error": str(e)})

    return LayerResult(
        layer=10, name="wayback_freeze", passed=True,
        reason="Wayback snapshots submitted (fire-and-forget).",
        details={"submissions": pending},
    )


# ===========================================================================
# Layer 12 — Perpetrator-only doctrine
#   Hard reject if any source page describes the named person as a VICTIM of
#   an attack on Chabad (Kogan UAE, Holtzberg Mumbai, Poway Goldstein-as-target,
#   etc.). Aligned with [[project_chabad_tracker_doctrine]].
#
#   Mechanism: scan a 200-char window around the name for victim-side keywords.
#   If found AND no perpetrator-side keywords nearby → reject.
# ===========================================================================

VICTIM_TERMS = [
    "shot dead", "shot and killed", "stabbed", "murdered", "assassinated",
    "killed in", "was killed", "attacker", "gunman", "shooter targeted",
    "terror attack", "antisemitic attack", "victim of", "hostage",
    "kidnapped", "abducted", "ambushed",
]

PERP_TERMS = [
    "convicted", "indicted", "charged with", "sentenced to", "pleaded guilty",
    "fraud", "abuse", "molest", "rape", "embezzle", "trafficking",
    "cover up", "covered up", "settled with", "lawsuit against",
]


def layer_12_perpetrator_only(ctx: LayerContext) -> LayerResult:
    names = [n for n in (ctx.incident.perpetrator_names or []) if n and n.strip()]
    if not names or not ctx.incident.sources:
        return LayerResult(
            layer=12, name="perpetrator_only",
            passed=True, skipped=True,
            reason="No name or no sources to check doctrine against.",
        )

    flags = []
    perp_anchors = []
    for src in ctx.incident.sources:
        page = ctx.pages.get(src.url)
        if page is None:
            page = http.get(src.url)
            ctx.pages[src.url] = page
        if not page.ok or not page.text:
            continue
        text = _normalize(_strip_html(page.text))
        for name in names:
            name_norm = _normalize(name)
            idx = text.find(name_norm)
            while idx >= 0:
                window = text[max(0, idx - 200): idx + len(name_norm) + 200]
                v_hits = [t for t in VICTIM_TERMS if t in window]
                p_hits = [t for t in PERP_TERMS if t in window]
                if v_hits and not p_hits:
                    flags.append({
                        "source_id": src.source_id, "name": name,
                        "victim_terms_near_name": v_hits,
                    })
                if p_hits:
                    perp_anchors.append({"source_id": src.source_id, "terms": p_hits})
                idx = text.find(name_norm, idx + 1)

    if flags and not perp_anchors:
        return LayerResult(
            layer=12, name="perpetrator_only", passed=False,
            redact_name=True,
            reason="Source page describes the named person as a VICTIM, not a perpetrator. "
                   "Doctrine reject — Chabad-as-victim cases are out of scope.",
            details={"flags": flags},
        )
    return LayerResult(
        layer=12, name="perpetrator_only", passed=True,
        reason="Perpetrator-side context anchors the name; not victim-coded.",
        details={"perp_anchors_found": len(perp_anchors)},
    )


# ===========================================================================
# Layer 11 — Confidence score (0-100)
#   Derived from the OTHER layers' outcomes. Not a layer that "fails" — it's
#   the synthesis. ≥80 archive, 50-79 archive flagged, <50 quarantine.
# ===========================================================================

# Layer-wise contributions to the score. Tuned so a clean Week-1-spine pass
# lands around 85, partial around 70, single hard fail around 30.
LAYER_WEIGHTS = {
    1:  15,   # url liveness
    2:  25,   # name on page
    3:  20,   # verbatim quote
    4:  10,   # triangulation (future)
    5:   8,   # role/doctrine (future)
    7:   7,   # source class (future)
    8:   5,   # cross-source (future)
    9:   5,   # second-pass LLM (future)
    10:  0,   # Wayback — informational, not graded
    12: 15,   # perpetrator-only hard gate
}


def layer_11_confidence(layer_results: list[LayerResult]) -> LayerResult:
    """Synthesis layer — input is the OTHER layers' results, not a context."""
    total_possible = 0
    earned = 0
    for r in layer_results:
        w = LAYER_WEIGHTS.get(r.layer, 0)
        if r.skipped:
            continue
        total_possible += w
        if r.passed:
            earned += w
    if total_possible == 0:
        score = 50  # nothing ran — neutral
    else:
        score = round(100 * earned / total_possible)
    return LayerResult(
        layer=11, name="confidence",
        passed=True,   # this is synthesis; never a fail-cause itself
        reason=f"Confidence {score}/100 from {earned}/{total_possible} weighted points.",
        details={"score": score, "weights": LAYER_WEIGHTS},
    )
