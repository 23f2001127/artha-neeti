"""Input validation in market_data.py that returns before any network call."""

from __future__ import annotations

import pytest

from mcp_servers.market_data_mcp import market_data as md


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("M&M.NS", "M&M.NS"), ("m&m", "M&M.NS"), (" tcs ", "TCS.NS"), ("RELIANCE.BO", "RELIANCE.BO")],
)
def test_normalize_ticker(raw: str, expected: str) -> None:
    assert md.normalize_ticker(raw) == expected


def test_normalize_ticker_rejects_empty() -> None:
    with pytest.raises(md.MarketDataError):
        md.normalize_ticker("  ")


def test_invalid_period_returns_error() -> None:
    assert "error" in md.get_price_history("RELIANCE.NS", period="42y")


def test_empty_peer_list_returns_error() -> None:
    assert "error" in md.get_peer_comparison([])
