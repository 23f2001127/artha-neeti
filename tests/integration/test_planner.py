"""Planner routing and end-to-end orchestration against live APIs.

The routing tests make one Groq call each and verify the planning logic. The
``e2e`` tests run the full specialist fan-out and are far more quota-heavy;
deselect them with ``-m "live and not e2e"``.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from agents import planner
from tests.helpers import norm_text

pytestmark = pytest.mark.live

_ROUTING_GAP = float(os.environ.get("PLANNER_ROUTING_GAP_S", "12"))
_E2E_GAP = float(os.environ.get("PLANNER_TEST_GAP_S", "60"))
_CORPUS_WORDS = ("corpus", "ingest", "not one of", "annual report")

ROUTING_CASES = [
    pytest.param("what's Reliance's current stock price",
                 {"mode": "single", "selected": {"market_data"}, "skipped": {"news_sentiment", "filings"}},
                 id="price-only"),
    pytest.param("give me a complete research view on TCS",
                 {"mode": "single", "selected": {"market_data", "news_sentiment", "filings"}, "skipped": set()},
                 id="full-view"),
    pytest.param("give me a full picture on State Bank of India (SBI)",
                 {"mode": "single", "selected": {"market_data", "news_sentiment"}, "skipped": {"filings"},
                  "filings_skip_words": _CORPUS_WORDS},
                 id="not-in-corpus"),
    pytest.param("compare TCS and Infosys on fundamentals, sentiment and risk profile",
                 {"mode": "multi", "companies": {"TCS", "INFY"}},
                 id="comparison"),
]


def _selected(result: dict) -> set:
    return set(result.get("routing", {}).get("specialists_selected", []))


def _skipped(result: dict) -> dict:
    return {s["specialist"]: s["reason"] for s in result.get("routing", {}).get("specialists_skipped", [])}


def _ran(result: dict) -> set:
    return set().union(*[set(v) for v in result.get("specialist_status", {}).values()] or [set()])


@pytest.mark.pace(_ROUTING_GAP)
@pytest.mark.parametrize(("query", "expected"), ROUTING_CASES)
def test_routing_decision(query: str, expected: dict) -> None:
    state = asyncio.run(planner._route_node({"query": query, "model_name": planner.DEFAULT_MODEL}))
    routing = state["routing"]

    assert state["mode"] == expected["mode"]
    selected = set(routing["specialists_selected"])
    if "selected" in expected:
        assert selected == expected["selected"]
    if "skipped" in expected:
        assert {s["specialist"] for s in routing["specialists_skipped"]} == expected["skipped"]
        for skip in routing["specialists_skipped"]:
            assert len(skip["reason"]) > 10, f"{skip['specialist']} skipped without a real reason"
    if "filings_skip_words" in expected:
        reason = norm_text(next(s["reason"] for s in routing["specialists_skipped"] if s["specialist"] == "filings"))
        assert any(w in reason for w in expected["filings_skip_words"]), reason
    if "companies" in expected:
        assert expected["companies"] <= {c["ticker"] for c in state["companies"]}
    assert len(state["routing_trace"]) >= 3
    assert len(routing["rationale"]) > 20


@pytest.mark.e2e
@pytest.mark.pace(_E2E_GAP)
def test_price_query_runs_market_data_only() -> None:
    r = asyncio.run(planner.plan("what's Reliance's current stock price"))
    assert "routing" in r, r.get("error")
    assert r.get("mode") == "single"
    assert _selected(r) == {"market_data"}
    skipped = _skipped(r)
    assert len(skipped.get("news_sentiment", "")) > 8
    assert len(skipped.get("filings", "")) > 8
    assert _ran(r) == {"market_data"}
    assert "compare" not in " ".join(r.get("graph_path", []))
    assert len(r.get("routing_trace", [])) >= 2


@pytest.mark.e2e
@pytest.mark.pace(_E2E_GAP)
def test_full_view_runs_all_three_specialists() -> None:
    r = asyncio.run(planner.plan("give me a complete research view on TCS"))
    assert "routing" in r, r.get("error")
    assert r.get("mode") == "single"
    assert _selected(r) == {"market_data", "news_sentiment", "filings"}
    assert not _skipped(r)
    report = r.get("reports", {}).get("TCS", {})
    assert report and "error" not in report, report.get("error")
    assert len(report.get("executive_summary", "")) > 120
    assert report.get("overall_caveats")
    graph_path = r.get("graph_path", [])
    assert [s.split(":")[0].split(" ")[0] for s in graph_path][:1] == ["route"]
    assert "compare" not in " ".join(graph_path)


@pytest.mark.e2e
@pytest.mark.pace(_E2E_GAP)
def test_company_outside_corpus_skips_filings() -> None:
    r = asyncio.run(planner.plan("give me a full picture on State Bank of India (SBI)"))
    assert "routing" in r, r.get("error")
    sbi = next((c for c in r.get("companies", []) if c["ticker"] in ("SBIN", "SBI")), None)
    assert sbi is not None, r.get("companies")
    assert sbi["resolvable"], sbi.get("resolution_note")
    assert not sbi["in_filings_corpus"]
    assert {"market_data", "news_sentiment"} <= _selected(r)
    assert "filings" not in _selected(r)
    assert any(w in norm_text(_skipped(r).get("filings", "")) for w in _CORPUS_WORDS)

    report = next(iter(r.get("reports", {}).values()), {})
    assert report and "error" not in report, report.get("error")
    assert any("filings" in norm_text(m) for m in report.get("missing_data", []))


@pytest.mark.e2e
@pytest.mark.pace(_E2E_GAP * 2.5)
def test_comparison_builds_reports_and_compares() -> None:
    r = asyncio.run(planner.plan("compare TCS and Infosys on fundamentals, sentiment and risk profile"))
    assert "routing" in r, r.get("error")
    assert r.get("mode") == "multi"
    assert {"TCS", "INFY"} <= {c["ticker"] for c in r.get("companies", [])}
    good = [t for t, rep in r.get("reports", {}).items() if "error" not in rep]
    assert len(good) >= 2, good

    comparison = r.get("comparison")
    assert comparison, "comparison is null"
    assert len(comparison.get("dimensions", [])) >= 2
    assert comparison.get("caveats")
    assert "compare" in " ".join(r.get("graph_path", []))

    ok_cells = sum(1 for per in r.get("specialist_status", {}).values() for v in per.values() if v == "ok")
    # Only judge comparison quality when both sides have enough real data.
    if ok_cells >= 4 and {"TCS", "INFY"} <= set(r.get("reports", {})):
        blob = norm_text(comparison.get("verdict", "") + " "
                         + " ".join(d.get("assessment", "") for d in comparison.get("dimensions", [])))
        assert any(w in blob for w in ("edge", "higher", "lower", "stronger", "premium", "cheaper",
                                       "roe", "p/e", "margin", "sentiment", "vs", "whereas", "both")), blob[:160]
