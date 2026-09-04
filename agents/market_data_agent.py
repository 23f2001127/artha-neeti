"""Market Data Agent - a standalone LangGraph specialist for Indian-equity market data.

What it is
----------
Given a natural-language question about a listed company's market data, this agent
reasons about which of ``market-data-mcp``'s 4 tools to call (often more than one -
"how is X valued" needs fundamentals *and* ratios), calls them, and returns a
structured result a future Synthesis Agent can consume, plus a human summary.

The shared agent machinery (MCP stdio client, Groq-backed ``create_react_agent``
through ``shared/llm_rate_limiter.py``, model-fallback chain, trace extraction)
lives in ``agents/_base.py``. This module supplies only the system prompt, the
synthesis step, and the provenance extractor.

- **MCP over stdio.** Spawns ``mcp_servers/market_data_mcp/server.py`` as a
  subprocess and talks the MCP protocol - it does NOT import ``market_data.py``.
- **Provenance preserved.** ``as_of`` / ``fiscal_year`` / ``roe_source`` /
  ``last_fiscal_year_end`` from the MCP responses are lifted into a top-level
  ``provenance`` block and the full output kept in ``raw_data``.

Standalone use
--------------
    from agents.market_data_agent import run_sync
    result = run_sync("how is TCS valued compared to its fundamentals")
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from pydantic import BaseModel, Field

from agents import _base
from agents._base import DEFAULT_MODEL

MARKET_DATA_SERVER = str(_base.REPO_ROOT / "mcp_servers" / "market_data_mcp" / "server.py")


# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = """You are the Market Data Agent for ArthaNeeti, a specialist that \
answers questions about the market data of companies listed on Indian exchanges \
(NSE/BSE), using ONLY the tools provided.

Tickers: pass NSE-style symbols with the .NS suffix (RELIANCE.NS, TCS.NS, M&M.NS, \
INFY.NS, HDFCBANK.NS, ...). Resolve company names to tickers yourself.

Tool selection - call as many as the question needs, then stop:
- get_price_history: recent OHLCV price action / returns / volatility.
- get_fundamentals: profile + headline valuation (market cap, P/E, EPS, dividend \
yield, 52-week range).
- get_ratios: profitability / leverage / liquidity ratios (ROE, ROA, debt/equity, \
margins, current ratio).
- get_peer_comparison: ONE call with a list of tickers for any "compare X, Y, Z" \
question - do not call the single-company tools per peer.

A "how is <company> valued / valued vs fundamentals" question needs BOTH \
get_fundamentals AND get_ratios. A bare "price" question needs only \
get_fundamentals (it carries current_price) or get_price_history.

Every tool result carries provenance (as_of, fiscal_year, roe_source, \
last_fiscal_year_end, computed/missing lists). Never contradict a tool result or \
invent numbers. When you have enough, give a short factual answer."""

_SYNTH_INSTRUCTIONS = """You are turning raw market-data-mcp tool output into a \
structured result for a downstream Synthesis Agent.

Rules:
- Use ONLY numbers present in the tool output. Do not estimate or recall.
- Each finding is one self-contained sentence. Include the figure AND its \
provenance where the data provides it: e.g. "TCS ROE is 47.7% (source: yfinance, \
FY ...)", "market cap and price are as of <as_of>". If a value is under a \
"missing" list or is null, say it was not available.
- For peer comparisons, make findings that actually compare (rank, relative \
size), not just per-company facts.
- ticker/company: the primary subject. For a multi-company comparison use the \
first/largest as primary and name the others in the summary.
- summary: 2-4 sentences, plain English, for a human."""


class _MarketDataSynthesis(BaseModel):
    ticker: str = Field(description="primary NSE ticker, e.g. RELIANCE.NS")
    company: str = Field(description="primary company display name")
    findings: list[str] = Field(description="grounded, provenance-carrying finding sentences")
    summary: str = Field(description="2-4 sentence human-readable summary")


_PROVENANCE_KEYS = (
    "as_of", "fiscal_year", "last_fiscal_year_end", "roe_source", "computed",
    "missing", "notes", "disclaimer",
)


async def _synthesize(model, query: str, call_log: list[dict]) -> dict:
    structured = model.with_structured_output(_MarketDataSynthesis)
    payload = json.dumps(
        [{"tool": c["tool"], "args": c["args"], "result": c["result"]} for c in call_log],
        default=str, indent=2,
    )
    msgs = [
        _base.SystemMessage(_SYNTH_INSTRUCTIONS),
        _base.HumanMessage(f"USER QUESTION:\n{query}\n\nTOOL OUTPUT:\n{payload}"),
    ]
    result = await structured.ainvoke(msgs)
    if isinstance(result, dict):
        result = _MarketDataSynthesis(**result)
    return result.model_dump()


def _collect_provenance(call_log: list[dict]) -> dict:
    prov: dict[str, Any] = {}
    for entry in call_log:
        res = entry["result"]
        if not isinstance(res, dict):
            continue
        block = {k: res[k] for k in _PROVENANCE_KEYS if k in res}
        if isinstance(res.get("companies"), list):
            block["per_company"] = [
                {"ticker": c.get("ticker"), "roe_source": c.get("roe_source"),
                 "fiscal_year": c.get("fiscal_year")}
                for c in res["companies"]
            ]
        if block:
            prov[entry["tool"]] = block
    return prov


# --------------------------------------------------------------------------- #
async def run(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Answer one market-data question. Returns the structured agent result."""
    return await _base.run_agent(
        server_path=MARKET_DATA_SERVER,
        system_prompt=_SYSTEM_PROMPT,
        query=query,
        synthesize=_synthesize,
        collect_provenance=_collect_provenance,
        model_name=model_name,
    )


def run_sync(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Blocking wrapper around :func:`run` for scripts / the future Planner node."""
    return asyncio.run(run(query, model_name=model_name))


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "what is Reliance's current stock price?"
    print(json.dumps(run_sync(q), indent=2, default=str))
