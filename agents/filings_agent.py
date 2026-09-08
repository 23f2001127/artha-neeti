"""Filings Agent - a standalone LangGraph specialist over filings-rag-mcp.

What it is
----------
Given a question about what an Indian-listed company disclosed in its OWN annual
report, this agent picks the right ``filings-rag-mcp`` tool, retrieves cited
chunks from the PDF, and returns a structured, page-cited result for a downstream
Synthesis Agent plus a human summary.

Shared machinery (MCP stdio client, Groq ``create_react_agent`` through
``shared/llm_rate_limiter.py``, model-fallback chain, trace extraction) is in
``agents/_base.py`` - same pattern as ``market_data_agent.py`` /
``news_sentiment_agent.py``.

The hard parts, matching filings-rag-mcp's own honest documentation:

- **Page citations are the point.** Every finding taken from a filing must carry
  the company, the fiscal year, and the specific page number(s). No un-cited
  claims from filing data.
- **``may_contain_tabular_data``** - a flagged chunk is a statement table that PDF
  extraction flattened into run-on text; its numbers may be collapsed/misaligned.
  The agent hedges those figures ("approximately", "as read from the flattened
  table on p.X"), it does not restate them with false precision.
- **``compare_yoy_metrics`` is single-filing scope** - the current + prior-year
  columns the ONE report itself discloses, not a trend across separate years'
  filings (ArthaNeeti holds one annual report per company). If the question wants
  a real multi-year trend, the agent says that plainly.
- **standalone vs consolidated** - ``get_financial_statement_section`` can return
  both; the agent flags which one a number is from, and does not blend them.

Large RAG payloads are trimmed before they hit the reasoning/synthesis models
(``_compact``); full chunk text stays in ``raw_data`` for citation.

Standalone use
--------------
    from agents.filings_agent import run_sync
    result = run_sync("what are Reliance's key disclosed risks")
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from pydantic import BaseModel, Field

from agents import _base
from agents._base import DEFAULT_MODEL

FILINGS_SERVER = str(_base.REPO_ROOT / "mcp_servers" / "filings_rag_mcp" / "server.py")

# Only these are ingested so far (free-tier embedding quota is a ~4-5 day job).
_INGESTED = ("RELIANCE", "TCS", "M&M", "BHARTIARTL")
_CHUNK_TEXT_LIMIT = 450  # chars of chunk text sent to the LLM; full text in raw_data
_MAX_CHUNKS_TO_LLM = 4
_RECURSION_LIMIT = 10     # ~3 tool calls max; retrieval is a one-shot per question


# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = f"""You are the Filings Agent for ArthaNeeti. You answer questions \
about what a company listed on an Indian exchange disclosed in its OWN annual \
report, grounded in cited pages of that report, using ONLY the tools provided.

TICKERS: pass a bare NSE-style symbol - RELIANCE, TCS, M&M, HDFCBANK, ICICIBANK, \
INFY, LT, BHARTIARTL, HINDUNILVR, SUNPHARMA (strip any .NS/.BO). Resolve company \
names yourself. Only these filings are ingested right now: {', '.join(_INGESTED)}. \
If asked about any other company, say its filing has not been ingested yet and stop.

TOOL SELECTION - pick ONE tool for the question:
- search_filing: open-ended / semantic questions about disclosures - risks, \
strategy, capex plans, segment performance, governance, ESG, litigation, outlook. \
Pass a natural-language query plus the ticker. Do NOT pass top_k - the default is \
correct.
- get_financial_statement_section: the user wants a specific primary statement. \
statement_type is one of balance_sheet, income_statement, cash_flow, \
equity_changes (aliases "income statement", "profit and loss", "p&l", "balance \
sheet", "cash flow", "changes in equity" are accepted).
- compare_yoy_metrics: the user asks how a metric CHANGED year over year - \
revenue, EBITDA, net profit, capex, EPS, operating margin, etc. Pass ticker + metric.

Do NOT call get_financial_statement_section for an open-ended risk/strategy \
question. Do NOT call compare_yoy_metrics unless the question is about a \
year-over-year change.

CALL BUDGET - this is strict:
- Make EXACTLY ONE tool call, then write your answer from what it returned. Each \
tool already returns the 5 best-matching passages from the filing - that is \
enough to answer.
- Do NOT call a tool again with a reworded query to "get more" - you will not get \
materially better passages, and it wastes a shared quota.
- A second call is allowed ONLY if the first returned an "error", or returned \
chunks that are clearly the wrong company or wrong section. Never exceed 2 calls.
- Do NOT supplement get_financial_statement_section or compare_yoy_metrics with \
search_filing - the dedicated tool's result stands on its own.

HOW TO READ THE RESULTS (these caveats are real - carry them forward, do not \
smooth them into confidence):
- Every result chunk has a page_number and a fiscal_year. You MUST cite BOTH for \
every fact you take from the filing. Never state a filing fact without its page.
- may_contain_tabular_data=true: the chunk is a financial-statement table that PDF \
extraction has flattened into run-on text. Numbers in it may be collapsed or \
misaligned. Report such figures as approximate ("about", "as best read from the \
flattened table on p.X") - do NOT give a falsely precise number.
- get_financial_statement_section: this is a semantic search + header-keyword \
boost, NOT a parsed statement. A company files BOTH a standalone and a \
consolidated version; retrieved chunks can mix the two. Say which one a number is \
from when the surrounding text tells you; if it does not, say it is unclear. Do \
not blend standalone and consolidated figures.
- compare_yoy_metrics: this returns the ONE filing's own two-year disclosure \
(current + prior-year columns, and MD&A / Board's Report commentary). It is NOT a \
multi-year trend built from separate years' filings - ArthaNeeti holds one annual \
report per company. If the question wants a longer trend, state that only this \
single year-on-year step is available.

Never invent numbers or page references. If the retrieved chunks do not answer \
the question, say so rather than guessing."""

_SYNTH_INSTRUCTIONS = """Turn the filings-rag-mcp tool output into a structured \
result for a downstream Synthesis Agent. Ground EVERYTHING in the retrieved \
chunks - no outside knowledge, no recalled figures.

findings - each a self-contained sentence:
- Every finding drawn from the filing MUST cite the company, the fiscal year, and \
the specific page number(s), e.g. "Reliance lists cybersecurity and data-privacy \
as a principal risk (Reliance Industries, FY2024-25, p.142)." A finding with no \
page cite is only acceptable if it is stating that something was NOT found in the \
retrieved chunks.
- If the supporting chunk has may_contain_tabular_data=true, hedge the figure - \
"approximately", "as read from the flattened table on p.X" - never a falsely \
precise number.
- For financial-statement figures, say whether the number is from the STANDALONE \
or the CONSOLIDATED statement if the chunk text makes it clear; if it does not, \
say "standalone/consolidated basis unclear from the retrieved text".

caveats - a NON-EMPTY list whenever a tool carried a note/limitation. Condensed \
but NOT softened. Include, as applicable:
- if any cited chunk is flagged may_contain_tabular_data: that its numbers come \
from a PDF-flattened table and may be column-collapsed / imprecise;
- for get_financial_statement_section: that it is search-based, not a parsed \
statement, and standalone vs consolidated versions can be mixed in the results;
- for compare_yoy_metrics: keep the substance of its limitation verbatim - this \
is the single filing's own year-on-year disclosure, NOT a cross-filing multi-year \
comparison; ArthaNeeti holds one annual report per company. If the user's \
question implied wanting a multi-year trend, state explicitly that only this one \
year-over-year step is available.

ticker / company / fiscal_year - the subject of the query (e.g. "M&M" / \
"Mahindra & Mahindra" / "2024-25").
statement_basis - "standalone", "consolidated", "mixed", or "n/a" - your best \
read of which basis the financial figures in the findings are on; "n/a" if the \
query was not about financial statements.
summary - 2-4 plain sentences for a human that themselves do not overstate: do \
not describe a single filing's YoY disclosure as a multi-year trend, and do not \
present flattened-table numbers as exact."""


class _FilingsSynthesis(BaseModel):
    ticker: str | None = Field(description="NSE ticker of the subject company, or null")
    company: str | None = Field(description="subject company display name, or null")
    fiscal_year: str | None = Field(description="fiscal year of the filing, e.g. '2024-25'")
    findings: list[str] = Field(
        description="page-cited finding sentences; every filing fact cites company + FY + page"
    )
    caveats: list[str] = Field(
        description="tool notes/limitations, condensed but not softened; non-empty when a tool carried one"
    )
    statement_basis: str = Field(
        description="'standalone' | 'consolidated' | 'mixed' | 'n/a' - basis of any financial figures cited"
    )
    summary: str = Field(description="2-4 sentence human summary that does not overstate")


# --------------------------------------------------------------------------- #
_CHUNK_KEEP = (
    "page_number", "similarity", "may_contain_tabular_data", "numeric_density",
    "fiscal_year", "matched_header_keyword", "matched_yoy_phrase",
)
_TOP_KEEP = (
    "ticker", "company", "statement_type", "metric", "fiscal_year", "query",
    "semantic_query", "basis", "limitation", "note", "as_of", "count", "pages_returned",
)


def _compact(_tool: str, result: Any) -> Any:
    """Shrink a filings-rag result before it reaches the reasoning / synthesis
    models: keep every caveat-bearing top-level field, cap the chunk list, and
    truncate each chunk's text. The full chunk text is preserved untouched in
    ``call_log`` -> ``raw_data`` so findings can still be verified against it.

    A single chunk can be ~1,100 tokens; 5-8 of them raw would blow Groq's
    ~8k-tokens/min budget and push the smaller fallback models into an empty
    synthesis (the bug news_sentiment_agent had to retrofit)."""
    if not isinstance(result, dict):
        return result
    out: dict[str, Any] = {k: result[k] for k in _TOP_KEEP if k in result}
    hits = result.get("results")
    if isinstance(hits, list):
        trimmed = []
        for h in hits[:_MAX_CHUNKS_TO_LLM]:
            if not isinstance(h, dict):
                continue
            row = {k: h[k] for k in _CHUNK_KEEP if k in h}
            txt = h.get("text")
            if isinstance(txt, str):
                row["text"] = txt[:_CHUNK_TEXT_LIMIT] + ("..." if len(txt) > _CHUNK_TEXT_LIMIT else "")
            trimmed.append(row)
        out["results"] = trimmed
        if len(hits) > _MAX_CHUNKS_TO_LLM:
            out["results_truncated"] = f"{len(hits) - _MAX_CHUNKS_TO_LLM} lower-ranked chunk(s) omitted"
    return out


async def _synthesize(model, query: str, call_log: list[dict]) -> dict:
    structured = model.with_structured_output(_FilingsSynthesis)
    payload = json.dumps(
        [{"tool": c["tool"], "args": c["args"], "result": _compact(c["tool"], c["result"])}
         for c in call_log],
        default=str, indent=2,
    )
    msgs = [
        _base.SystemMessage(_SYNTH_INSTRUCTIONS),
        _base.HumanMessage(
            f"USER QUESTION:\n{query}\n\nTOOL OUTPUT (JSON, {len(call_log)} tool call(s)):\n{payload}"
        ),
    ]
    result = await structured.ainvoke(msgs)
    if isinstance(result, dict):
        result = _FilingsSynthesis(**result)

    # Guard: a smaller fallback model sometimes claims the payload is empty even
    # when it is not. Nudge once before returning a dud.
    joined = " ".join(result.findings + [result.summary]).lower()
    if call_log and any(p in joined for p in ("no tool output", "no filings", "were not provided",
                                              "was not provided", "re-run the query", "no chunks")):
        msgs.append(_base.HumanMessage(
            "The TOOL OUTPUT above IS the retrieved data - it is not empty. Produce "
            "findings/caveats/summary strictly from it, citing page numbers."
        ))
        retry = await structured.ainvoke(msgs)
        if isinstance(retry, dict):
            retry = _FilingsSynthesis(**retry)
        result = retry

    return result.model_dump()


# --------------------------------------------------------------------------- #
def _pages_meta(results: Any) -> dict:
    """Page list, which of them are flattened-table pages, similarity spread."""
    if not isinstance(results, list):
        return {}
    pages, tabular, sims, kws = [], [], [], []
    for h in results:
        if not isinstance(h, dict):
            continue
        p = h.get("page_number")
        if p is not None:
            pages.append(p)
            if h.get("may_contain_tabular_data"):
                tabular.append(p)
        if isinstance(h.get("similarity"), (int, float)):
            sims.append(h["similarity"])
        kw = h.get("matched_header_keyword") or h.get("matched_yoy_phrase")
        if kw:
            kws.append(kw)
    meta: dict[str, Any] = {
        "pages": sorted(set(pages)),
        "tabular_pages": sorted(set(tabular)),
        "chunk_count": len(pages),
    }
    if sims:
        meta["similarity_range"] = [round(min(sims), 4), round(max(sims), 4)]
    if kws:
        meta["matched_keywords"] = sorted(set(kws))
    return meta


def _collect_provenance(call_log: list[dict]) -> dict:
    """Lift every caveat-bearing field so the Synthesis Agent gets it structured,
    not only baked into prose."""
    prov: dict[str, Any] = {}
    for entry in call_log:
        tool, res = entry["tool"], entry["result"]
        if not isinstance(res, dict):
            continue
        if "error" in res:
            prov[tool] = {"error": res["error"]}
            continue
        block: dict[str, Any] = {}
        for k in ("as_of", "note", "fiscal_year", "company", "ticker", "count"):
            if k in res:
                block[k] = res[k]
        block.update(_pages_meta(res.get("results")))

        if tool == "get_financial_statement_section":
            block["statement_type"] = res.get("statement_type")
            block["pages_returned"] = res.get("pages_returned")
            block["caveat"] = ("search-based, not a parsed statement; standalone and "
                               "consolidated versions can be mixed in the results")
        elif tool == "compare_yoy_metrics":
            block["metric"] = res.get("metric")
            block["basis"] = res.get("basis")
            block["limitation"] = res.get("limitation")
        elif tool == "search_filing":
            block["query"] = res.get("query")

        if block.get("tabular_pages"):
            block["tabular_warning"] = (
                "cited pages " + ", ".join(f"p.{p}" for p in block["tabular_pages"])
                + " are flagged may_contain_tabular_data - figures there may be "
                "column-flattened by PDF extraction"
            )
        prov[tool] = block
    return prov


# --------------------------------------------------------------------------- #
async def run(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Answer one question about a company's annual-report disclosures."""
    return await _base.run_agent(
        server_path=FILINGS_SERVER,
        system_prompt=_SYSTEM_PROMPT,
        query=query,
        synthesize=_synthesize,
        collect_provenance=_collect_provenance,
        model_name=model_name,
        compact_tool_result=_compact,
        recursion_limit=_RECURSION_LIMIT,
    )


def run_sync(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Blocking wrapper around :func:`run` for scripts / the future Planner node."""
    return asyncio.run(run(query, model_name=model_name))


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "what are Reliance's key disclosed risks"
    print(json.dumps(run_sync(q), indent=2, default=str))
