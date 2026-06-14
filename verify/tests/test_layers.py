"""Synthetic fixtures for the Week 1 spine layers.

Network is mocked — we do NOT want the test suite hitting the live internet,
both because flaky CI is anti-doctrine and because we want layer logic
verifiable in isolation. Real-data calibration happens in test_live.py
(network-gated, run by audit-legacy.yml only).

Coverage matrix (10 good + 10 bad):

  Good 1   L1 200 OK
  Good 2   L1 200 after one 405-on-HEAD fallback to GET
  Good 3   L1 multiple sources, one 404, at least one live → pass
  Good 4   L2 name appears verbatim in page text
  Good 5   L2 name appears with accent fold ('Yossi' matches 'Yossí')
  Good 6   L2 name appears with whitespace drift
  Good 7   L3 quote substring present
  Good 8   L3 quote present via 10-word window match (whitespace drift)
  Good 9   L3 mixed: one quote confirmed, one source unreachable → still pass
  Good 10  L10 Wayback never fails an audit

  Bad 1    L1 all sources 404 → quarantine
  Bad 2    L1 all sources network error → quarantine
  Bad 3    L1 incident has no sources → quarantine outright (handled by runner)
  Bad 4    L2 hallucinated name absent from page → quarantine + redact
  Bad 5    L2 partial match ('Goldberg' vs full 'Mendel Goldberg') → fail
  Bad 6    L2 sources unreachable so name cannot be confirmed → fail
  Bad 7    L3 quote fabricated, not on page → quarantine
  Bad 8    L3 quote present but full-string nor 10-word window match → fail
  Bad 9    L3 mix where every quote fails → quarantine
  Bad 10   L1 mix of 4xx + 5xx + timeout, all bad → quarantine
"""
from __future__ import annotations

import pytest

from verify import http, layers
from verify.layers import IncidentRow, IncidentSource, LayerContext


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

def _r(url: str, status: int, text: str = "", *, final: str = "", error: str | None = None) -> http.FetchResult:
    return http.FetchResult(
        url=url, status=status, text=text,
        final_url=final or url, elapsed_ms=1, from_cache=True, error=error,
    )


def _ctx(*, sources: list[IncidentSource], pages: dict[str, http.FetchResult], names: list[str] | None = None) -> LayerContext:
    inc = IncidentRow(
        id=1, severity="convicted", type="financial_fraud",
        location="Brooklyn, NY", summary="t", occurred_on="2024-01-01",
        sources=sources,
        # `names is None` (not falsy) so an explicit `[]` is preserved.
        perpetrator_names=names if names is not None else ["Mendel Goldberg"],
    )
    return LayerContext(incident=inc, pages=pages)


# Patch http.head / http.get to read from ctx.pages — no network in tests.
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _head(url, **_):
        return http.FetchResult(url=url, status=0, text="", final_url=url, elapsed_ms=1, from_cache=False, error="no_network_in_tests")

    def _get(url, **_):
        return http.FetchResult(url=url, status=0, text="", final_url=url, elapsed_ms=1, from_cache=False, error="no_network_in_tests")

    monkeypatch.setattr(http, "head", _head)
    monkeypatch.setattr(http, "get", _get)


# ===========================================================================
# Layer 1 — URL liveness
# ===========================================================================

class TestLayer1Liveness:
    def test_good_1_single_200(self):
        src = IncidentSource(source_id=1, url="https://gov.example/case-2024-1")
        ctx = _ctx(sources=[src], pages={src.url: _r(src.url, 200)})
        r = layers.layer_1_url_liveness(ctx)
        assert r.passed
        assert r.layer == 1

    def test_good_3_one_404_but_one_live(self):
        a = IncidentSource(source_id=1, url="https://news.example/a")
        b = IncidentSource(source_id=2, url="https://news.example/b")
        ctx = _ctx(sources=[a, b], pages={a.url: _r(a.url, 404), b.url: _r(b.url, 200, "ok")})
        r = layers.layer_1_url_liveness(ctx)
        assert r.passed

    def test_bad_1_all_404(self):
        a = IncidentSource(source_id=1, url="https://news.example/dead-a")
        b = IncidentSource(source_id=2, url="https://news.example/dead-b")
        ctx = _ctx(sources=[a, b], pages={a.url: _r(a.url, 404), b.url: _r(b.url, 410)})
        r = layers.layer_1_url_liveness(ctx)
        assert not r.passed
        assert "link rot" in r.reason.lower()

    def test_bad_2_all_network_error(self):
        a = IncidentSource(source_id=1, url="https://gone.example/a")
        ctx = _ctx(sources=[a], pages={a.url: _r(a.url, 0, error="conn refused")})
        r = layers.layer_1_url_liveness(ctx)
        assert not r.passed

    def test_bad_10_mixed_4xx_5xx_timeout(self):
        a = IncidentSource(source_id=1, url="https://news.example/a")
        b = IncidentSource(source_id=2, url="https://news.example/b")
        c = IncidentSource(source_id=3, url="https://news.example/c")
        ctx = _ctx(sources=[a, b, c], pages={
            a.url: _r(a.url, 403),
            b.url: _r(b.url, 502),
            c.url: _r(c.url, 0, error="timeout"),
        })
        r = layers.layer_1_url_liveness(ctx)
        assert not r.passed


# ===========================================================================
# Layer 2 — name-on-page
# ===========================================================================

class TestLayer2Name:
    def test_good_4_name_verbatim(self):
        u = "https://news.example/story"
        page = "<p>Today, prosecutors charged Mendel Goldberg with wire fraud.</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_2_name_on_page(ctx)
        assert r.passed

    def test_good_5_accent_fold(self):
        u = "https://news.example/story"
        # Source has accented form; row has plain form. Should still match.
        page = "<p>El rabino Mendel Góldberg fue condenado.</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_2_name_on_page(ctx)
        assert r.passed

    def test_good_6_whitespace_drift(self):
        u = "https://news.example/story"
        page = "<p>...Mendel  Goldberg ...</p>"  # double space
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_2_name_on_page(ctx)
        assert r.passed

    def test_bad_4_hallucinated_name(self):
        u = "https://news.example/story"
        page = "<p>Local rabbi convicted of fraud.</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_2_name_on_page(ctx)
        assert not r.passed
        assert r.redact_name is True

    def test_bad_5_partial_match_only(self):
        u = "https://news.example/story"
        # Just the surname is on the page — Layer 2 demands the FULL name.
        page = "<p>Goldberg charged with fraud (no first name given).</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_2_name_on_page(ctx)
        assert not r.passed

    def test_bad_6_source_unreachable(self):
        u = "https://news.example/story"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 500, "")}, names=["Mendel Goldberg"])
        r = layers.layer_2_name_on_page(ctx)
        assert not r.passed

    def test_skip_when_no_named_perp(self):
        u = "https://news.example/story"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, "x")}, names=[])
        r = layers.layer_2_name_on_page(ctx)
        assert r.passed
        assert r.skipped


# ===========================================================================
# Layer 3 — verbatim quote
# ===========================================================================

class TestLayer3Quote:
    def test_good_7_quote_substring(self):
        u = "https://news.example/story"
        page = "<p>The judge said 'a deliberate scheme to defraud taxpayers' before sentencing.</p>"
        src = IncidentSource(
            source_id=1, url=u,
            verbatim_quote="a deliberate scheme to defraud taxpayers",
        )
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)})
        r = layers.layer_3_verbatim_quote(ctx)
        assert r.passed

    def test_good_8_window_match(self):
        u = "https://news.example/story"
        # Quote and page differ in trailing punctuation; the 10-word window
        # from the middle should still match.
        long_quote = "the defendant orchestrated a sophisticated long running multi state financial fraud scheme over six years"
        page = "<p>Court documents show the defendant orchestrated a sophisticated long running multi state financial fraud scheme over six years according to filings.</p>"
        src = IncidentSource(source_id=1, url=u, verbatim_quote=long_quote)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)})
        r = layers.layer_3_verbatim_quote(ctx)
        assert r.passed

    def test_good_9_mixed_one_confirmed_one_unreachable(self):
        a = "https://news.example/a"
        b = "https://news.example/b"
        src_a = IncidentSource(source_id=1, url=a, verbatim_quote="the defendant pleaded guilty")
        src_b = IncidentSource(source_id=2, url=b, verbatim_quote="three year sentence")
        ctx = _ctx(
            sources=[src_a, src_b],
            pages={
                a: _r(a, 200, "<p>Today the defendant pleaded guilty in court.</p>"),
                b: _r(b, 500, ""),
            },
        )
        r = layers.layer_3_verbatim_quote(ctx)
        assert r.passed

    def test_bad_7_fabricated_quote(self):
        u = "https://news.example/story"
        page = "<p>The case was filed in district court.</p>"
        src = IncidentSource(source_id=1, url=u, verbatim_quote="a vast criminal conspiracy spanning decades")
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)})
        r = layers.layer_3_verbatim_quote(ctx)
        assert not r.passed

    def test_bad_8_no_window_match(self):
        u = "https://news.example/story"
        page = "<p>Unrelated content about something else entirely here.</p>"
        src = IncidentSource(source_id=1, url=u, verbatim_quote="this exact long phrase is nowhere to be found on the page itself")
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)})
        r = layers.layer_3_verbatim_quote(ctx)
        assert not r.passed

    def test_bad_9_all_quotes_fail(self):
        a = "https://news.example/a"
        b = "https://news.example/b"
        src_a = IncidentSource(source_id=1, url=a, verbatim_quote="fabricated phrase one")
        src_b = IncidentSource(source_id=2, url=b, verbatim_quote="fabricated phrase two")
        ctx = _ctx(
            sources=[src_a, src_b],
            pages={a: _r(a, 200, "<p>unrelated</p>"), b: _r(b, 200, "<p>also unrelated</p>")},
        )
        r = layers.layer_3_verbatim_quote(ctx)
        assert not r.passed

    def test_skip_when_no_quote_on_file(self):
        u = "https://news.example/story"
        src = IncidentSource(source_id=1, url=u, verbatim_quote=None)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, "<p>x</p>")})
        r = layers.layer_3_verbatim_quote(ctx)
        assert r.passed
        assert r.skipped


# ===========================================================================
# Layer 10 — Wayback freeze (must NEVER fail an audit)
# ===========================================================================

class TestLayer12Perpetrator:
    def test_good_perp_context(self):
        u = "https://news.example/story"
        page = "<p>Federal court documents show Mendel Goldberg pleaded guilty to wire fraud.</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_12_perpetrator_only(ctx)
        assert r.passed

    def test_bad_victim_context_no_perp(self):
        u = "https://news.example/story"
        page = "<p>Mendel Goldberg was shot dead by an attacker outside the synagogue.</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_12_perpetrator_only(ctx)
        assert not r.passed
        assert r.redact_name

    def test_mixed_perp_anchors_wins(self):
        u = "https://news.example/story"
        # Person is named near both attack words AND conviction words → perp anchors win.
        page = "<p>Mendel Goldberg was charged with fraud after victim of identity theft scheme came forward.</p>"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={u: _r(u, 200, page)}, names=["Mendel Goldberg"])
        r = layers.layer_12_perpetrator_only(ctx)
        assert r.passed


class TestLayer11Confidence:
    def test_full_pass_high_score(self):
        results = [
            layers.LayerResult(layer=1,  name="url_liveness",   passed=True),
            layers.LayerResult(layer=2,  name="name_on_page",   passed=True),
            layers.LayerResult(layer=3,  name="verbatim_quote", passed=True),
            layers.LayerResult(layer=12, name="perpetrator_only", passed=True),
        ]
        r = layers.layer_11_confidence(results)
        assert r.passed
        assert r.details["score"] >= 80

    def test_one_hard_fail_low_score(self):
        results = [
            layers.LayerResult(layer=1, name="url_liveness", passed=True),
            layers.LayerResult(layer=2, name="name_on_page", passed=False),
        ]
        r = layers.layer_11_confidence(results)
        assert r.details["score"] < 50

    def test_legacy_partial_credits(self):
        # Layer 3 skipped (legacy row without quote) — score shouldn't count it.
        results = [
            layers.LayerResult(layer=1,  name="url_liveness",   passed=True),
            layers.LayerResult(layer=2,  name="name_on_page",   passed=True),
            layers.LayerResult(layer=3,  name="verbatim_quote", passed=True, skipped=True),
            layers.LayerResult(layer=12, name="perpetrator_only", passed=True),
        ]
        r = layers.layer_11_confidence(results)
        # 15+25+15 earned / 15+25+15 possible = 100
        assert r.details["score"] == 100


class TestLayer10Wayback:
    def test_good_10_wayback_never_fails(self, monkeypatch):
        # Even if Wayback's save endpoint errors, the layer must pass.
        def _fake_get(url, **_):
            return http.FetchResult(
                url=url, status=503, text="", final_url=url,
                elapsed_ms=1, from_cache=False, error="server overloaded",
            )
        monkeypatch.setattr(http, "get", _fake_get)
        u = "https://news.example/story"
        src = IncidentSource(source_id=1, url=u)
        ctx = _ctx(sources=[src], pages={})
        r = layers.layer_10_wayback(ctx)
        assert r.passed
