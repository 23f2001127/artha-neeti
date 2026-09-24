"""Attribution of numbers and citations to the right company and source."""

from __future__ import annotations

from agents import planner
from agents.synthesis_agent import _SOURCE_SPLIT_RE


def test_portfolio_metrics_ignore_peer_lookups() -> None:
    raw = {
        "get_fundamentals": {"ticker": "INFY.NS", "sector": "Technology", "pe_ratio": 13.2},
        "get_ratios": {"ticker": "TCS.NS", "roe": 0.477},
    }
    assert planner._extract_field(raw, "pe_ratio", (int, float), "TCS") is None
    assert planner._extract_field(raw, "roe", (int, float), "TCS") == 0.477
    assert planner._extract_field(raw, "pe_ratio", (int, float), "INFY") == 13.2


def test_results_without_a_ticker_are_accepted() -> None:
    assert planner._extract_field({"x": {"pe_ratio": 9.0}}, "pe_ratio", (int, float), "TCS") == 9.0


def test_citation_commas_inside_parentheses_are_kept() -> None:
    raw = "news_sentiment (univest.in, 16 Sep 2026), filings (TCS FY2025-26, p.38), market_data"
    assert [s.strip() for s in _SOURCE_SPLIT_RE.split(raw)] == [
        "news_sentiment (univest.in, 16 Sep 2026)",
        "filings (TCS FY2025-26, p.38)",
        "market_data",
    ]
