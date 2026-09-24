"""Structured chart data for a finished research report.

Built deterministically from market data (yfinance, no LLM calls) plus the
sentiment signals the planner lifts from the news specialist. Consumed by the
web report and the PDF renderer; persisted as ``report["visuals"]``.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from mcp_servers.market_data_mcp import market_data as md

log = logging.getLogger("arthaneeti.visuals")

_RETURN_WINDOWS = (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", None))

# (key, label, unit) - unit drives formatting on both the web and the PDF.
_COMPARISON_METRICS = (
    ("pe_ratio", "P/E (TTM)", "x"),
    ("forward_pe", "Forward P/E", "x"),
    ("roe", "Return on equity", "%"),
    ("operating_margin", "Operating margin", "%"),
    ("net_margin", "Net margin", "%"),
    ("dividend_yield_pct", "Dividend yield", "%"),
    ("debt_to_equity", "Debt to equity", "x"),
    ("return_1y", "1Y price return", "%"),
)


def _pct(fraction: Any) -> float | None:
    return round(fraction * 100, 2) if isinstance(fraction, (int, float)) else None


def _returns(series: list[dict]) -> dict[str, float | None]:
    closes = [p["close"] for p in series if isinstance(p.get("close"), (int, float))]
    out: dict[str, float | None] = {}
    if not closes:
        return out
    last = closes[-1]
    for label, days in _RETURN_WINDOWS:
        base = closes[0] if days is None or days >= len(closes) else closes[-days - 1]
        out[label] = round((last / base - 1) * 100, 2) if base else None
    return out


def _company_pack(ticker: str) -> dict:
    errors: list[str] = []

    def fetch(fn, *args):
        result = fn(*args)
        if not isinstance(result, dict) or "error" in result:
            errors.append(f"{fn.__name__}: {(result or {}).get('error', 'no data')}")
            return {}
        return result

    fundamentals = fetch(md.get_fundamentals, ticker)
    ratios = fetch(md.get_ratios, ticker)
    history = fetch(md.get_price_history, ticker, "1y")
    trends = fetch(md.get_financial_trends, ticker)

    series = [
        {"date": row["date"], "close": row["close"], "volume": row.get("volume")}
        for row in history.get("history") or []
        if isinstance(row.get("close"), (int, float))
    ]
    years = trends.get("years") or []
    latest_net_margin = years[-1].get("net_margin") if years else None

    kpis = {
        "price": fundamentals.get("current_price"),
        "market_cap": fundamentals.get("market_cap"),
        "pe_ratio": fundamentals.get("pe_ratio"),
        "forward_pe": fundamentals.get("forward_pe"),
        "eps_ttm": fundamentals.get("eps_ttm"),
        "dividend_yield_pct": fundamentals.get("dividend_yield_pct"),
        "week52_high": fundamentals.get("fifty_two_week_high"),
        "week52_low": fundamentals.get("fifty_two_week_low"),
        "roe": _pct(ratios.get("roe")),
        "roa": _pct(ratios.get("roa")),
        "debt_to_equity": round(ratios["debt_to_equity"] / 100, 2)
        if isinstance(ratios.get("debt_to_equity"), (int, float)) else None,
        "current_ratio": ratios.get("current_ratio"),
    }

    return {
        "ticker": md.normalize_ticker(ticker),
        "name": fundamentals.get("name") or history.get("name"),
        "sector": fundamentals.get("sector"),
        "industry": fundamentals.get("industry"),
        "currency": fundamentals.get("currency") or history.get("currency") or "INR",
        "kpis": kpis,
        "price_history": series,
        "returns": _returns(series),
        "financials": [
            {
                "fiscal_year": y["period_end"][:4],
                "revenue": y.get("revenue"),
                "net_income": y.get("net_income"),
                "operating_margin": _pct(y.get("operating_margin")),
                "net_margin": _pct(y.get("net_margin")),
            }
            for y in years
        ],
        "margins": {
            "gross": _pct(ratios.get("gross_margin")),
            "ebitda": _pct(ratios.get("ebitda_margin")),
            "operating": _pct(ratios.get("operating_margin")),
            "net": _pct(ratios.get("profit_margin")) or _pct(latest_net_margin),
        },
        "errors": errors,
    }


def _relative_performance(companies: dict[str, dict]) -> list[dict]:
    """Price series rebased to 100 on the first date every company traded."""
    by_ticker = {
        t: {p["date"]: p["close"] for p in c.get("price_history") or []}
        for t, c in companies.items()
    }
    if not all(by_ticker.values()):
        return []
    common = sorted(set.intersection(*(set(s) for s in by_ticker.values())))
    if not common:
        return []
    base = {t: s[common[0]] for t, s in by_ticker.items()}
    return [
        {"date": d, **{t: round(by_ticker[t][d] / base[t] * 100, 2) for t in by_ticker if base[t]}}
        for d in common
    ]


def _comparison(companies: dict[str, dict]) -> dict:
    def value(pack: dict, key: str) -> Any:
        if key == "return_1y":
            return (pack.get("returns") or {}).get("1Y")
        if key in ("operating_margin", "net_margin"):
            return (pack.get("margins") or {}).get(key.split("_")[0])
        return (pack.get("kpis") or {}).get(key)

    metrics = []
    for key, label, unit in _COMPARISON_METRICS:
        values = {t: value(p, key) for t, p in companies.items()}
        if any(isinstance(v, (int, float)) for v in values.values()):
            metrics.append({"key": key, "label": label, "unit": unit, "values": values})
    return {"relative_performance": _relative_performance(companies), "metrics": metrics}


def build(report: dict) -> dict | None:
    """Chart data for every company in ``report``, or None if there are none."""
    tickers = [t for t, r in (report.get("reports") or {}).items() if isinstance(r, dict)]
    if not tickers:
        return None

    with ThreadPoolExecutor(max_workers=min(4, len(tickers))) as pool:
        packs = list(pool.map(_company_pack, tickers))

    signals = report.get("signals") or {}
    companies = {}
    for ticker, pack in zip(tickers, packs):
        sentiment = (signals.get(ticker) or {}).get("sentiment")
        if sentiment:
            pack["sentiment"] = sentiment
        companies[ticker] = pack

    visuals: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "companies": companies,
    }
    if len(companies) > 1:
        visuals["comparison"] = _comparison(companies)
    return visuals
