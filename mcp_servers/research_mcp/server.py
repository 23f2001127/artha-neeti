"""research-mcp - MCP server for news, sentiment, and corporate announcements.

Transport: stdio (for now). Run directly with:

    python mcp_servers/research_mcp/server.py

or as a module:

    python -m mcp_servers.research_mcp.server

Needs TAVILY_API_KEY and GEMINI_API_KEY (read from the project .env or the real
environment). Ticker arguments accept NSE/BSE symbols or plain company names;
a small built-in map turns common tickers (RELIANCE, TCS, M&M, ...) into full
names for better search queries.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Make ``import research`` work whether this file is run as a script or a module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research as rz  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer(
    name="research-mcp",
    version="0.1.0",
    instructions=(
        "News, market sentiment, and corporate-announcement signal for companies "
        "listed on Indian exchanges. Backed by Tavily web/news search and a Gemini "
        "LLM for sentiment. Use these tools for 'what is the recent news / how is "
        "sentiment / what has the company announced' questions. Pass a ticker "
        "(RELIANCE.NS) or a company name. Sentiment and corporate-announcement "
        "results are approximations - read the 'note' / 'disclaimer' fields and "
        "pass them on rather than presenting them as authoritative. Every tool "
        "returns an 'error' string instead of raising when a key is missing, a "
        "rate limit is hit, or a service fails."
    ),
)


@server.tool()
def search_news(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search recent news for a company or topic (general-purpose news search).

    Use this for open-ended queries ("Adani Group news", "India IT sector layoffs",
    "RBI rate decision reaction"). For news about one specific company prefer
    get_company_news, which scopes and windows the query for you.

    Args:
        query: Free-text search string.
        max_results: How many articles to return, 1-20 (clamped). Default 10.

    Returns:
        dict with query, count, "results" (a list of {title, url, published_date,
        source_score, snippet}), and as_of. "note" is set when there were zero
        results (which is not an error). On failure: {"error": "<message>"}.
    """
    return rz.search_news(query, max_results)


@server.tool()
def get_company_news(ticker_or_name: str, days_back: int = 30) -> dict[str, Any]:
    """Recent news about ONE company over a trailing window.

    Builds a company-scoped query and passes it to news search. Use this for
    "what's the latest on <company>" questions.

    Args:
        ticker_or_name: NSE/BSE symbol (e.g. "TCS.NS", "M&M.NS") or a company name
            ("Tata Consultancy Services"). Common tickers are mapped to full names.
        days_back: Trailing window in days, 1-365 (clamped). Default 30.

    Returns:
        dict with input, company (the resolved name),
        name_resolved_from_ticker_map, days_back, query, count, on_company_count,
        "results" (list of {title, url, published_date, source_score, snippet,
        mentions_company}), and as_of. `mentions_company` flags whether the item
        names the company (vs a group company / peer) - results are flagged, not
        dropped. "note" summarises the on-company ratio. On failure:
        {"error": "<message>"}.
    """
    return rz.get_company_news(ticker_or_name, days_back)


@server.tool()
def get_sentiment(text_or_ticker: str) -> dict[str, Any]:
    """Classify financial-news sentiment with the Gemini LLM. Dual-mode.

    - Pass a **ticker or short company name** ("RELIANCE.NS", "Infosys") and the
      tool fetches ~10 recent articles and returns an AGGREGATE assessment
      (overall label/score/rationale, a positive/neutral/negative breakdown, and a
      per-article label). Use this for "how is sentiment on <company>".
    - Pass a **longer piece of text** (a headline, an analyst quote, an earnings
      commentary paragraph) and the tool scores THAT text directly. Use this to
      judge a specific statement you already have.

    The tool decides which mode by the shape of the input (short & punctuation-free
    -> company; otherwise -> text).

    Args:
        text_or_ticker: A ticker, a company name, or a passage of text.

    Returns:
        Aggregate mode: dict with mode="aggregate", company, article_count,
        on_company_count, "overall" {label, score, rationale}, "breakdown" (all
        articles), "breakdown_on_company" (only articles naming the company),
        "articles" (each with mentions_company + label + score), model, as_of.
        Off-entity articles are flagged to the model so they do not drive the
        overall label. Text mode: dict with mode="text", label, score, rationale,
        model, as_of. label is one of positive/neutral/negative; score is the
        model's self-reported confidence (0-1), NOT a calibrated probability. On
        failure: {"error": "<message>"}.
    """
    return rz.get_sentiment(text_or_ticker)


@server.tool()
def get_corporate_announcements(ticker: str, days_back: int = 30) -> dict[str, Any]:
    """Recent corporate-announcement-style news for a company (results, dividends,
    board meetings, buybacks, M&A, investor presentations, exchange filings).

    IMPORTANT: this is a Tavily news search, NOT a feed from the NSE/BSE official
    corporate-announcements system. Each result is flagged `mentions_company` (a
    company alias appears in the text) and `matched_keywords`; `likely_announcement`
    is true only when both hold, and those sort first. Prefer the
    `likely_announcement` items; the tail contains peer/group-company noise. The
    response carries a "disclaimer" field; pass it along.

    Args:
        ticker: NSE/BSE symbol or company name.
        days_back: Trailing window in days, 1-365 (clamped). Default 30.

    Returns:
        dict with input, company, days_back, query, count, likely_announcement_count,
        on_company_count, "announcements" (list of {title, url, published_date,
        source_score, snippet, mentions_company, matched_keywords,
        likely_announcement}), as_of, and "disclaimer". "note" is set when there
        were zero results. On failure: {"error": "<message>"}.
    """
    return rz.get_corporate_announcements(ticker, days_back)


if __name__ == "__main__":
    server.run("stdio")
