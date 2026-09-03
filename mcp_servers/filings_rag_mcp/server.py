"""filings-rag-mcp - MCP server for retrieval over Indian annual-report filings.

Transport: stdio. Run directly with:

    python mcp_servers/filings_rag_mcp/server.py

Prerequisite: run the ingestion pipeline first (once):

    python -m mcp_servers.filings_rag_mcp.ingest

Needs DATABASE_URL (Supabase Postgres + pgvector) and GEMINI_API_KEY, both from
the project .env. The Gemini embedding quota is SHARED with research-mcp.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Ensure the repo root is importable so the package's relative imports resolve,
# whether this file is run as a script or as `python -m ...`.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp_servers.filings_rag_mcp import retrieval as rt  # noqa: E402

server = MCPServer(
    name="filings-rag-mcp",
    version="0.1.0",
    instructions=(
        "Retrieval-augmented access to the actual annual-report PDFs of ~10 large "
        "Indian companies (one filing each, FY2024-25; TCS is FY2025-26). Use these "
        "tools to ground answers about a company's own disclosures - strategy, "
        "risks, capex, segment performance, financial statements - in cited pages "
        "of its report, rather than model memory. Pass an NSE-style ticker "
        "(RELIANCE, TCS, M&M). Retrieval is semantic over PDF-extracted text: "
        "tables are often column-flattened (flagged may_contain_tabular_data) and "
        "only ONE year's filing exists per company. Every tool returns an 'error' "
        "string instead of raising."
    ),
)


@server.tool()
def search_filing(query: str, ticker: str, top_k: int = 5) -> dict[str, Any]:
    """Semantic search within ONE company's annual report.

    Use for any grounded question about what a company disclosed in its own
    filing: "key risks", "capital expenditure plans", "revenue growth drivers",
    "board composition", "ESG commitments", etc.

    Args:
        ticker: NSE-style symbol - RELIANCE, TCS, M&M, HDFCBANK, ICICIBANK, INFY,
            LT, BHARTIARTL, HINDUNILVR, SUNPHARMA. (".NS"/".BO" suffixes are
            stripped.)
        query: A natural-language question or phrase.
        top_k: Number of chunks to return, 1-20 (clamped). Default 5.

    Returns:
        dict with ticker, company, query, count, and "results": a list of
        {page_number, similarity (cosine, 0-1), may_contain_tabular_data,
        numeric_density, fiscal_year, text} ordered best-first. Cite page_number.
        On failure (bad ticker, not ingested, embedding/DB error):
        {"error": "<message>"}.
    """
    return rt.search_filing(query, ticker, top_k)


@server.tool()
def get_financial_statement_section(ticker: str, statement_type: str) -> dict[str, Any]:
    """Retrieve a named financial statement from a company's filing.

    A more targeted version of search_filing for the primary statements.

    Args:
        ticker: NSE-style symbol (see search_filing).
        statement_type: one of "balance_sheet", "income_statement", "cash_flow",
            "equity_changes". Aliases accepted: "income statement", "profit and
            loss", "p&l", "balance sheet", "cash flow", "changes in equity".

    Returns:
        dict with statement_type, pages_returned, count, and "results": chunks
        (each with page_number, similarity, may_contain_tabular_data,
        matched_header_keyword, text). This is search-based, not a parsed
        statement - numbers may be column-flattened and standalone vs consolidated
        versions can mix. On failure: {"error": "<message>"}.
    """
    return rt.get_financial_statement_section(ticker, statement_type)


@server.tool()
def compare_yoy_metrics(ticker: str, metric: str) -> dict[str, Any]:
    """Year-over-year figures for a metric, as reported WITHIN the single filing.

    IMPORTANT SCOPE: ArthaNeeti holds one annual report per company, so this is
    NOT a comparison across separate years' filings. It surfaces the filing's own
    year-on-year disclosure for the metric - the current + prior-year columns in
    the statements and the MD&A/Board's-Report commentary ("Revenue grew X% Y-o-Y").
    For a real multi-year trend, prior years' reports would need to be ingested
    (out of scope for v1).

    Args:
        ticker: NSE-style symbol (see search_filing).
        metric: e.g. "revenue", "EBITDA", "net profit", "capex", "EPS",
            "operating margin".

    Returns:
        dict with metric, fiscal_year, "basis" and "limitation" strings stating
        the single-filing scope, count, and "results": chunks (each with
        page_number, similarity, may_contain_tabular_data, matched_yoy_phrase,
        text). On failure: {"error": "<message>"}.
    """
    return rt.compare_yoy_metrics(ticker, metric)


if __name__ == "__main__":
    server.run("stdio")
