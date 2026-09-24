"""filings-rag-mcp retrieval against the live pgvector corpus and Gemini embeddings.

Requires the RELIANCE, TCS and M&M filings to be ingested
(``python -m mcp_servers.filings_rag_mcp.ingest``); tickers that are not are skipped.
"""

from __future__ import annotations

import os

import pytest

from mcp_servers.filings_rag_mcp import db, retrieval as rt

pytestmark = [pytest.mark.live, pytest.mark.pace(float(os.environ.get("GEMINI_TEST_SPACING_S", "1.5")))]

REQUESTED_TICKERS = ["RELIANCE", "TCS", "M&M"]
SEARCH_QUERIES = [
    "what was the revenue growth this year and what drove it",
    "key risks and risk factors disclosed",
    "capital expenditure plans and investments",
]
STATEMENTS = ["income_statement", "balance_sheet", "cash_flow"]
YOY_CASES = [("RELIANCE", "revenue"), ("TCS", "net profit"), ("M&M", "EBITDA")]


@pytest.fixture(scope="module")
def ingested() -> set[str]:
    return set(db.available_tickers())


def _require(ticker: str, ingested: set[str]) -> None:
    if ticker not in ingested:
        pytest.skip(f"{ticker} is not ingested; run: python -m mcp_servers.filings_rag_mcp.ingest --only {ticker}")


def test_requested_tickers_are_ingested(ingested: set[str]) -> None:
    summary = db.corpus_summary()
    in_corpus = {row["ticker"] for row in summary["by_ticker"]}
    present = [t for t in REQUESTED_TICKERS if t in ingested]
    assert present, "none of the requested tickers are ingested"
    assert set(present) <= in_corpus


@pytest.mark.parametrize("ticker", REQUESTED_TICKERS)
@pytest.mark.parametrize("query", SEARCH_QUERIES)
def test_search_filing_returns_relevant_hits(ticker: str, query: str, ingested: set[str]) -> None:
    _require(ticker, ingested)
    res = rt.search_filing(query, ticker, top_k=4)
    assert "error" not in res, res.get("error")
    assert res["count"] > 0
    assert res["results"][0]["similarity"] > 0.5


@pytest.mark.parametrize("ticker", REQUESTED_TICKERS)
@pytest.mark.parametrize("statement", STATEMENTS)
def test_statement_section_lands_on_plausible_page(ticker: str, statement: str, ingested: set[str]) -> None:
    _require(ticker, ingested)
    res = rt.get_financial_statement_section(ticker, statement)
    assert "error" not in res, res.get("error")
    assert res["count"] > 0
    # Financial statements sit well past the front matter of an annual report.
    assert res["pages_returned"] and max(res["pages_returned"]) > 40, res["pages_returned"]


@pytest.mark.parametrize(("ticker", "metric"), YOY_CASES)
def test_yoy_carries_single_filing_limitation(ticker: str, metric: str, ingested: set[str]) -> None:
    _require(ticker, ingested)
    res = rt.compare_yoy_metrics(ticker, metric)
    assert "error" not in res, res.get("error")
    assert res["count"] > 0
    assert "limitation" in res


@pytest.mark.pace(0)
def test_invalid_inputs_return_errors() -> None:
    assert "error" in rt.search_filing("", "RELIANCE")
    assert "error" in rt.search_filing("revenue", "")
    unknown = rt.search_filing("revenue", "NOTATICKER")
    assert "error" in unknown and "ingested" in unknown["error"].lower()
    bad_statement = rt.get_financial_statement_section("RELIANCE", "cash flow of unicorns")
    assert "error" in bad_statement and "supported" in bad_statement["error"].lower()
