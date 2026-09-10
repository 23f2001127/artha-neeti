"""agents/planner.py - the LangGraph orchestrator that turns a raw question into
ArthaNeeti's end-to-end research pipeline.

The graph
---------
    START -> route -> (gather -> synthesize -> [compare]) -> finalize -> END

- **route**   one Groq call decides: which compan(ies) (resolved to NSE tickers,
              flagged if yfinance can't confirm them), single vs multi-company,
              and which of the three specialists each company actually needs -
              selective, with a stated reason for every skip. Filings is skipped
              up front for any company outside the 10-report RAG corpus.
- **gather**  runs the selected specialists, as a bounded-concurrency fan-out over
              the (company x specialist) matrix. Each specialist is the existing
              agent, called through its own ``run`` coroutine - nothing is
              reimplemented or bypassed.
- **synthesize** one ``synthesis_agent.synthesize`` call per company over whatever
              specialist outputs came back (its proven Case-2 partial handling
              does the rest).
- **compare** multi-company only: a light Groq call over the finished per-company
              reports for a cross-company read. (Design note below.)
- **finalize** assembles the output, including the full routing rationale.

Multi-company design
--------------------
Per-company full pipeline (specialists + synthesis) FIRST, then one comparison
step over the finished reports. Chosen over "one synthesis call across everything"
because (a) the user gets a proper standalone research view per company AND the
comparison, (b) each company keeps its own conflict-flagging and caveats instead
of them being blended, (c) it reuses ``synthesis_agent`` unchanged. The comparison
step is deliberately its own small structured call, not another ``synthesize``
invocation - ``synthesize``'s schema/prompt are built for one company's raw
specialist output, not for reports that are already synthesised.

Concurrency
-----------
``PLANNER_MAX_CONCURRENCY`` (default 2, read per-call) bounds in-flight specialist
agents. Each fires 3-5 Groq calls and spawns an MCP subprocess; this project's
Groq budget is ~5k tokens/min shared (measured) and the machine is memory-tight.
2 overlaps the non-LLM work (MCP spawn, Tavily, embeddings) for a single-company
query. A multi-company query (up to 6 specialist agents) is safest at **1** on the
free tier - the first test run 429-cascaded at 2 - so the caller should set
``PLANNER_MAX_CONCURRENCY=1`` for comparisons until the quota headroom is there.

Use
---
    from agents.planner import plan_sync
    result = plan_sync("give me a complete research view on TCS")
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import operator
import os
import sys
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents import _base, filings_agent, market_data_agent, news_sentiment_agent, synthesis_agent
from agents._base import DEFAULT_MODEL
from agents.filings_agent import INGESTED_TICKERS

def _concurrency(multi: bool = False) -> int:
    """Max in-flight specialist agents, read per-call. An explicit
    ``PLANNER_MAX_CONCURRENCY`` wins. Otherwise: 2 for a single-company query
    (overlaps MCP spawn / Tavily / embeddings), but **1** for a multi-company one -
    that fans out to up to 6 specialist agents and 429-cascaded at 2 on the free
    Groq budget (~5k tokens/min shared, measured). At 1 the fan-out serializes through the
    shared limiter and calls wait rather than fail."""
    env = os.environ.get("PLANNER_MAX_CONCURRENCY")
    if env is not None:
        return max(1, int(env))
    return 1 if multi else 2


# Optional intermediate-progress hook. A caller (the FastAPI job runner) sets this
# via plan(on_progress=...); nodes push {routing_trace, routing, specialist_status,
# ...} fragments through it as the graph advances, so a client polling mid-run sees
# real progress instead of silence. Best-effort - a failing callback never breaks
# the run. A ContextVar (not a global) so concurrent plan() calls stay isolated.
_progress_cb: contextvars.ContextVar[Callable[[dict], None] | None] = contextvars.ContextVar(
    "planner_progress_cb", default=None
)


def _emit(**fields: Any) -> None:
    cb = _progress_cb.get()
    if cb is None:
        return
    try:
        cb(fields)
    except Exception:  # noqa: BLE001 - progress reporting must never break the graph
        pass


def _deep(status: dict) -> dict:
    """Snapshot the 2-level specialist_status dict so a later mutation can't race
    a callback that hasn't finished with it."""
    return {t: dict(per) for t, per in status.items()}


SPECIALISTS = ("market_data", "news_sentiment", "filings")
_RUNNERS = {
    "market_data": market_data_agent.run,
    "news_sentiment": news_sentiment_agent.run,
    "filings": filings_agent.run,
}
_DEFAULT_SUBQ = {
    "market_data": "current price, valuation multiples and key ratios (ROE, margins, leverage)",
    "news_sentiment": "recent news and current market sentiment",
    "filings": "key risks, strategy and performance disclosed in the latest annual report",
}

# NSE large-caps that never need a yfinance round-trip to confirm. The 10 filings
# companies plus common index names.
_KNOWN_NSE = frozenset({
    "RELIANCE", "TCS", "M&M", "HDFCBANK", "ICICIBANK", "INFY", "LT", "BHARTIARTL",
    "HINDUNILVR", "SUNPHARMA", "SBIN", "ITC", "KOTAKBANK", "AXISBANK", "BAJFINANCE",
    "BAJAJFINSV", "ASIANPAINT", "MARUTI", "HCLTECH", "WIPRO", "TECHM", "TITAN",
    "NESTLEIND", "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC", "COALINDIA", "TATAMOTORS",
    "TATASTEEL", "JSWSTEEL", "ADANIENT", "ADANIPORTS", "GRASIM", "HINDALCO", "DRREDDY",
    "CIPLA", "DIVISLAB", "BRITANNIA", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO",
    "SHREECEM", "BPCL", "IOC", "GAIL", "DMART", "PIDILITIND", "DABUR", "GODREJCP",
})


# --------------------------------------------------------------------------- #
# routing LLM schema
# --------------------------------------------------------------------------- #
class _RoutedCompany(BaseModel):
    name: str = Field(description="company display name")
    ticker: str = Field(description="NSE ticker symbol, NO exchange suffix (RELIANCE, TCS, INFY, M&M, SBIN)")


class _SpecialistRoute(BaseModel):
    specialist: str = Field(description="one of: market_data, news_sentiment, filings")
    relevant: bool = Field(description="would a good analyst consult this specialist for THIS question?")
    sub_query: str = Field(default="", description="company-agnostic phrasing of what to fetch; '' if not relevant")
    reason: str = Field(description="why this specialist is or isn't relevant to the user's question")


class _RoutingDecision(BaseModel):
    companies: list[_RoutedCompany]
    is_comparison: bool = Field(description="true if the user wants 2+ companies compared or ranked")
    routes: list[_SpecialistRoute] = Field(
        description="exactly three entries - market_data, news_sentiment, filings"
    )
    rationale: str = Field(description="one paragraph explaining the overall dispatch")


_ROUTER_PROMPT = """You are the routing brain of ArthaNeeti, an Indian-equity \
research system. Given a user's question you decide how to dispatch it - you do \
NOT answer it.

Return:
- companies: every company the question is about, each with a display name and its \
NSE ticker symbol WITHOUT any exchange suffix (RELIANCE, TCS, INFY, M&M, HDFCBANK, \
SBIN, ...). Empty list if the question names no company.
- is_comparison: true if the user wants two or more companies compared or ranked.
- routes: EXACTLY three entries - one each for market_data, news_sentiment, \
filings. For each: relevant (bool), a short reason, and if relevant a \
company-agnostic sub_query naming what to fetch.

When each specialist is relevant:
- market_data: price, valuation, multiples (P/E), ratios (ROE, margins, debt), \
returns, "how is X valued", "is X cheap/expensive", any comparison of financial \
metrics.
- news_sentiment: recent news, "what's happening with X", market sentiment / mood, \
analyst reactions, dividend / buyback / earnings-date / M&A announcements.
- filings: what the company itself disclosed in its latest annual report - risk \
factors, strategy, management commentary, segment performance, governance, ESG, \
capex plans, litigation.

Select ONLY the specialists a good analyst would actually consult for THIS \
question. A narrow factual question ("current share price") needs market_data \
alone. A broad "complete view / research report / should I buy / full picture" \
needs all three. Every skip needs a real reason.

rationale: one paragraph on the overall dispatch."""


# --------------------------------------------------------------------------- #
# comparison LLM schema (multi-company)
# --------------------------------------------------------------------------- #
class _CompareDimension(BaseModel):
    dimension: str = Field(description="e.g. Valuation, Profitability, Sentiment, Disclosed risks, Balance sheet")
    assessment: str = Field(description="how the companies stack up on this dimension, citing the per-company reports")
    edge: str | None = Field(default=None, description="company that looks stronger here, 'comparable', or null")


class _Comparison(BaseModel):
    companies: list[str]
    verdict: str = Field(description="the overall comparative take - do not force a winner if the reports don't support one")
    dimensions: list[_CompareDimension]
    caveats: list[str] = Field(
        description="incl. that this is built from already-synthesised per-company reports, "
        "and any data-vintage / sample limits those reports carried"
    )


_COMPARE_PROMPT = """You are ArthaNeeti's cross-company comparison step. You are \
given the FINISHED research reports for two or more companies (each already \
reconciled from its own specialists). Produce a comparison.

Rules:
- Compare only on what the reports actually contain. Do not introduce new facts.
- Carry the reports' caveats forward - especially that market data and filings may \
be different fiscal years, and that sentiment is a small recent-news sample.
- Do not manufacture a winner. If the reports don't support a clear edge on a \
dimension, say "comparable" and why.
- dimensions: the handful that matter for THIS question (valuation, profitability, \
leverage, sentiment, disclosed risk, growth commentary - whichever the reports \
speak to)."""


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
class PlannerState(TypedDict, total=False):
    query: str
    model_name: str
    # routing
    routing: dict
    companies: list[dict]
    mode: str                    # "single" | "multi" | "none"
    plan: dict                   # {ticker: {specialist: sub_query}}
    routing_trace: list[str]
    # execution
    specialist_outputs: dict     # {ticker: {specialist: output_dict}}
    specialist_status: dict      # {ticker: {specialist: "ok" | "error: ..."}}
    reports: dict                # {ticker: synthesis report}
    comparison: dict
    # transparency
    graph_path: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    final: dict


# --------------------------------------------------------------------------- #
def _norm_ticker(sym: str) -> str:
    t = (sym or "").strip().upper()
    for suf in (".NS", ".BO"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t


async def _validate_ticker(base: str) -> tuple[bool, str]:
    """(resolvable, note). Known large-caps pass free; the rest get ONE cheap
    yfinance existence check (fast_info, not full .info). This is the only place
    the planner touches yfinance directly, and only to confirm a symbol exists -
    never for data (that stays with market-data-mcp)."""
    if not base:
        return False, "routing proposed no ticker"
    if base in _KNOWN_NSE:
        return True, "known NSE large-cap (no lookup needed)"

    def _check() -> float | None:
        try:
            import yfinance as yf
            fi = yf.Ticker(f"{base}.NS").fast_info
            for key in ("last_price", "lastPrice", "previous_close", "previousClose"):
                try:
                    v = fi[key]
                except Exception:  # noqa: BLE001
                    v = getattr(fi, key, None)
                if isinstance(v, (int, float)) and v > 0:
                    return float(v)
        except Exception:  # noqa: BLE001 - yfinance throws a grab-bag
            return None
        return None

    try:
        price = await asyncio.wait_for(asyncio.to_thread(_check), timeout=20.0)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        price = None
    if price:
        return True, f"confirmed on yfinance (last/prev price {price})"
    return False, f"'{base}.NS' returned no market data from yfinance"


# --------------------------------------------------------------------------- #
# nodes
# --------------------------------------------------------------------------- #
async def _route_node(state: PlannerState) -> dict:
    query = state["query"]
    model_name = state.get("model_name", DEFAULT_MODEL)
    model = _base.make_model(model_name)

    decision: _RoutingDecision = await model.with_structured_output(_RoutingDecision).ainvoke(
        [_base.SystemMessage(_ROUTER_PROMPT), _base.HumanMessage(query)]
    )
    if isinstance(decision, dict):
        decision = _RoutingDecision(**decision)

    routes = {r.specialist: r for r in decision.routes if r.specialist in SPECIALISTS}
    trace: list[str] = [f"routing query: {query!r}", f"LLM rationale: {decision.rationale}"]

    companies_out: list[dict] = []
    plan: dict[str, dict[str, str]] = {}
    for rc in decision.companies:
        base = _norm_ticker(rc.ticker)
        resolvable, note = await _validate_ticker(base)
        in_corpus = base in INGESTED_TICKERS
        companies_out.append({
            "name": rc.name, "ticker": base, "nse_symbol": f"{base}.NS" if base else None,
            "resolvable": resolvable, "resolution_note": note, "in_filings_corpus": in_corpus,
        })
        trace.append(
            f"company {rc.name!r} -> {base}.NS: "
            f"{'RESOLVABLE' if resolvable else 'NOT resolvable'} ({note}); "
            f"{'in' if in_corpus else 'NOT in'} filings corpus"
        )
        if not resolvable and not in_corpus:
            trace.append(f"  -> {rc.name}: no usable data source (no ticker, no filing) - dropped")
            continue

        per: dict[str, str] = {}
        for sp in SPECIALISTS:
            r = routes.get(sp)
            if r is None or not r.relevant:
                trace.append(f"  -> {base}: skip {sp} - {r.reason if r else 'no route returned'}")
                continue
            if sp == "market_data" and not resolvable:
                trace.append(f"  -> {base}: skip market_data - ticker not resolvable on yfinance")
                continue
            if sp == "filings" and not in_corpus:
                trace.append(
                    f"  -> {base}: skip filings - not one of the {len(INGESTED_TICKERS)} ingested "
                    f"annual reports ({', '.join(INGESTED_TICKERS)})"
                )
                continue
            per[sp] = (r.sub_query or "").strip() or _DEFAULT_SUBQ[sp]
            trace.append(f"  -> {base}: call {sp} - {r.reason}")
        if per:
            plan[base] = per
        else:
            trace.append(f"  -> {base}: no applicable specialists, nothing to run")

    mode = "multi" if len(plan) >= 2 else ("single" if len(plan) == 1 else "none")
    selected = sorted({sp for per in plan.values() for sp in per})

    skipped: list[dict] = []
    for sp in SPECIALISTS:
        if sp in selected:
            continue
        r = routes.get(sp)
        if r is None:
            skipped.append({"specialist": sp, "reason": "router returned no route for it"})
        elif not r.relevant:
            skipped.append({"specialist": sp, "reason": r.reason or "not relevant to this query"})
        else:  # relevant, but filtered for every company
            why = []
            if sp == "filings":
                bad = [c["ticker"] for c in companies_out if not c["in_filings_corpus"]]
                if bad:
                    why.append(f"none of {bad} are in the {len(INGESTED_TICKERS)}-company filings corpus")
            if sp == "market_data":
                bad = [c["ticker"] for c in companies_out if not c["resolvable"]]
                if bad:
                    why.append(f"tickers not resolvable on yfinance: {bad}")
            skipped.append({"specialist": sp, "reason": "; ".join(why) or "filtered out during routing"})

    routing = {
        "companies_identified": [
            {k: c[k] for k in ("name", "ticker", "resolvable", "in_filings_corpus")} for c in companies_out
        ],
        "is_comparison": decision.is_comparison,
        "mode": mode,
        "specialists_selected": selected,
        "specialists_skipped": skipped,
        "sub_queries": plan,
        "rationale": decision.rationale,
    }
    note = f"route: {len(companies_out)} company(ies), mode={mode}, specialists={selected or 'none'}"
    # push routing out immediately - the frontend shows the decision before the
    # (slow) specialist phase even starts.
    _emit(routing=routing, routing_trace=trace, companies=companies_out, mode=mode)
    return {
        "routing": routing, "companies": companies_out, "mode": mode, "plan": plan,
        "routing_trace": trace, "graph_path": [note],
    }


def _after_route(state: PlannerState) -> str:
    return "gather" if state.get("plan") else "finalize"


async def _gather_node(state: PlannerState) -> dict:
    plan: dict = state["plan"]
    model_name = state.get("model_name", DEFAULT_MODEL)
    names = {c["ticker"]: c["name"] for c in state.get("companies", [])}
    n = _concurrency(multi=len(plan) >= 2)
    sem = asyncio.Semaphore(n)

    outputs: dict[str, dict] = {}
    # seed every planned (company, specialist) cell as 'pending' and push it, so a
    # polling client sees the shape up front and each cell then flips to ok/error.
    status: dict[str, dict] = {t: {sp: "pending" for sp in per} for t, per in plan.items()}
    _emit(specialist_status=_deep(status))

    async def _one(ticker: str, specialist: str, sub_query: str) -> None:
        company = names.get(ticker, ticker)
        full_q = f"{company} ({ticker}.NS): {sub_query}"
        async with sem:
            try:
                out = await _RUNNERS[specialist](full_q, model_name=model_name)
            except BaseException as exc:  # noqa: BLE001
                flat = _base.flatten_exc(exc)
                head = flat[0] if flat else exc
                out = {"error": f"{type(head).__name__}: {head}", "query": full_q}
        outputs.setdefault(ticker, {})[specialist] = out
        status[ticker][specialist] = (
            "ok" if isinstance(out, dict) and "error" not in out
            else f"error: {str(out.get('error'))[:140]}"
        )
        _emit(specialist_status=_deep(status))

    tasks = [_one(t, sp, q) for t, per in plan.items() for sp, q in per.items()]
    await asyncio.gather(*tasks)

    ok = sum(1 for per in status.values() for v in per.values() if v == "ok")
    total = sum(len(per) for per in status.values())
    return {
        "specialist_outputs": outputs, "specialist_status": status,
        "graph_path": [f"gather: {ok}/{total} specialist calls ok (concurrency={n})"],
    }


async def _synthesize_node(state: PlannerState) -> dict:
    model_name = state.get("model_name", DEFAULT_MODEL)
    names = {c["ticker"]: c["name"] for c in state.get("companies", [])}
    outputs: dict = state.get("specialist_outputs", {})
    sem = asyncio.Semaphore(_concurrency(multi=len(outputs) >= 2))
    reports: dict[str, dict] = {}

    async def _one(ticker: str, specialist_outputs: dict) -> None:
        company = names.get(ticker, ticker)
        sq = (
            f"Give an overall research view on {company}: reconcile its fundamentals, "
            f"recent sentiment and disclosed risks into one picture, surfacing any tension."
        )
        async with sem:
            try:
                reports[ticker] = await synthesis_agent.synthesize(
                    sq, specialist_outputs, model_name=model_name
                )
            except BaseException as exc:  # noqa: BLE001 - synthesize has its own guard; this is belt-and-suspenders
                flat = _base.flatten_exc(exc)
                head = flat[0] if flat else exc
                reports[ticker] = {"query": sq, "error": f"{type(head).__name__}: {head}"}

    await asyncio.gather(*(_one(t, o) for t, o in outputs.items()))
    ok = sum(1 for r in reports.values() if "error" not in r)
    return {"reports": reports, "graph_path": [f"synthesize: {ok}/{len(reports)} per-company reports built"]}


def _after_synth(state: PlannerState) -> str:
    good = [t for t, r in state.get("reports", {}).items() if "error" not in r]
    return "compare" if state.get("mode") == "multi" and len(good) >= 2 else "finalize"


async def _compare_node(state: PlannerState) -> dict:
    model_name = state.get("model_name", DEFAULT_MODEL)
    names = {c["ticker"]: c["name"] for c in state.get("companies", [])}
    reports: dict = state.get("reports", {})

    digest = []
    for ticker, r in reports.items():
        if "error" in r:
            continue
        digest.append({
            "company": names.get(ticker, ticker),
            "ticker": ticker,
            "executive_summary": r.get("executive_summary"),
            "claims": list(r.get("sources_by_claim", {}).keys()),
            "conflicts_flagged": r.get("conflicts_flagged"),
            "overall_caveats": r.get("overall_caveats"),
            "sections": r.get("sections"),
        })
    if len(digest) < 2:
        return {"graph_path": ["compare: skipped (fewer than 2 usable reports)"]}

    model = _base.make_model(model_name)
    comp: _Comparison = await model.with_structured_output(_Comparison).ainvoke([
        _base.SystemMessage(_COMPARE_PROMPT),
        _base.HumanMessage(
            f"ORIGINAL USER QUERY:\n{state['query']}\n\n"
            f"PER-COMPANY REPORTS (JSON):\n{json.dumps(digest, indent=2, default=str)}"
        ),
    ])
    if isinstance(comp, dict):
        comp = _Comparison(**comp)
    return {
        "comparison": {
            "companies": comp.companies,
            "verdict": comp.verdict,
            "dimensions": [d.model_dump() for d in comp.dimensions],
            "caveats": comp.caveats,
        },
        "graph_path": [f"compare: {len(digest)} reports, {len(comp.dimensions)} dimensions"],
    }


def _finalize_node(state: PlannerState) -> dict:
    final = {
        "query": state["query"],
        "mode": state.get("mode", "none"),
        "companies": state.get("companies", []),
        "routing": state.get("routing", {}),
        "routing_trace": state.get("routing_trace", []),
        "reports": state.get("reports", {}),
        "comparison": state.get("comparison"),
        "specialist_status": state.get("specialist_status", {}),
        "graph_path": state.get("graph_path", []) + ["finalize"],
        "errors": state.get("errors", []),
        "model": state.get("model_name", DEFAULT_MODEL),
    }
    if state.get("mode") == "none":
        final["note"] = (
            "No company could be resolved to a usable data source for this query; "
            "nothing was dispatched. See routing_trace."
        )
    return {"final": final, "graph_path": ["finalize"]}


# --------------------------------------------------------------------------- #
def _build_graph():
    g = StateGraph(PlannerState)
    g.add_node("route", _route_node)
    g.add_node("gather", _gather_node)
    g.add_node("synthesize", _synthesize_node)
    g.add_node("compare", _compare_node)
    g.add_node("finalize", _finalize_node)

    g.add_edge(START, "route")
    g.add_conditional_edges("route", _after_route, {"gather": "gather", "finalize": "finalize"})
    g.add_edge("gather", "synthesize")
    g.add_conditional_edges("synthesize", _after_synth, {"compare": "compare", "finalize": "finalize"})
    g.add_edge("compare", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


_GRAPH = _build_graph()


# --------------------------------------------------------------------------- #
async def plan(
    query: str,
    *,
    model_name: str = DEFAULT_MODEL,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Route -> gather -> synthesize -> [compare] -> finalize. Returns the final
    report dict, including the full routing rationale in ``routing_trace``.

    ``on_progress`` (optional): a sync callback invoked with intermediate-state
    fragments as the graph advances - ``{routing, routing_trace, companies, mode}``
    when routing finishes, then ``{specialist_status}`` each time a specialist
    finishes. Lets a job runner stream live progress; see ``app/jobs.py``.
    """
    if not query or not query.strip():
        return {"query": query, "error": "query is empty."}
    token = _progress_cb.set(on_progress) if on_progress is not None else None
    try:
        state = await _GRAPH.ainvoke(
            {"query": query.strip(), "model_name": model_name, "graph_path": [], "errors": []},
            config={"recursion_limit": 25},
        )
    except BaseException as exc:  # noqa: BLE001
        flat = _base.flatten_exc(exc)
        quota = next((e for e in flat if isinstance(e, _base.rl.QuotaExceededError)), None)
        head = quota or (flat[0] if flat else exc)
        return {
            "query": query,
            "error": ("LLM quota: " if quota else "") + f"{type(head).__name__}: {head}",
        }
    finally:
        if token is not None:
            _progress_cb.reset(token)
    return state.get("final") or {"query": query, "error": "planner produced no final report"}


def plan_sync(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Blocking wrapper around :func:`plan`."""
    return asyncio.run(plan(query, model_name=model_name))


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "give me a complete research view on TCS"
    print(json.dumps(plan_sync(q), indent=2, default=str))
