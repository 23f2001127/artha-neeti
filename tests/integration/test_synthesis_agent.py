"""Synthesis Agent against real outputs from all three specialists for TCS."""

from __future__ import annotations

import os
import time

import pytest

from agents.filings_agent import run_sync as filings_run
from agents.market_data_agent import run_sync as market_run
from agents.news_sentiment_agent import run_sync as news_run
from agents.synthesis_agent import synthesize_sync
from tests.helpers import norm_text

_GAP = float(os.environ.get("SYNTH_TEST_GAP_S", "40"))

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.pace(_GAP)]

SPECIALISTS = ("market_data", "news_sentiment", "filings")
TOP_QUERY = (
    "Give me the overall picture on TCS - fundamentals, market sentiment and the "
    "risks it discloses. Is the near-term outlook as strong as the fundamentals?"
)
_UPSTREAM_HEDGES = (
    "as_of", "as of", "fiscal year", "fiscal-year", "fy20", "trailing",
    "self-reported", "not calibrated", "sample", "surfaced news",
    "tabular", "flatten", "column-collapse", "column-flatten",
    "roe_source", "computed", "not the nse", "nse/bse", "official feed",
    "one annual report", "single filing", "single annual report", "not a multi-year",
)


@pytest.fixture(scope="module")
def specialist_outputs() -> dict:
    outputs = {"market_data": market_run("how is TCS valued compared to its fundamentals?")}
    time.sleep(_GAP)
    outputs["news_sentiment"] = news_run("what's the market sentiment on TCS right now?")
    time.sleep(_GAP)
    outputs["filings"] = filings_run("what are TCS's key disclosed risks?")
    time.sleep(_GAP)
    if not any(isinstance(v, dict) and "error" not in v for v in outputs.values()):
        pytest.skip("every specialist errored (likely provider quota); cannot exercise synthesis")
    return outputs


def _report_blob(report: dict) -> str:
    parts = [report.get("executive_summary", ""), *report.get("sections", {}).values(),
             *report.get("overall_caveats", []), *report.get("missing_data", [])]
    for c in report.get("conflicts_flagged", []):
        parts += [c.get("position_a", ""), c.get("position_b", ""), c.get("assessment", "")]
    parts += [meta.get("caveat") or "" for meta in report.get("sources_by_claim", {}).values()]
    return norm_text(" ".join(parts))


def test_full_synthesis(specialist_outputs: dict) -> None:
    r = synthesize_sync(TOP_QUERY, specialist_outputs)
    assert "error" not in r, r.get("error")
    ok = [k for k, v in specialist_outputs.items() if isinstance(v, dict) and "error" not in v]

    for key in ("query", "companies", "executive_summary", "sections",
                "conflicts_flagged", "overall_caveats", "missing_data", "sources_by_claim"):
        assert key in r
    assert any("tcs" in norm_text(c) or "tata" in norm_text(c) for c in r["companies"])
    assert len(r.get("executive_summary", "")) > 120
    assert set(r["sections"]) == set(SPECIALISTS)
    assert all(len(r["sections"][k]) > 40 for k in ok)

    claims = r["sources_by_claim"]
    assert claims
    assert all(meta.get("sources") for meta in claims.values())
    assert all(any(s.split()[0].strip(":,") in SPECIALISTS for s in meta["sources"]) for meta in claims.values())
    assert r["overall_caveats"]

    hedges = [h for h in _UPSTREAM_HEDGES if h in _report_blob(r)]
    assert len(hedges) >= 2, f"upstream hedges lost; found {hedges}"
    assert any(meta.get("caveat") for meta in claims.values())
    assert not any("not provided" in norm_text(m) and any(k in norm_text(m) for k in ok)
                   for m in r["missing_data"]), r["missing_data"]

    news = specialist_outputs.get("news_sentiment", {})
    news_blob = norm_text(" ".join(news.get("findings", []) + [news.get("summary", "")]))
    leans_negative = any(w in news_blob for w in ("negative", "cautious", "weak", "muted", "decline", "concern"))
    assert isinstance(r["conflicts_flagged"], list)
    if leans_negative and {"market_data", "news_sentiment"} <= set(ok):
        assert r["conflicts_flagged"], "fundamentals-vs-sentiment tension should be flagged"
        assert any(
            "sentiment" in norm_text(c.get("topic", "") + c.get("position_a", "")
                                     + c.get("position_b", "") + c.get("assessment", ""))
            for c in r["conflicts_flagged"]
        )


def test_partial_synthesis_reports_missing_filings(specialist_outputs: dict) -> None:
    partial = {k: v for k, v in specialist_outputs.items() if k != "filings"}
    r = synthesize_sync(TOP_QUERY, partial)
    assert "error" not in r, r.get("error")
    assert len(r.get("executive_summary", "")) > 120
    assert "filings" not in r.get("specialists_used", [])
    assert any("filings" in norm_text(m) for m in r["missing_data"]), r["missing_data"]
    assert norm_text(r["sections"].get("filings", "")).startswith("not available")
    assert len(r["sections"].get("market_data", "")) > 40
    assert len(r["sections"].get("news_sentiment", "")) > 40
    invented = [c for c, m in r["sources_by_claim"].items() if any("filings" in s.lower() for s in m["sources"])]
    assert not invented, f"claims cite the absent filings specialist: {invented}"
