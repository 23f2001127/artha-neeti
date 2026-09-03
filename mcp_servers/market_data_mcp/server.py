"""market-data-mcp - MCP server exposing yfinance-backed tools for Indian equities.

Transport: stdio (for now). Run directly with:

    python mcp_servers/market_data_mcp/server.py

or as a module:

    python -m mcp_servers.market_data_mcp.server

All ticker arguments accept NSE symbols (RELIANCE.NS), BSE symbols (RELIANCE.BO),
or bare symbols (RELIANCE -> treated as .NS). Ampersands are fine: M&M.NS.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Make ``import market_data`` work whether this file is run as a script or a module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import market_data as md  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer(
    name="market-data-mcp",
    version="0.1.0",
    instructions=(
        "Live market data for companies listed on Indian exchanges (NSE/BSE), "
        "sourced from Yahoo Finance via yfinance. Use these tools to answer "
        "questions about share price movement, valuation, fundamentals, financial "
        "ratios, and peer comparison. Pass tickers as NSE symbols (e.g. RELIANCE.NS, "
        "TCS.NS, M&M.NS); a bare symbol is assumed to be NSE. Every tool returns an "
        "'error' string instead of failing when a ticker is invalid or data is "
        "unavailable - surface that message rather than guessing."
    ),
)


@server.tool()
def get_price_history(ticker: str, period: str = "1mo") -> dict[str, Any]:
    """Return daily OHLCV (open/high/low/close/volume) price history for one Indian
    stock over a trailing window.

    Use this to describe recent price action, compute returns, or spot trends and
    volatility. For fundamentals or ratios use the other tools instead.

    Args:
        ticker: NSE/BSE symbol, e.g. "RELIANCE.NS", "TCS.NS", "M&M.NS". A bare
            symbol like "INFY" is treated as "INFY.NS".
        period: Trailing window. One of: "1d", "5d", "1mo", "3mo", "6mo", "1y",
            "5y". Defaults to "1mo".

    Returns:
        dict with ticker, name, period, currency, count, start/end dates, and
        "history": a list of {date, open, high, low, close, volume} rows in
        chronological order. On failure: {"error": "<message>"}.
    """
    return md.get_price_history(ticker, period)


@server.tool()
def get_fundamentals(ticker: str) -> dict[str, Any]:
    """Return a company profile and headline valuation figures for one Indian stock.

    Use this for "what does this company do / how big is it / how is it valued"
    questions: sector, market capitalisation, P/E, EPS, dividend yield, and the
    52-week trading range.

    Args:
        ticker: NSE/BSE symbol, e.g. "HDFCBANK.NS". A bare symbol is treated as .NS.

    Returns:
        dict with name, sector, industry, currency, current_price, market_cap,
        pe_ratio, forward_pe, eps_ttm, dividend_yield_pct (a percentage),
        fifty_two_week_high, fifty_two_week_low, "missing" (fields yfinance did not
        provide), "as_of" (when the snapshot was taken - price/market cap are
        near-real-time), and "last_fiscal_year_end" (the period the reported annual
        figures belong to). On failure: {"error": "<message>"}.
    """
    return md.get_fundamentals(ticker)


@server.tool()
def get_ratios(ticker: str) -> dict[str, Any]:
    """Return key profitability, leverage, and liquidity ratios for one Indian stock.

    Use this to judge financial quality: return on equity/assets, debt-to-equity,
    current and quick ratios, and profit/gross/operating/EBITDA margins.

    Availability varies by company. Values come from yfinance's summary data where
    present; ROE, ROA, debt-to-equity and current ratio are computed from the two
    most recent annual statements when the summary omits them (the "computed" list
    says which, and "fiscal_year" says which period). Computed ROE/ROA use net
    income to owners over AVERAGE equity/assets, matching yfinance's basis so
    values stay comparable across a peer set. Ratios that remain unavailable are
    null and listed under "missing".

    Args:
        ticker: NSE/BSE symbol, e.g. "TCS.NS". A bare symbol is treated as .NS.

    Returns:
        dict with roe, roa, debt_to_equity, current_ratio, quick_ratio,
        profit_margin, gross_margin, operating_margin, ebitda_margin, plus
        "computed", "missing", "fiscal_year", and "as_of". roe/roa/margins are
        fractions (0.15 == 15%); debt_to_equity is a percentage (36.65 == 0.37x).
        On failure: {"error": "<message>"}.
    """
    return md.get_ratios(ticker)


@server.tool()
def get_peer_comparison(tickers: list[str]) -> dict[str, Any]:
    """Compare several Indian stocks side by side on market cap, P/E, ROE and
    dividend yield.

    Use this for "how does X stack up against its peers" questions. Pass two or
    more tickers (works with one, but comparison is the point).

    Args:
        tickers: List of NSE/BSE symbols, e.g. ["RELIANCE.NS", "ONGC.NS",
            "IOC.NS"]. Bare symbols are treated as .NS.

    Returns:
        dict with "companies": one row per resolved ticker containing ticker,
        name, sector, market_cap, pe_ratio, roe, roe_source ("yfinance" or
        "computed"), fiscal_year, and dividend_yield_pct - sorted by market cap,
        largest first. Check roe_source/fiscal_year before comparing ROE across
        rows. Tickers that could not be resolved appear under "errors" (keyed by
        symbol) while the rest still return. "error" is set only if none of the
        tickers resolved.
    """
    return md.get_peer_comparison(tickers)


if __name__ == "__main__":
    server.run("stdio")
