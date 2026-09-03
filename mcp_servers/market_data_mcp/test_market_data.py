"""Standalone smoke test for market-data-mcp.

Not pytest - just a runnable script that hits the live yfinance API so you can
eyeball the output. Run it from anywhere:

    python mcp_servers/market_data_mcp/test_market_data.py

It:
  1. calls all 4 tools against RELIANCE.NS, TCS.NS, and M&M.NS and prints results
  2. runs a focused check on the M&M.NS ampersand symbol
  3. checks that invalid tickers / periods return a clean error, not a crash

Exit code is non-zero if any assertion fails. Needs network access.
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# yfinance logs "HTTP Error 404" / "No data found" at ERROR when we probe a
# deliberately-bad ticker below. Those are expected here, so keep the output clean.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

import market_data as md

TICKERS = ["RELIANCE.NS", "TCS.NS", "M&M.NS"]

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def dump(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# --------------------------------------------------------------------------- #
def run_all_tools() -> None:
    for ticker in TICKERS:
        section(f"{ticker}  ::  get_price_history(period='1mo')")
        hist = md.get_price_history(ticker, period="1mo")
        if "error" in hist:
            dump(hist)
            check(f"{ticker} price history", False, hist["error"])
        else:
            print(
                f"  {hist['count']} rows  {hist['start']} -> {hist['end']}  "
                f"({hist['currency']})"
            )
            print("  last 3 rows:")
            dump(hist["history"][-3:])
            check(f"{ticker} price history has rows", hist["count"] > 0)

        section(f"{ticker}  ::  get_fundamentals()")
        fund = md.get_fundamentals(ticker)
        dump(fund)
        check(f"{ticker} fundamentals ok", "error" not in fund)
        if "error" not in fund:
            check(f"{ticker} has a name", bool(fund.get("name")), str(fund.get("name")))
            check(
                f"{ticker} has market cap",
                isinstance(fund.get("market_cap"), (int, float)),
            )

        section(f"{ticker}  ::  get_ratios()")
        ratios = md.get_ratios(ticker)
        dump(ratios)
        check(f"{ticker} ratios ok", "error" not in ratios)
        if "error" not in ratios:
            check(
                f"{ticker} has ROE (from .info or computed)",
                ratios.get("roe") is not None,
                f"computed={ratios.get('computed')}",
            )
            if "roe" in ratios.get("computed", []):
                check(
                    f"{ticker} computed ROE carries a fiscal_year",
                    bool(ratios.get("fiscal_year")),
                    str(ratios.get("fiscal_year")),
                )

    section("get_peer_comparison(RELIANCE.NS, TCS.NS, M&M.NS)")
    peers = md.get_peer_comparison(TICKERS)
    dump(peers)
    check("peer comparison returns all 3", len(peers.get("companies", [])) == 3)
    check(
        "peer comparison sorted by market cap desc",
        [c["market_cap"] for c in peers.get("companies", [])]
        == sorted(
            (c["market_cap"] for c in peers.get("companies", [])),
            reverse=True,
        ),
    )


def test_mnm_ampersand() -> None:
    section("FOCUS: M&M.NS ampersand handling")

    check(
        "normalize_ticker keeps 'M&M.NS' intact",
        md.normalize_ticker("M&M.NS") == "M&M.NS",
        md.normalize_ticker("M&M.NS"),
    )
    check(
        "normalize_ticker adds .NS to bare 'M&M'",
        md.normalize_ticker("m&m") == "M&M.NS",
        md.normalize_ticker("m&m"),
    )

    fund = md.get_fundamentals("M&M.NS")
    check("M&M.NS fundamentals resolve", "error" not in fund, fund.get("error", ""))
    name = (fund.get("name") or "").lower()
    check("M&M.NS resolves to Mahindra", "mahindra" in name, fund.get("name"))
    check(
        "M&M.NS market cap is a positive number",
        isinstance(fund.get("market_cap"), (int, float)) and fund["market_cap"] > 0,
        str(fund.get("market_cap")),
    )

    hist = md.get_price_history("M&M.NS", period="5d")
    check("M&M.NS price history resolves", "error" not in hist, hist.get("error", ""))
    check("M&M.NS price history has rows", hist.get("count", 0) > 0)


def test_failure_cases() -> None:
    section("FOCUS: graceful failure handling")

    bad = md.get_fundamentals("NOTAREALTICKER.NS")
    dump(bad)
    check("invalid ticker returns an error string", "error" in bad)

    bad_hist = md.get_price_history("RELIANCE.NS", period="42y")
    dump(bad_hist)
    check("invalid period returns an error string", "error" in bad_hist)

    empty = md.get_peer_comparison([])
    check("empty peer list returns an error string", "error" in empty)

    partial = md.get_peer_comparison(["RELIANCE.NS", "NOTAREAL.NS"])
    check(
        "peer comparison returns partial results + errors",
        len(partial.get("companies", [])) == 1 and "errors" in partial,
        f"companies={len(partial.get('companies', []))} errors={list(partial.get('errors', {}))}",
    )


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    run_all_tools()
    test_mnm_ampersand()
    test_failure_cases()

    section("SUMMARY")
    if _failures:
        print(f"  {len(_failures)} check(s) FAILED:")
        for name in _failures:
            print(f"    - {name}")
        sys.exit(1)
    print("  all checks passed")
    sys.exit(0)
