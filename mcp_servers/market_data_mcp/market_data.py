"""Core market-data functions backed by yfinance.

These functions are deliberately framework-agnostic: they take plain arguments and
return plain JSON-serialisable dicts. The MCP layer in ``server.py`` is a thin
wrapper around them, and the standalone ``test_market_data.py`` script calls them
directly.

Design rules:
- A function never raises for an expected failure (bad ticker, no data, network
  hiccup). It returns ``{"error": "<human readable message>"}`` instead, so the
  calling agent gets a clear signal rather than a stack trace.
- Missing individual fields are reported as ``null`` and listed under a
  ``"missing"`` key rather than omitted, so the consumer can tell "not available"
  apart from "zero".
- Tickers are for Indian listings. A bare symbol gets the NSE ``.NS`` suffix;
  ``.BO`` (BSE) is also accepted. Symbols with an ampersand (e.g. ``M&M.NS``)
  work as-is and must not be mangled.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

VALID_PERIODS = ("1d", "5d", "1mo", "3mo", "6mo", "1y", "5y")


class MarketDataError(Exception):
    """Raised internally when a ticker cannot be resolved to usable data."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def normalize_ticker(ticker: str) -> str:
    """Uppercase, trim, and default a bare symbol to the NSE (.NS) suffix.

    Preserves ampersands and existing ``.NS`` / ``.BO`` suffixes.
    """
    if not ticker or not str(ticker).strip():
        raise MarketDataError("Ticker is empty.")
    t = str(ticker).strip().upper()
    if not (t.endswith(".NS") or t.endswith(".BO")):
        t = f"{t}.NS"
    return t


def _clean(value: Any) -> Any:
    """Convert NaN / inf to None and numpy scalars to plain Python numbers."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
    except (TypeError, ValueError):
        pass
    # numpy scalar -> python scalar
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            return value
    return value


def _round(value: Any, digits: int = 2) -> Any:
    value = _clean(value)
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def _looks_valid(info: dict) -> bool:
    """yfinance returns a near-empty dict for delisted / unknown symbols."""
    if not info or len(info) <= 1:
        return False
    return any(
        info.get(k) is not None
        for k in ("marketCap", "regularMarketPrice", "currentPrice", "longName", "shortName")
    )


def _load(ticker: str) -> tuple[yf.Ticker, dict]:
    """Return ``(Ticker, info)`` for a normalised symbol or raise MarketDataError."""
    symbol = normalize_ticker(ticker)
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}
    except Exception as exc:  # noqa: BLE001 - yfinance raises a grab-bag of errors
        raise MarketDataError(
            f"Could not fetch data for '{symbol}': {type(exc).__name__}: {exc}"
        ) from exc
    if not _looks_valid(info):
        raise MarketDataError(
            f"No market data for '{symbol}'. The symbol may be wrong, delisted, "
            f"or not an Indian listing (expected an NSE/BSE ticker such as RELIANCE.NS)."
        )
    return tk, info


def _now_utc_iso() -> str:
    """Current UTC time, seconds precision, as an ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _statement_values(df, *names: str, n: int = 2) -> list[float]:
    """Up to ``n`` most-recent values (newest first) for the first matching row."""
    if df is None or getattr(df, "empty", True):
        return []
    for name in names:
        if name in df.index:
            try:
                series = df.loc[name].dropna()
                if not series.empty:
                    return [float(x) for x in series.iloc[:n]]
            except (KeyError, IndexError, ValueError, TypeError):
                continue
    return []


def _statement_value(df, *names: str) -> float | None:
    """First matching row's most-recent (left-most column) value from a statement df."""
    values = _statement_values(df, *names, n=1)
    return values[0] if values else None


def _avg(values: list[float | None]) -> float | None:
    """Mean of the non-None values, or None if there are none."""
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _latest_period(*dfs) -> str | None:
    """Period-end date (YYYY-MM-DD) of the most recent column across the given statements."""
    for df in dfs:
        if df is None or getattr(df, "empty", True):
            continue
        try:
            return df.columns[0].strftime("%Y-%m-%d")
        except (AttributeError, IndexError, ValueError):
            continue
    return None


# --------------------------------------------------------------------------- #
# tool implementations
# --------------------------------------------------------------------------- #
def get_price_history(ticker: str, period: str = "1mo") -> dict:
    """OHLCV price history for one Indian equity."""
    if period not in VALID_PERIODS:
        return {
            "error": f"Invalid period '{period}'. Choose one of: {', '.join(VALID_PERIODS)}."
        }
    try:
        tk, info = _load(ticker)
    except MarketDataError as exc:
        return {"error": str(exc)}

    symbol = normalize_ticker(ticker)
    try:
        hist = tk.history(period=period, auto_adjust=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to load price history for '{symbol}': {exc}"}

    if hist is None or hist.empty:
        return {
            "error": f"No price history returned for '{symbol}' over period '{period}'."
        }

    rows = []
    for ts, row in hist.iterrows():
        rows.append(
            {
                "date": ts.strftime("%Y-%m-%d"),
                "open": _round(row.get("Open")),
                "high": _round(row.get("High")),
                "low": _round(row.get("Low")),
                "close": _round(row.get("Close")),
                "volume": int(_clean(row.get("Volume")) or 0),
            }
        )

    return {
        "ticker": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "period": period,
        "currency": info.get("currency"),
        "count": len(rows),
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "as_of": _now_utc_iso(),
        "history": rows,
    }


def get_fundamentals(ticker: str) -> dict:
    """Snapshot of company profile and headline valuation figures."""
    try:
        tk, info = _load(ticker)
    except MarketDataError as exc:
        return {"error": str(exc)}

    fields = {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "current_price": _round(info.get("currentPrice") or info.get("regularMarketPrice")),
        "market_cap": _clean(info.get("marketCap")),
        "pe_ratio": _round(info.get("trailingPE")),
        "forward_pe": _round(info.get("forwardPE")),
        "eps_ttm": _round(info.get("trailingEps")),
        "dividend_yield_pct": _round(info.get("dividendYield")),
        "fifty_two_week_high": _round(info.get("fiftyTwoWeekHigh")),
        "fifty_two_week_low": _round(info.get("fiftyTwoWeekLow")),
    }
    missing = [k for k, v in fields.items() if v is None]

    last_fy_end = info.get("lastFiscalYearEnd")
    if isinstance(last_fy_end, (int, float)):
        last_fy_end = datetime.fromtimestamp(last_fy_end, timezone.utc).strftime("%Y-%m-%d")
    else:
        last_fy_end = None

    return {
        "ticker": normalize_ticker(ticker),
        **fields,
        "missing": missing,
        "as_of": _now_utc_iso(),
        "last_fiscal_year_end": last_fy_end,
        "notes": "Price and market_cap are near-real-time (see as_of). pe_ratio / "
        "eps_ttm are trailing-twelve-month. dividend_yield_pct is a percentage "
        "(2.74 == 2.74%). market_cap is in the listing currency (INR for .NS "
        "symbols). last_fiscal_year_end is the period the reported annual figures "
        "belong to.",
    }


def get_ratios(ticker: str) -> dict:
    """Key profitability, leverage, and liquidity ratios.

    Values come from yfinance's ``.info`` where present. When ``.info`` omits one
    (common for large Indian names), it is computed from the two most recent annual
    statements, matching yfinance's own conventions so ``.info`` and computed values
    stay comparable across a peer set:

    - ROE  = net income to owners / **average** shareholders' equity (parent)
    - ROA  = net income to owners / **average** total assets
    - debt-to-equity = total debt / **total equity incl. minority interest**,
      period-end, as a percentage (matches yfinance's ``debtToEquity`` scale)
    - current ratio  = current assets / current liabilities, period-end

    ``"computed"`` lists which fields were derived from statements; ``"fiscal_year"``
    is the period those statements cover. Anything still unavailable is ``null`` and
    listed under ``"missing"``.
    """
    try:
        tk, info = _load(ticker)
    except MarketDataError as exc:
        return {"error": str(exc)}

    symbol = normalize_ticker(ticker)

    roe = _clean(info.get("returnOnEquity"))
    roa = _clean(info.get("returnOnAssets"))
    debt_to_equity = _clean(info.get("debtToEquity"))
    current_ratio = _clean(info.get("currentRatio"))
    quick_ratio = _clean(info.get("quickRatio"))

    computed: list[str] = []
    fiscal_year: str | None = None
    if roe is None or roa is None or debt_to_equity is None or current_ratio is None:
        try:
            financials = tk.financials
        except Exception:  # noqa: BLE001
            financials = None
        try:
            balance = tk.balance_sheet
        except Exception:  # noqa: BLE001
            balance = None

        fiscal_year = _latest_period(financials, balance)

        # net income attributable to owners of the parent (excludes minority interest)
        net_income = _statement_value(
            financials, "Net Income", "Net Income Common Stockholders"
        )
        # parent-only equity, and total equity including minority interest (for D/E)
        equity_series = _statement_values(
            balance, "Stockholders Equity", "Common Stock Equity"
        )
        avg_equity = _avg(equity_series)
        avg_assets = _avg(_statement_values(balance, "Total Assets"))
        total_equity_incl_minority = _statement_value(
            balance, "Total Equity Gross Minority Interest",
            "Stockholders Equity", "Common Stock Equity",
        )
        total_debt = _statement_value(balance, "Total Debt")
        current_assets = _statement_value(balance, "Current Assets", "Total Current Assets")
        current_liabilities = _statement_value(
            balance, "Current Liabilities", "Total Current Liabilities"
        )

        if roe is None and net_income is not None and avg_equity not in (None, 0):
            roe = net_income / avg_equity
            computed.append("roe")
        if roa is None and net_income is not None and avg_assets not in (None, 0):
            roa = net_income / avg_assets
            computed.append("roa")
        if (
            debt_to_equity is None
            and total_debt is not None
            and total_equity_incl_minority not in (None, 0)
        ):
            # yfinance's debtToEquity is a percentage against total equity incl. minority
            debt_to_equity = (total_debt / total_equity_incl_minority) * 100
            computed.append("debt_to_equity")
        if (
            current_ratio is None
            and current_assets is not None
            and current_liabilities not in (None, 0)
        ):
            current_ratio = current_assets / current_liabilities
            computed.append("current_ratio")

    ratios = {
        "roe": _round(roe, 4),
        "roa": _round(roa, 4),
        "debt_to_equity": _round(debt_to_equity),
        "current_ratio": _round(current_ratio),
        "quick_ratio": _round(quick_ratio),
        "profit_margin": _round(info.get("profitMargins"), 4),
        "gross_margin": _round(info.get("grossMargins"), 4),
        "operating_margin": _round(info.get("operatingMargins"), 4),
        "ebitda_margin": _round(info.get("ebitdaMargins"), 4),
    }
    missing = [k for k, v in ratios.items() if v is None]

    return {
        "ticker": symbol,
        "name": info.get("longName") or info.get("shortName"),
        **ratios,
        "computed": computed,
        "missing": missing,
        "fiscal_year": fiscal_year,
        "as_of": _now_utc_iso(),
        "notes": "roe/roa/*margin are fractions (0.15 == 15%). debt_to_equity is a "
        "percentage (36.65 == 0.37x). Fields under 'computed' were derived from the "
        "annual statements for the period in 'fiscal_year' (ROE/ROA on average "
        "equity/assets); the rest are from yfinance's .info, which reflects the "
        "last reported fiscal year / trailing twelve months.",
    }


def get_peer_comparison(tickers: list[str]) -> dict:
    """Side-by-side comparison of market cap, P/E, and ROE across several tickers."""
    if not tickers:
        return {"error": "Provide at least one ticker to compare."}
    if isinstance(tickers, str):
        tickers = [tickers]

    companies = []
    errors: dict[str, str] = {}
    for raw in tickers:
        try:
            symbol = normalize_ticker(raw)
        except MarketDataError as exc:
            errors[str(raw)] = str(exc)
            continue

        ratios = get_ratios(symbol)
        fundamentals = get_fundamentals(symbol)
        if "error" in fundamentals:
            errors[symbol] = fundamentals["error"]
            continue

        companies.append(
            {
                "ticker": symbol,
                "name": fundamentals.get("name"),
                "sector": fundamentals.get("sector"),
                "market_cap": fundamentals.get("market_cap"),
                "pe_ratio": fundamentals.get("pe_ratio"),
                "roe": None if "error" in ratios else ratios.get("roe"),
                "roe_source": None
                if "error" in ratios
                else ("computed" if "roe" in ratios.get("computed", []) else "yfinance"),
                "fiscal_year": None if "error" in ratios else ratios.get("fiscal_year"),
                "dividend_yield_pct": fundamentals.get("dividend_yield_pct"),
            }
        )

    # rank by market cap (largest first) when available
    companies.sort(
        key=lambda c: c["market_cap"] if isinstance(c["market_cap"], (int, float)) else -1,
        reverse=True,
    )

    result: dict = {
        "requested": [str(t) for t in tickers],
        "columns": [
            "ticker", "name", "sector", "market_cap", "pe_ratio",
            "roe", "roe_source", "fiscal_year", "dividend_yield_pct",
        ],
        "companies": companies,
        "as_of": _now_utc_iso(),
        "notes": "roe is a fraction (0.15 == 15%), on a consistent basis across rows "
        "(average equity, net income to owners). roe_source is 'yfinance' or "
        "'computed'; fiscal_year is the statement period behind a computed roe. "
        "dividend_yield_pct is a percentage. Rows are sorted by market cap, largest "
        "first. market_cap/pe_ratio are near-real-time (see as_of).",
    }
    if errors:
        result["errors"] = errors
    if not companies:
        result["error"] = "None of the requested tickers returned usable data."
    return result
