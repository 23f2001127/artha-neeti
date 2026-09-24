"""Market Data Agent tool selection against live Groq and yfinance."""

from __future__ import annotations

import os

import pytest

from agents.market_data_agent import run_sync

pytestmark = [pytest.mark.live, pytest.mark.pace(float(os.environ.get("GROQ_TEST_GAP_S", "30")))]

CASES = [
    pytest.param(
        "what's Reliance's current stock price?",
        {"expect_any": [{"get_fundamentals"}, {"get_price_history"}], "expect_not": {"get_peer_comparison"}},
        id="single-tool-price",
    ),
    pytest.param(
        "how is TCS valued compared to its fundamentals?",
        {"expect_all": {"get_fundamentals", "get_ratios"}, "expect_not": {"get_peer_comparison"}},
        id="multi-tool-valuation",
    ),
    pytest.param(
        "compare Reliance, TCS, and M&M",
        {"expect_all": {"get_peer_comparison"},
         "expect_not": {"get_fundamentals", "get_ratios", "get_price_history"}},
        id="peer-comparison",
    ),
]


@pytest.mark.parametrize(("query", "expectations"), CASES)
def test_tool_selection_and_provenance(query: str, expectations: dict) -> None:
    result = run_sync(query)
    assert "error" not in result, result.get("error")
    called = set(result.get("tools_called", []))

    assert result.get("findings")
    if "expect_all" in expectations:
        assert expectations["expect_all"] <= called, f"called {sorted(called)}"
    if "expect_any" in expectations:
        assert any(s <= called for s in expectations["expect_any"]), f"called {sorted(called)}"
    if "expect_not" in expectations:
        assert not (expectations["expect_not"] & called), f"called {sorted(called)}"
    assert any(
        "as_of" in v or "fiscal_year" in v or "per_company" in v
        for v in result.get("provenance", {}).values()
    ), "provenance must carry as_of / fiscal_year / per_company"
