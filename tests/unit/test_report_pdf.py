"""PDF export (app/report_pdf.py) rendered from synthetic reports, offline."""

from __future__ import annotations

import io

import pypdf
import pytest

from app.report_pdf import render_report_pdf


def _history(start: float, n: int = 60) -> list[dict]:
    return [{"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "close": start + (i % 7) * 3 - i * 0.5} for i in range(n)]


def _pack(ticker: str, name: str, price: float) -> dict:
    return {
        "ticker": f"{ticker}.NS",
        "name": name,
        "sector": "Technology",
        "industry": "Information Technology Services",
        "currency": "INR",
        "kpis": {"price": price, "market_cap": 7.5e12, "pe_ratio": 15.2, "forward_pe": 12.8, "eps_ttm": 136.6,
                 "dividend_yield_pct": 3.1, "week52_high": price * 1.5, "week52_low": price * 0.9, "roe": 47.7,
                 "roa": 24.5, "debt_to_equity": 0.1, "current_ratio": 2.3},
        "price_history": _history(price),
        "returns": {"1M": -8.0, "3M": 0.1, "6M": -10.9, "1Y": -28.4},
        "financials": [{"fiscal_year": str(y), "revenue": 2.2e12 + i * 1e11, "net_income": 4.2e11 + i * 1e10,
                        "operating_margin": 24 + i * 0.2, "net_margin": 18.7 + i * 0.1} for i, y in enumerate(range(2023, 2027))],
        "margins": {"gross": 40.4, "ebitda": 26.1, "operating": 24.0, "net": 18.1},
        "errors": [],
        "sentiment": {"breakdown": {"positive": 4, "neutral": 6, "negative": 3}, "as_of": "2026-09-21T10:00:00+00:00",
                      "articles": [{"title": "Deal win announced", "published_date": "2026-09-18", "label": "positive"}]},
    }


def _company_report(name: str) -> dict:
    return {
        "companies": [name],
        "executive_summary": "Strong profitability with a weaker share price.\n\nValuation has de-rated.",
        "sections": {
            "market_data": "Trades at 15x trailing earnings.",
            "news_sentiment": "Not available - news_sentiment agent errored: LLM quota: QuotaExceededError",
            "filings": "The annual report flags litigation risk (p.62).",
        },
        "sources_by_claim": {
            "Share price fell 2% in September.": {"sources": ["news_sentiment (univest.in", "16 Sep 2026)"], "caveat": None},
            "ROE is 47.7%.": {"sources": ["market_data (as_of 2026-09-21T08:30:58+00:00)"], "caveat": "Trailing figure."},
        },
        "conflicts_flagged": [{"topic": "Fundamentals vs price", "specialist_a": "market_data", "position_a": "Strong.",
                               "specialist_b": "news_sentiment (absent)", "position_b": "Unknown.", "assessment": "A coverage gap."}],
        "overall_caveats": ["news_sentiment specialist failed due to LLM quota limit."],
        "missing_data": [],
    }


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _report(mode: str) -> dict:
    tickers = {"single": ["TCS"], "compare": ["TCS", "INFY"], "portfolio": ["TCS", "INFY"]}[mode]
    names = {"TCS": "Tata Consultancy Services Limited", "INFY": "Infosys Limited"}
    report = {
        "mode": "single" if mode == "single" else "multi",
        "query": "Research TCS",
        "reports": {t: _company_report(names[t]) for t in tickers},
        "visuals": {"as_of": "2026-09-24T07:00:00+00:00",
                    "companies": {t: _pack(t, names[t], 2000 - 900 * i) for i, t in enumerate(tickers)}},
        "comparison": None,
        "portfolio": None,
    }
    if len(tickers) > 1:
        report["visuals"]["comparison"] = {
            "relative_performance": [{"date": r["date"], "TCS": 100 - i * 0.3, "INFY": 100 - i * 0.2}
                                     for i, r in enumerate(_history(1))],
            "metrics": [{"key": "pe_ratio", "label": "P/E (TTM)", "unit": "x", "values": {"TCS": 15.3, "INFY": 13.2}},
                        {"key": "return_1y", "label": "1Y price return", "unit": "%", "values": {"TCS": -28.3, "INFY": 4.0}}],
        }
    if mode == "compare":
        report["comparison"] = {"verdict": "No clear winner.", "caveats": ["Single-year filings."],
                                "dimensions": [{"dimension": "Valuation", "assessment": "Infosys is cheaper.", "edge": "INFY"}]}
    if mode == "portfolio":
        report["portfolio"] = {
            "narrative": "Concentrated in technology.",
            "holdings": [{"ticker": t, "name": names[t], "sector": "Technology", "weight_pct": 50.0,
                          "pe_ratio": 15.0, "roe": 40.0, "dividend_yield_pct": 3.0} for t in tickers],
            "sector_allocation_pct": {"Technology": 100.0},
            "weighted_pe_ratio": 15.0, "weighted_roe": 40.0, "weighted_dividend_yield_pct": 3.0,
            "diversification": "Single sector.", "concentration_risks": ["All holdings share one sector."], "caveats": [],
        }
    return report


@pytest.mark.parametrize("mode", ["single", "compare", "portfolio"])
def test_renders_every_report_shape(mode: str) -> None:
    pdf = render_report_pdf(_report(mode))
    assert pdf.startswith(b"%PDF")
    text = _text(pdf)
    assert "Tata Consultancy Services Limited" in text
    assert "Page 1 of" in text
    assert "About this report" in text


def test_reader_facing_text_has_no_internal_names() -> None:
    text = _text(render_report_pdf(_report("compare")))
    for leaked in ("news_sentiment", "market_data", "QuotaExceededError", "LLM quota", "as_of", "T08:30:58"):
        assert leaked not in text, leaked
    assert "univest.in, 16 Sep 2026" in text
    assert "This source could not be retrieved during this run." in text


def test_rupee_and_typographic_glyphs_survive() -> None:
    text = _text(render_report_pdf(_report("single")))
    assert "₹2,000.00" in text
    assert "–" in text


def test_report_without_company_or_visuals() -> None:
    pdf = render_report_pdf({"mode": "none", "query": "tell me about abc", "note": "See routing_trace.", "reports": {}})
    text = _text(pdf)
    assert "No NSE-listed company could be identified" in text
    assert "routing_trace" not in text


def test_report_without_visuals_still_renders() -> None:
    report = _report("single")
    report.pop("visuals")
    assert "Analysis" in _text(render_report_pdf(report))
