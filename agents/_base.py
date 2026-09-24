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
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env", override=False)

from langchain_core.callbacks import AsyncCallbackHandler  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402
from langchain_groq import ChatGroq  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from mcp.client import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from shared import llm_rate_limiter as rl  # noqa: E402

REPO_ROOT = _REPO_ROOT

# Groq reasoning models, primary + fallbacks. gpt-oss-120b/qwen3.8-27b/
# gpt-oss-20b each carry 1000 req/day, 8k TPM (live-checked via response
# headers). llama-3.3-70b was retired on Groq; gpt-oss-120b is the current
# large general reasoner. gemma2-9b-it (the previous last rung) was itself
# decommissioned by Groq - confirmed live via a 400 "has been decommissioned"
# error, not just docs. Two replacements were tried and rejected/accepted by
# live-testing the actual ReAct tool-calling loop (not just a bare chat
# completion - every specialist agent needs real tool calling, and that's
# exactly what breaks silently if skipped):
#   - llama-3.1-8b-instant looked right from Groq's docs but 404's on this
#     account's real model list.
#   - allam-2-7b IS listed/active and answers a plain prompt fine, but hard-
#     fails every time on a tool-calling request ("`tool calling` is not
#     supported with this model") - worse than the dead model it would have
#     replaced, since it fails 100% of the time instead of only when reached
#     mid-decommission.
# openai/gpt-oss-safeguard-20b (a safety-policy-tuned gpt-oss-20b variant)
# is the one that actually works: real tool calling confirmed against
# get_peer_comparison, and a separate quota bucket from gpt-oss-20b (live-
# checked headers - same 1000 req/day, 8k TPM, but counted independently by
# model id). One structured-output schema slip was observed in 3 live test
# calls (a comparison query's synthesis call), not repeated on retry - normal
# small-model structured-output brittleness, not a hard incompatibility, and
# this is the last-resort rung only reached under real quota pressure.
# GROQ_AGENT_MODEL overrides the primary.
DEFAULT_MODEL = os.environ.get("GROQ_AGENT_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b")
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


class RequestTooLargeError(AgentError):
    """A single request exceeded the model's per-request token limit."""


# Groq's free tier rejects (413) any single request whose input plus max_tokens
# exceeds the model's tokens-per-minute limit - 8,000 for every model in the
# chain, so rotating models never helps. Requests are fitted below this before
# they are sent.
REQUEST_TOKEN_LIMIT = int(os.environ.get("GROQ_REQUEST_TOKEN_LIMIT", "8000"))
_OUTPUT_RESERVE = 1500
_FIT_CHARS_PER_TOKEN = 3.0
_MIN_KEEP_CHARS = 400
_REQUESTED_RE = re.compile(r"requested\s+(\d+)", re.IGNORECASE)


def prompt_json(obj: Any) -> str:
    """Compact JSON for prompt payloads (pretty-printing roughly doubles tokens)."""
    return json.dumps(obj, default=str, separators=(",", ":"), ensure_ascii=False)


def _content_len(m: Any) -> int:
    content = getattr(m, "content", m)
    return len(content if isinstance(content, str) else str(content))


def estimate_tokens(messages: list) -> int:
    """Conservative token estimate for the shared limiter, including an output
    allowance. Errs high: under-estimating lets the limiter admit calls Groq
    then rejects."""
    return sum(_content_len(m) for m in messages) // 3 + 1200


def fit_messages(messages: list, max_input_tokens: int) -> list:
    """Return a copy of ``messages`` whose estimated input fits the budget.

    Shrinks the largest tool/human message contents first, keeping the head of
    each and marking the cut. System messages are never trimmed. A last-resort
    guard - agents compact their tool payloads semantically before this runs.
    """
    budget_chars = int(max_input_tokens * _FIT_CHARS_PER_TOKEN)
    total = sum(_content_len(m) for m in messages)
    if total <= budget_chars:
        return messages

    out = list(messages)
    shrinkable = sorted(
        (i for i, m in enumerate(out)
         if isinstance(m, (ToolMessage, HumanMessage)) and isinstance(m.content, str)),
        key=lambda i: len(out[i].content),
        reverse=True,
    )
    excess = total - budget_chars
    for i in shrinkable:
        if excess <= 0:
            break
        text = out[i].content
        keep = max(_MIN_KEEP_CHARS, len(text) - excess)
        if keep >= len(text):
            continue
        cut = len(text) - keep
        out[i] = out[i].model_copy(
            update={"content": text[:keep] + f"\n...[{cut} characters omitted to fit the model's request limit]"}
        )
        excess -= cut
    return out


def is_too_large_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "413" in text or "request too large" in text or "payload too large" in text


def is_generation_error(exc: BaseException) -> bool:
    """The model emitted a malformed or schema-invalid tool call (transient)."""
    text = str(exc).lower()
    return (
        "tool_use_failed" in text
        or "failed to parse tool call" in text
        or "tool call validation failed" in text
    )


def is_rate_error(exc: BaseException) -> bool:
    if is_too_large_error(exc) or is_generation_error(exc):
        return False
    text = str(exc).lower()
    return (
        "resource_exhausted" in text
        or "429" in text
        or "rate_limit" in text
        or "rate limit" in text
        or "quota" in text
    )


def describe_error(exc: BaseException) -> str:
    """One-line error for job status and reports, labelled by real cause."""
    flat = flatten_exc(exc)
    known = next(
        (e for e in flat if isinstance(e, (rl.QuotaExceededError, RequestTooLargeError))), None
    )
    primary = known or (flat[0] if flat else exc)
    if isinstance(primary, rl.QuotaExceededError):
        label = "LLM rate limit: "
    elif isinstance(primary, RequestTooLargeError):
        label = "Request too large: "
    else:
        label = ""
    return f"{label}{type(primary).__name__}: {primary}"


def _requested_tokens(exc: BaseException) -> int | None:
    match = _REQUESTED_RE.search(str(exc))
    return int(match.group(1)) if match else None


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
    """ChatGroq that paces every call through the shared limiter, fits each
    request under the per-request token limit, and rotates through a fallback
    chain on rate limiting or malformed output. Drops straight into ``create_react_agent``.

    One reservation per call against a single account-wide ``"groq"`` bucket.
    A 413 (request too large) is retried once on the same model with a tighter
    budget; rotating would not help since every model shares the limit. A
    malformed tool call is retried once, then falls through to the next model.
    """

    def _candidates(self) -> list[str]:
        return list(getattr(self, "_rl_chain", None) or [self.model_name])

    def _input_budget(self, kwargs: dict) -> int:
        # Bound tool/structured-output schemas are sent with every request too.
        schema_tokens = int(len(json.dumps(kwargs.get("tools") or [], default=str)) / _FIT_CHARS_PER_TOKEN)
        return REQUEST_TOKEN_LIMIT - (self.max_tokens or _OUTPUT_RESERVE) - schema_tokens - 200

    def _refit_after_413(self, messages: list, exc: BaseException, budget: int) -> tuple[list, int]:
        requested = _requested_tokens(exc)
        ratio = (REQUEST_TOKEN_LIMIT / requested) if requested else 0.6
        tighter = max(1000, int(budget * min(ratio, 0.9) * 0.85))
        return fit_messages(messages, tighter), tighter

    def _on_failure(self, exc: BaseException, cand: str, attempt: int, state: dict) -> str:
        """Decide what to do after a failed call: "retry" the same model,
        move to the "next" model, or "raise". Mutates ``state`` (messages,
        budget, errors) for the retry."""
        if is_too_large_error(exc):
            if attempt == 0:
                state["messages"], state["budget"] = self._refit_after_413(state["messages"], exc, state["budget"])
                return "retry"
            raise RequestTooLargeError(
                f"request still exceeds {cand}'s {REQUEST_TOKEN_LIMIT}-token limit after compaction"
            ) from exc
        if is_generation_error(exc):
            if attempt == 0:
                return "retry"
            state["errors"].append(f"{cand}: malformed tool call")
            return "next"
        if is_rate_error(exc):
            state["rate_limited"] = True
            state["errors"].append(f"{cand}: rate limited")
            return "next"
        return "raise"

    @staticmethod
    def _exhausted(state: dict) -> BaseException:
        detail = " | ".join(state["errors"])
        if state["rate_limited"]:
            return rl.QuotaExceededError(f"all fallback models failed: {detail}")
        return AgentError(f"all fallback models failed: {detail}")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        state = {"budget": self._input_budget(kwargs), "errors": [], "rate_limited": False}
        state["messages"] = fit_messages(messages, state["budget"])
        original = self.model_name
        rid = rl.acquire(estimate_tokens(state["messages"]), "groq", timeout=240.0)
        used = False
        try:
            for cand in self._candidates():
                object.__setattr__(self, "model_name", cand)
                for attempt in range(2):
                    try:
                        out = super()._generate(state["messages"], stop, run_manager, **kwargs)
                        used = True
                        return out
                    except BaseException as exc:  # noqa: BLE001
                        action = self._on_failure(exc, cand, attempt, state)
                        if action == "raise":
                            raise
                        if action == "next":
                            break
            raise self._exhausted(state)
        finally:
            object.__setattr__(self, "model_name", original)
            if not used:
                rl.refund(rid, "groq")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        state = {"budget": self._input_budget(kwargs), "errors": [], "rate_limited": False}
        state["messages"] = fit_messages(messages, state["budget"])
        original = self.model_name
        rid = await asyncio.to_thread(
            functools.partial(rl.acquire, estimate_tokens(state["messages"]), "groq", timeout=240.0)
        )
        used = False
        try:
            for cand in self._candidates():
                object.__setattr__(self, "model_name", cand)
                for attempt in range(2):
                    try:
                        out = await super()._agenerate(state["messages"], stop, run_manager, **kwargs)
                        used = True
                        return out
                    except BaseException as exc:  # noqa: BLE001
                        action = self._on_failure(exc, cand, attempt, state)
                        if action == "raise":
                            raise
                        if action == "next":
                            break
            raise self._exhausted(state)
        finally:
            object.__setattr__(self, "model_name", original)
            if not used:
                rl.refund(rid, "groq")


def make_model(model_name: str = DEFAULT_MODEL, *, max_tokens: int | None = None) -> RateLimitedChatGroq:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise AgentError(
            "GROQ_API_KEY is not set (checked the environment and the project .env)."
        )
    kw = {"model": model_name, "temperature": 0.0, "max_retries": 0, "groq_api_key": key}
    if max_tokens:  # a hard ceiling - a degenerate gpt-oss generation truncates
        kw["max_tokens"] = max_tokens  # instead of looping a token run forever
    m = RateLimitedChatGroq(**kw)
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
StageFn = Callable[[str], None]


class _StageCallback(AsyncCallbackHandler):
    """Turns a ReAct loop's tool calls and model turns into short human-readable
    stage strings ("calling get_quote...") via ``on_stage``, so a client polling
    mid-run sees what's actually happening instead of one static "running" for
    up to a couple of minutes. Best-effort: ``on_stage`` itself is expected not
    to raise, but a callback failing must never break the actual agent run."""

    def __init__(self, on_stage: StageFn):
        self._on_stage = on_stage

    def _fire(self, msg: str) -> None:
        try:
            self._on_stage(msg)
        except Exception:  # noqa: BLE001 - progress reporting is never fatal
            pass

    async def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self._fire("thinking...")

    async def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        name = (serialized or {}).get("name") or "a tool"
        self._fire(f"calling {name}...")

    async def on_tool_end(self, output, **kwargs) -> None:
        self._fire("reading results...")


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
    on_stage: StageFn | None = None,
) -> dict:
    """Connect to one MCP server, run the ReAct loop + synthesis, return the
    standard agent result dict. Agent-specific bits are the three callables/strings.

    ``compact_tool_result(tool_name, payload)`` (optional): shrink what the ReAct
    loop sees per tool call. ``raw_data`` / provenance still get the full payload.
    ``on_stage(msg)`` (optional): fired with a short phase string at each
    meaningful step (connecting, thinking, calling a tool, synthesizing) - see
    ``_StageCallback``. Purely observational; never changes what the agent does.
    """
    if not query or not query.strip():
        return {"query": query, "error": "query is empty."}

    def stage(msg: str) -> None:
        if on_stage:
            try:
                on_stage(msg)
            except Exception:  # noqa: BLE001 - progress reporting is never fatal
                pass

    params = StdioServerParameters(command=sys.executable, args=[server_path])
    call_log: list[dict] = []
    try:
        stage("connecting...")
        async with Client(params) as client:
            tools = await load_mcp_tools(client, call_log, to_llm=compact_tool_result)
            model = make_model(model_name)
            agent = create_react_agent(model, tools, prompt=system_prompt)
            config: dict[str, Any] = {"recursion_limit": recursion_limit}
            if on_stage:
                config["callbacks"] = [_StageCallback(stage)]
            state = await agent.ainvoke({"messages": [HumanMessage(query)]}, config=config)
            stage("writing summary...")
            synth = await synthesize(model, query, call_log)
            trace = extract_trace(state["messages"])
    except BaseException as exc:  # noqa: BLE001 - unwrap anyio/MCP ExceptionGroups
        return {
            "query": query,
            "error": describe_error(exc),
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
