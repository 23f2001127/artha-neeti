"""Market Data Agent - a standalone LangGraph specialist for Indian-equity market data.

What it is
----------
Given a natural-language question about a listed company's market data, this agent
reasons about which of ``market-data-mcp``'s 4 tools to call (often more than one -
"how is X valued" needs fundamentals *and* ratios), calls them, and returns a
structured result a future Synthesis Agent can consume, plus a human summary.

How it's wired (deliberately, per the project's architecture rules)
------------------------------------------------------------------
- **MCP over stdio.** It spawns ``mcp_servers/market_data_mcp/server.py`` as a
  subprocess and talks to it with the MCP client protocol - it does NOT import
  ``market_data.py``'s functions. That's the point of the MCP layer; the Planner
  will connect the same way.
- **Groq for reasoning, through the shared limiter.** The ReAct tool-selection
  loop and the final synthesis call run on Groq (`langchain-groq` / `ChatGroq`),
  chosen because Gemini's free-tier *generate* quota (~20/day/model) can't sustain
  multiple agents each burning several calls per query. Every LLM call still
  clears ``shared/llm_rate_limiter.py`` (a ``groq:<model>`` bucket) - nothing here
  calls an LLM outside the shared limiter's awareness. See ``agents/README.md``
  for why Gemini stays for sentiment (research-mcp) and embeddings (filings-rag).
- **Provenance preserved.** ``as_of`` / ``fiscal_year`` / ``roe_source`` /
  ``last_fiscal_year_end`` from the MCP responses are lifted into a top-level
  ``provenance`` block and the full tool output is kept in ``raw_data`` - the
  agent never silently drops that context.

Standalone use
--------------
    from agents.market_data_agent import run_sync
    result = run_sync("how is TCS valued compared to its fundamentals")
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env", override=False)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402
from langchain_groq import ChatGroq  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from mcp.client import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from shared import llm_rate_limiter as rl  # noqa: E402

MARKET_DATA_SERVER = str(_REPO_ROOT / "mcp_servers" / "market_data_mcp" / "server.py")

# Groq reasoning models, primary + fallbacks. Each has its own free-tier bucket
# (~1,000 req/day, ~8k tokens/min - the token cap binds), so the fallback chain
# multiplies headroom. llama-3.3-70b was retired on Groq; gpt-oss-120b is the
# current large general reasoner. GROQ_AGENT_MODEL overrides the primary.
DEFAULT_MODEL = os.environ.get("GROQ_AGENT_MODEL", "openai/gpt-oss-120b")
_FALLBACK_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-20b")
_RECURSION_LIMIT = 14  # tool-selection loop: 4 tools, a couple of retries of headroom


class MarketDataAgentError(RuntimeError):
    pass


def _flatten_exc(exc: BaseException) -> list[BaseException]:
    """Recursively unwrap ExceptionGroup / __cause__ into a flat leaf list."""
    out: list[BaseException] = []
    stack = [exc]
    while stack:
        e = stack.pop()
        subs = getattr(e, "exceptions", None)
        if subs:
            stack.extend(subs)
        else:
            out.append(e)
            if e.__cause__ is not None and e.__cause__ not in out:
                stack.append(e.__cause__)
    return out


# --------------------------------------------------------------------------- #
# Groq chat model, rate-limited through the shared cross-process limiter
# --------------------------------------------------------------------------- #
def _estimate_tokens(messages: list) -> int:
    chars = 0
    for m in messages:
        content = getattr(m, "content", m)
        chars += len(content if isinstance(content, str) else str(content))
    return chars // 4 + 800  # + output allowance


def _is_rate_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "resource_exhausted" in text
        or " 429" in text
        or "429" in text
        or "rate_limit" in text
        or "rate limit" in text
        or "quota" in text
    )


class _RateLimitedChatGroq(ChatGroq):
    """ChatGroq that clears shared/llm_rate_limiter before every call and rotates
    through a model-fallback chain when a model's shared budget is spent or it
    429s. One object, so it drops straight into create_react_agent.

    The candidate chain is stashed via object.__setattr__ (pydantic ignores names
    it doesn't declare as fields); ``model_name`` is swapped in place per attempt.
    """

    def _candidates(self) -> list[str]:
        return list(getattr(self, "_rl_chain", None) or [self.model_name])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        est = _estimate_tokens(messages)
        errs: list[str] = []
        original = self.model_name
        for cand in self._candidates():
            bucket = f"groq:{cand}"
            try:
                rid = rl.acquire(est, bucket, timeout=120.0)
            except rl.QuotaExceededError:
                errs.append(f"{cand}: shared budget spent")
                continue
            object.__setattr__(self, "model_name", cand)
            try:
                return super()._generate(messages, stop, run_manager, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                rl.refund(rid, bucket)
                if _is_rate_error(exc):
                    errs.append(f"{cand}: 429")
                    continue
                object.__setattr__(self, "model_name", original)
                raise
            finally:
                object.__setattr__(self, "model_name", original)
        raise rl.QuotaExceededError(
            "all candidate Groq models are rate/quota limited: " + " | ".join(errs)
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # the shared limiter is sync (time.sleep); keep it off the event loop
        est = _estimate_tokens(messages)
        errs: list[str] = []
        original = self.model_name
        for cand in self._candidates():
            bucket = f"groq:{cand}"
            try:
                rid = await asyncio.to_thread(
                    functools.partial(rl.acquire, est, bucket, timeout=120.0)
                )
            except rl.QuotaExceededError:
                errs.append(f"{cand}: shared budget spent")
                continue
            object.__setattr__(self, "model_name", cand)
            try:
                return await super()._agenerate(messages, stop, run_manager, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                rl.refund(rid, bucket)
                if _is_rate_error(exc):
                    errs.append(f"{cand}: 429")
                    continue
                object.__setattr__(self, "model_name", original)
                raise
            finally:
                object.__setattr__(self, "model_name", original)
        raise rl.QuotaExceededError(
            "all candidate Groq models are rate/quota limited: " + " | ".join(errs)
        )


def _make_model(model_name: str) -> _RateLimitedChatGroq:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise MarketDataAgentError(
            "GROQ_API_KEY is not set (checked the environment and the project .env)."
        )
    m = _RateLimitedChatGroq(
        model=model_name,
        temperature=0.0,
        max_retries=0,  # the shared limiter + rotation are the only retry authority
        groq_api_key=key,
    )
    chain = [model_name] + [x for x in _FALLBACK_MODELS if x != model_name]
    object.__setattr__(m, "_rl_chain", chain)
    return m


# --------------------------------------------------------------------------- #
# MCP tool bridge: market-data-mcp tools -> LangChain StructuredTools
# --------------------------------------------------------------------------- #
def _result_payload(res: Any) -> dict:
    sc = getattr(res, "structured_content", None)
    if sc is not None:
        return sc
    parts = []
    for block in getattr(res, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    joined = "\n".join(parts)
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, ValueError):
        return {"_text": joined}


async def _load_tools(client: Client, call_log: list[dict]) -> list[StructuredTool]:
    listing = await client.list_tools()
    tools: list[StructuredTool] = []
    for spec in listing.tools:
        name = spec.name

        def _factory(tool_name: str):
            async def _call(**kwargs) -> str:
                res = await client.call_tool(tool_name, kwargs)
                payload = _result_payload(res)
                call_log.append({"tool": tool_name, "args": kwargs, "result": payload})
                return json.dumps(payload, default=str)

            return _call

        tools.append(
            StructuredTool(
                name=name,
                description=(spec.description or "").strip(),
                args_schema=spec.input_schema,
                coroutine=_factory(name),
            )
        )
    return tools


# --------------------------------------------------------------------------- #
# prompts + structured synthesis
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


class _AgentSynthesis(BaseModel):
    ticker: str = Field(description="primary NSE ticker, e.g. RELIANCE.NS")
    company: str = Field(description="primary company display name")
    findings: list[str] = Field(description="grounded, provenance-carrying finding sentences")
    summary: str = Field(description="2-4 sentence human-readable summary")


async def _synthesize(model: _RateLimitedChatGroq, query: str, call_log: list[dict]) -> _AgentSynthesis:
    structured = model.with_structured_output(_AgentSynthesis)
    payload = json.dumps(
        [{"tool": c["tool"], "args": c["args"], "result": c["result"]} for c in call_log],
        default=str,
        indent=2,
    )
    msgs = [
        SystemMessage(_SYNTH_INSTRUCTIONS),
        HumanMessage(f"USER QUESTION:\n{query}\n\nTOOL OUTPUT:\n{payload}"),
    ]
    result = await structured.ainvoke(msgs)
    if isinstance(result, dict):
        result = _AgentSynthesis(**result)
    return result


# --------------------------------------------------------------------------- #
# trace + provenance extraction
# --------------------------------------------------------------------------- #
_PROVENANCE_KEYS = (
    "as_of", "fiscal_year", "last_fiscal_year_end", "roe_source", "computed",
    "missing", "notes", "disclaimer",
)


def _collect_provenance(call_log: list[dict]) -> dict:
    prov: dict[str, Any] = {}
    for entry in call_log:
        res = entry["result"]
        if not isinstance(res, dict):
            continue
        block = {k: res[k] for k in _PROVENANCE_KEYS if k in res}
        # peer comparison carries per-company roe_source / fiscal_year
        if isinstance(res.get("companies"), list):
            block["per_company"] = [
                {
                    "ticker": c.get("ticker"),
                    "roe_source": c.get("roe_source"),
                    "fiscal_year": c.get("fiscal_year"),
                }
                for c in res["companies"]
            ]
        if block:
            prov[entry["tool"]] = block
    return prov


def _msg_text(content: Any) -> str:
    """Gemini messages sometimes carry content as a list of blocks; flatten to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
        return " ".join(p for p in parts if p)
    return str(content or "")


def _extract_trace(messages: list) -> list[dict]:
    """Human-readable step list: each LLM tool decision and each tool result."""
    trace: list[dict] = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                trace.append(
                    {"step": "tool_call", "tool": tc["name"], "args": tc.get("args", {})}
                )
            text = _msg_text(m.content).strip()
            if not m.tool_calls and text:
                trace.append({"step": "agent_answer", "text": text})
        elif isinstance(m, ToolMessage):
            preview = _msg_text(m.content)
            trace.append(
                {"step": "tool_result", "tool": m.name, "chars": len(preview),
                 "preview": preview[:240]}
            )
    return trace


# --------------------------------------------------------------------------- #
# public entrypoints
# --------------------------------------------------------------------------- #
async def run(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Answer one market-data question. Returns the structured agent result."""
    if not query or not query.strip():
        return {"query": query, "error": "query is empty."}

    params = StdioServerParameters(command=sys.executable, args=[MARKET_DATA_SERVER])
    call_log: list[dict] = []
    try:
        async with Client(params) as client:
            tools = await _load_tools(client, call_log)
            model = _make_model(model_name)
            agent = create_react_agent(model, tools, prompt=_SYSTEM_PROMPT)
            state = await agent.ainvoke(
                {"messages": [HumanMessage(query)]},
                config={"recursion_limit": _RECURSION_LIMIT},
            )
            synthesis = await _synthesize(model, query, call_log)
            trace = _extract_trace(state["messages"])
    except BaseException as exc:  # noqa: BLE001 - unwrap anyio/MCP ExceptionGroups
        flat = _flatten_exc(exc)
        quota = next((e for e in flat if isinstance(e, rl.QuotaExceededError)), None)
        primary = quota or (flat[0] if flat else exc)
        return {
            "query": query,
            "error": ("Gemini quota: " if quota else "") + f"{type(primary).__name__}: {primary}",
            "tools_called": [c["tool"] for c in call_log],
            "partial_raw_data": {c["tool"]: c["result"] for c in call_log} or None,
        }

    return {
        "query": query,
        "ticker": synthesis.ticker,
        "company": synthesis.company,
        "findings": synthesis.findings,
        "summary": synthesis.summary,
        "tools_called": [c["tool"] for c in call_log],
        "tool_calls": [{"tool": c["tool"], "args": c["args"]} for c in call_log],
        "provenance": _collect_provenance(call_log),
        "raw_data": {c["tool"]: c["result"] for c in call_log},
        "reasoning_trace": trace,
        "model": model_name,
    }


def run_sync(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Blocking wrapper around :func:`run` for scripts / the future Planner node."""
    return asyncio.run(run(query, model_name=model_name))


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "what is Reliance's current stock price?"
    print(json.dumps(run_sync(q), indent=2, default=str))
