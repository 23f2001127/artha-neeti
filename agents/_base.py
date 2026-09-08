"""Shared machinery for ArthaNeeti's LangGraph specialist agents.

Every agent is the same shape: connect to one MCP server over stdio, expose its
tools to a Groq-backed ``create_react_agent``, then do one structured-output
synthesis call. This module holds the parts that don't change between agents -
the rate-limited chat model, the MCP->LangChain tool bridge, trace extraction,
and a ``run_agent`` driver. Each agent supplies only its system prompt, its
synthesis step, and a provenance extractor.

The Groq-for-reasoning choice, the shared cross-process limiter, and the model
fallback chain are documented in ``agents/README.md``.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv

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

REPO_ROOT = _REPO_ROOT

# Groq reasoning models, primary + fallbacks. Each has its own free-tier bucket
# (~1,000 req/day, ~8k tokens/min - the token cap binds), so the chain multiplies
# headroom. llama-3.3-70b was retired on Groq; gpt-oss-120b is the current large
# general reasoner. GROQ_AGENT_MODEL overrides the primary.
DEFAULT_MODEL = os.environ.get("GROQ_AGENT_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-20b")
RECURSION_LIMIT = 16


class AgentError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
def flatten_exc(exc: BaseException) -> list[BaseException]:
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


def estimate_tokens(messages: list) -> int:
    chars = 0
    for m in messages:
        content = getattr(m, "content", m)
        chars += len(content if isinstance(content, str) else str(content))
    return chars // 4 + 800  # + output allowance


def is_rate_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "resource_exhausted" in text
        or "429" in text
        or "rate_limit" in text
        or "rate limit" in text
        or "quota" in text
    )


def msg_text(content: Any) -> str:
    """Chat message content is sometimes a list of blocks; flatten to plain text."""
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


# --------------------------------------------------------------------------- #
# Groq chat model, rate-limited + model-rotating through the shared limiter
# --------------------------------------------------------------------------- #
class RateLimitedChatGroq(ChatGroq):
    """ChatGroq that clears shared/llm_rate_limiter before every call and rotates
    through a model-fallback chain when a model's shared budget is spent or it
    429s. One object, so it drops straight into create_react_agent.

    The candidate chain is stashed via object.__setattr__ (pydantic ignores names
    it doesn't declare as fields); ``model_name`` is swapped in place per attempt.
    """

    def _candidates(self) -> list[str]:
        return list(getattr(self, "_rl_chain", None) or [self.model_name])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        errs: list[str] = []
        original = self.model_name
        est = estimate_tokens(messages)
        for cand in self._candidates():
            bucket = f"groq:{cand}"
            try:
                rid = rl.acquire(est, bucket, timeout=150.0)
            except rl.QuotaExceededError:
                errs.append(f"{cand}: shared budget spent")
                continue
            object.__setattr__(self, "model_name", cand)
            try:
                return super()._generate(messages, stop, run_manager, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                rl.refund(rid, bucket)
                if is_rate_error(exc):
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
        errs: list[str] = []
        original = self.model_name
        est = estimate_tokens(messages)
        for cand in self._candidates():
            bucket = f"groq:{cand}"
            try:
                rid = await asyncio.to_thread(
                    functools.partial(rl.acquire, est, bucket, timeout=150.0)
                )
            except rl.QuotaExceededError:
                errs.append(f"{cand}: shared budget spent")
                continue
            object.__setattr__(self, "model_name", cand)
            try:
                return await super()._agenerate(messages, stop, run_manager, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                rl.refund(rid, bucket)
                if is_rate_error(exc):
                    errs.append(f"{cand}: 429")
                    continue
                object.__setattr__(self, "model_name", original)
                raise
            finally:
                object.__setattr__(self, "model_name", original)
        raise rl.QuotaExceededError(
            "all candidate Groq models are rate/quota limited: " + " | ".join(errs)
        )


def make_model(model_name: str = DEFAULT_MODEL) -> RateLimitedChatGroq:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise AgentError(
            "GROQ_API_KEY is not set (checked the environment and the project .env)."
        )
    m = RateLimitedChatGroq(
        model=model_name, temperature=0.0, max_retries=0, groq_api_key=key
    )
    object.__setattr__(m, "_rl_chain", [model_name] + [x for x in FALLBACK_MODELS if x != model_name])
    return m


# --------------------------------------------------------------------------- #
# MCP tool bridge
# --------------------------------------------------------------------------- #
def result_payload(res: Any) -> Any:
    sc = getattr(res, "structured_content", None)
    if sc is not None:
        return sc
    parts = [getattr(b, "text", "") for b in getattr(res, "content", []) or []]
    joined = "\n".join(p for p in parts if p)
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, ValueError):
        return {"_text": joined}


async def load_mcp_tools(
    client: Client,
    call_log: list[dict],
    to_llm: Callable[[str, Any], Any] | None = None,
) -> list[StructuredTool]:
    """Every MCP tool -> a LangChain StructuredTool; results appended to call_log.

    ``call_log`` always keeps the FULL tool payload (that's what feeds ``raw_data``
    and provenance). ``to_llm(tool_name, payload)``, if given, shrinks what the
    ReAct loop actually sees in message history - use it when a tool returns bulky
    text (RAG chunks) that would blow the reasoning model's token budget or confuse
    the smaller fallback models. Opt-in; agents that don't pass it are unchanged.
    """
    listing = await client.list_tools()
    tools: list[StructuredTool] = []
    for spec in listing.tools:
        def _factory(tool_name: str):
            async def _call(**kwargs) -> str:
                res = await client.call_tool(tool_name, kwargs)
                payload = result_payload(res)
                call_log.append({"tool": tool_name, "args": kwargs, "result": payload})
                shown = to_llm(tool_name, payload) if to_llm else payload
                return json.dumps(shown, default=str)

            return _call

        tools.append(
            StructuredTool(
                name=spec.name,
                description=(spec.description or "").strip(),
                args_schema=spec.input_schema,
                coroutine=_factory(spec.name),
            )
        )
    return tools


def extract_trace(messages: list) -> list[dict]:
    """Human-readable step list: each LLM tool decision and each tool result."""
    trace: list[dict] = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                trace.append({"step": "tool_call", "tool": tc["name"], "args": tc.get("args", {})})
            text = msg_text(m.content).strip()
            if not m.tool_calls and text:
                trace.append({"step": "agent_answer", "text": text})
        elif isinstance(m, ToolMessage):
            preview = msg_text(m.content)
            trace.append({"step": "tool_result", "tool": m.name,
                          "chars": len(preview), "preview": preview[:240]})
    return trace


# --------------------------------------------------------------------------- #
# the shared driver
# --------------------------------------------------------------------------- #
Synthesizer = Callable[[RateLimitedChatGroq, str, list[dict]], Awaitable[dict]]
ProvenanceFn = Callable[[list[dict]], dict]


async def run_agent(
    *,
    server_path: str,
    system_prompt: str,
    query: str,
    synthesize: Synthesizer,
    collect_provenance: ProvenanceFn,
    model_name: str = DEFAULT_MODEL,
    compact_tool_result: Callable[[str, Any], Any] | None = None,
    recursion_limit: int = RECURSION_LIMIT,
) -> dict:
    """Connect to one MCP server, run the ReAct loop + synthesis, return the
    standard agent result dict. Agent-specific bits are the three callables/strings.

    ``compact_tool_result(tool_name, payload)`` (optional): shrink what the ReAct
    loop sees per tool call. ``raw_data`` / provenance still get the full payload.
    """
    if not query or not query.strip():
        return {"query": query, "error": "query is empty."}

    params = StdioServerParameters(command=sys.executable, args=[server_path])
    call_log: list[dict] = []
    try:
        async with Client(params) as client:
            tools = await load_mcp_tools(client, call_log, to_llm=compact_tool_result)
            model = make_model(model_name)
            agent = create_react_agent(model, tools, prompt=system_prompt)
            state = await agent.ainvoke(
                {"messages": [HumanMessage(query)]},
                config={"recursion_limit": recursion_limit},
            )
            synth = await synthesize(model, query, call_log)
            trace = extract_trace(state["messages"])
    except BaseException as exc:  # noqa: BLE001 - unwrap anyio/MCP ExceptionGroups
        flat = flatten_exc(exc)
        quota = next((e for e in flat if isinstance(e, rl.QuotaExceededError)), None)
        primary = quota or (flat[0] if flat else exc)
        return {
            "query": query,
            "error": ("LLM quota: " if quota else "") + f"{type(primary).__name__}: {primary}",
            "tools_called": [c["tool"] for c in call_log],
            "partial_raw_data": {c["tool"]: c["result"] for c in call_log} or None,
        }

    return {
        "query": query,
        **synth,
        "tools_called": [c["tool"] for c in call_log],
        "tool_calls": [{"tool": c["tool"], "args": c["args"]} for c in call_log],
        "provenance": collect_provenance(call_log),
        "raw_data": {c["tool"]: c["result"] for c in call_log},
        "reasoning_trace": trace,
        "model": model_name,
    }
