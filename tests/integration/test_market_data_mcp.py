"""market-data-mcp tool functions against live yfinance data."""

from __future__ import annotations

import pytest

from mcp_servers.market_data_mcp import market_data as md

pytestmark = pytest.mark.live

TICKERS = ["RELIANCE.NS", "TCS.NS", "M&M.NS"]


@pytest.mark.parametrize("ticker", TICKERS)
def test_price_history_has_rows(ticker: str) -> None:
    hist = md.get_price_history(ticker, period="1mo")
    assert "error" not in hist, hist.get("error")
    assert hist["count"] > 0


@pytest.mark.parametrize("ticker", TICKERS)
def test_fundamentals(ticker: str) -> None:
    fund = md.get_fundamentals(ticker)
    assert "error" not in fund, fund.get("error")
    assert fund.get("name")
    assert isinstance(fund.get("market_cap"), (int, float))


@pytest.mark.parametrize("ticker", TICKERS)
def test_ratios(ticker: str) -> None:
    ratios = md.get_ratios(ticker)
    assert "error" not in ratios, ratios.get("error")
    assert ratios.get("roe") is not None, f"computed={ratios.get('computed')}"
    if "roe" in ratios.get("computed", []):
        assert ratios.get("fiscal_year"), "computed ROE must carry its fiscal year"


def test_peer_comparison_returns_all_sorted_by_market_cap() -> None:
    peers = md.get_peer_comparison(TICKERS)
    companies = peers.get("companies", [])
    assert len(companies) == 3
    caps = [c["market_cap"] for c in companies]
    assert caps == sorted(caps, reverse=True)


def test_ampersand_ticker_resolves_to_mahindra() -> None:
    fund = md.get_fundamentals("M&M.NS")
    assert "error" not in fund, fund.get("error")
    assert "mahindra" in (fund.get("name") or "").lower()
    assert isinstance(fund.get("market_cap"), (int, float)) and fund["market_cap"] > 0

    hist = md.get_price_history("M&M.NS", period="5d")
    assert "error" not in hist, hist.get("error")
    assert hist.get("count", 0) > 0


def test_invalid_ticker_returns_error() -> None:
    assert "error" in md.get_fundamentals("NOTAREALTICKER.NS")


def test_peer_comparison_returns_partial_results_with_errors() -> None:
    partial = md.get_peer_comparison(["RELIANCE.NS", "NOTAREAL.NS"])
    assert len(partial.get("companies", [])) == 1
    assert "errors" in partial
