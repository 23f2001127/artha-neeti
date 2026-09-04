"""News & Sentiment Agent - a standalone LangGraph specialist over research-mcp.

What it is
----------
Given a natural-language question about recent news, market sentiment, or
corporate announcements for an Indian-listed company, this agent picks the right
``research-mcp`` tool(s), calls them, and returns a structured result for a
downstream Synthesis Agent plus a human summary.

Shared machinery (MCP stdio client, Groq ``create_react_agent`` through
``shared/llm_rate_limiter.py``, model-fallback chain, trace extraction) is in
``agents/_base.py`` - the same pattern as ``market_data_agent.py``.

The hard part: research-mcp's tools carry real caveats, and this agent must NOT
smooth them into false confidence:

- **get_sentiment** has two modes. For a "sentiment on <company>" question the
  agent passes a ticker so the tool runs AGGREGATE mode over recent news. The
  trustworthy headline is ``overall.label`` + **``breakdown_on_company``** over the
  on-company articles - the raw ``breakdown`` also counts off-entity items and is
  inflated (this matches research-mcp's own README). ``score`` is the model's
  self-reported confidence, not a calibrated probability.
- **get_corporate_announcements** is a keyword-scoped Tavily news search, **NOT**
  the NSE/BSE official feed. Its ``disclaimer`` string is carried verbatim into
  ``caveats``. Findings lead with ``likely_announcement=true`` items; anything
  cited from the unflagged tail is labelled lower-confidence with the reason.
- **get_company_news** items flagged ``mentions_company=false`` may be about a
  group company / peer; relying on them is noted.

Standalone use
--------------
    from agents.news_sentiment_agent import run_sync
    result = run_sync("what's the market sentiment on TCS right now")
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from pydantic import BaseModel, Field

from agents import _base
from agents._base import DEFAULT_MODEL

RESEARCH_SERVER = str(_base.REPO_ROOT / "mcp_servers" / "research_mcp" / "server.py")


# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = """You are the News & Sentiment Agent for ArthaNeeti. You answer \
questions about recent news, market sentiment, and corporate announcements for \
companies listed on Indian exchanges, using ONLY the tools provided.

TOOL SELECTION (call the fewest that answer the question, then stop):
- search_news: open-ended / multi-company / topic queries ("India IT layoffs", \
"Adani news", "RBI rate decision reaction").
- get_company_news: "what's the latest on <one company>". Pass the ticker or name.
- get_sentiment: "what's the sentiment / how is the market feeling about <company>". \
  Pass the SHORT ticker or name (e.g. "TCS.NS") so the tool runs its AGGREGATE \
  mode over recent news. Only pass a long passage of text if the user gave you a \
  specific quote/paragraph to judge.
- get_corporate_announcements: "any dividend / earnings / results / board meeting / \
  buyback / M&A announcements from <company>". Pass the ticker.

Do NOT call get_sentiment for a plain "what's the news" question. Do NOT call \
get_corporate_announcements for a sentiment question.

HOW TO READ THE RESULTS (this matters - the tools have caveats):
- get_sentiment AGGREGATE: the headline is overall.label plus breakdown_on_company \
  (positive/neutral/negative among the on_company_count articles that actually \
  name the company). The plain 'breakdown' ALSO counts off-entity articles and is \
  inflated - do not quote it as the sentiment. 'score' is the model's own \
  confidence, not a validated probability.
- get_corporate_announcements: this is a keyword news search, NOT the NSE/BSE \
  official announcements feed. Trust items where likely_announcement is true \
  (they both name the company AND match announcement keywords). If you mention an \
  item where likely_announcement is false, say it is lower-confidence and why.
- get_company_news / announcements: an item with mentions_company=false may be \
  about a group company (e.g. Tech Mahindra / Mahindra Finance for M&M), not the \
  company asked about.

Never invent facts. Cite the source and date. Carry every tool 'disclaimer' / \
'note' forward - do not present low-confidence results as certain."""

_SYNTH_INSTRUCTIONS = """Turn the research-mcp tool output into a structured result \
for a downstream Synthesis Agent. Ground everything in the tool output only.

findings - each a self-contained sentence:
- Cite the article title/source and published_date where available.
- If get_sentiment ran in AGGREGATE mode: state overall.label and score, then the \
  breakdown_on_company counts over on_company_count articles as THE sentiment \
  number. If the raw 'breakdown' differs, note it counts off-entity articles too.
- If get_sentiment ran in TEXT mode: state label + score for that passage.
- If get_corporate_announcements ran: list the likely_announcement=true items \
  first; for any likely_announcement=false item you include, append \
  "(lower confidence: not flagged on-company / no announcement keyword)".

caveats - a NON-EMPTY list whenever a tool carried a disclaimer/note. Include, \
condensed but not softened:
- the get_corporate_announcements disclaimer, keeping the phrase that it is NOT \
  the NSE/BSE official corporate-announcement feed;
- the entity-disambiguation risk (results can include a group company / peer), \
  naming the specific noise if the data shows it (e.g. Tech Mahindra / Mahindra \
  Finance for M&M);
- for sentiment: that 'score' is a self-reported confidence, not calibrated, and \
  the sample is whatever the news search surfaced, not exhaustive.

ticker/company - the company the question is about (e.g. "TCS.NS" /
"Tata Consultancy Services"). Fill BOTH whenever the query names one company; use
null only for a genuine multi-company or topic query.
summary - 2-4 plain sentences for a human, that themselves do not overstate \
confidence."""


class _NewsSynthesis(BaseModel):
    ticker: str | None = Field(description="primary NSE ticker or null for a topic query")
    company: str | None = Field(description="primary company name or null")
    findings: list[str] = Field(description="grounded, source-cited finding sentences")
    caveats: list[str] = Field(
        description="tool disclaimers + confidence limits, condensed but not softened; "
        "non-empty whenever a tool carried one"
    )
    summary: str = Field(description="2-4 sentence human summary that does not overstate confidence")


def _compact(result: Any) -> Any:
    """Shrink a tool result for the synthesis prompt - keep every caveat-bearing
    field, trim article snippets, drop bulky article lists to their essentials.
    A 9-article get_company_news blob otherwise confuses the smaller fallback
    models into returning an empty synthesis."""
    if not isinstance(result, dict):
        return result
    out: dict[str, Any] = {}
    for k, v in result.items():
        if k in ("results", "articles", "announcements") and isinstance(v, list):
            out[k] = [
                {
                    kk: (vv[:200] + "..." if kk == "snippet" and isinstance(vv, str) and len(vv) > 200 else vv)
                    for kk, vv in it.items()
                    if kk in ("title", "url", "published_date", "snippet", "source_score",
                              "mentions_company", "matched_keywords", "likely_announcement",
                              "label", "score", "index")
                }
                for it in v
                if isinstance(it, dict)
            ]
        else:
            out[k] = v
    return out


async def _synthesize(model, query: str, call_log: list[dict]) -> dict:
    structured = model.with_structured_output(_NewsSynthesis)
    payload = json.dumps(
        [{"tool": c["tool"], "args": c["args"], "result": _compact(c["result"])} for c in call_log],
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
        result = _NewsSynthesis(**result)

    # Guard: a smaller fallback model sometimes claims "no tool output" even with
    # a populated payload. Retry once, nudging it, before returning a dud.
    joined = " ".join(result.findings + [result.summary]).lower()
    if call_log and any(p in joined for p in ("no tool output", "no research-mcp tool output",
                                              "were not provided", "was not provided", "re-run the query")):
        msgs.append(_base.HumanMessage(
            "The TOOL OUTPUT above IS the data - it is not empty. Produce the "
            "findings/caveats/summary strictly from it."
        ))
        retry = await structured.ainvoke(msgs)
        if isinstance(retry, dict):
            retry = _NewsSynthesis(**retry)
        result = retry

    return result.model_dump()


# --------------------------------------------------------------------------- #
def _flag_breakdown(items: list) -> dict:
    if not isinstance(items, list):
        return {}
    n = len(items)
    return {
        "total": n,
        "mentions_company_true": sum(1 for it in items if isinstance(it, dict) and it.get("mentions_company")),
        "likely_announcement_true": sum(
            1 for it in items if isinstance(it, dict) and it.get("likely_announcement")
        ),
    }


def _collect_provenance(call_log: list[dict]) -> dict:
    """Lift every caveat-bearing field so the Synthesis Agent gets it structured,
    not only baked into prose."""
    prov: dict[str, Any] = {}
    for entry in call_log:
        tool, res = entry["tool"], entry["result"]
        if not isinstance(res, dict):
            continue
        block: dict[str, Any] = {}
        for k in ("as_of", "note", "disclaimer", "model", "mode", "query"):
            if k in res:
                block[k] = res[k]

        if tool == "get_sentiment" and res.get("mode") == "aggregate":
            block.update({
                "overall": res.get("overall"),
                "breakdown": res.get("breakdown"),
                "breakdown_on_company": res.get("breakdown_on_company"),
                "on_company_count": res.get("on_company_count"),
                "article_count": res.get("article_count"),
                "trust": "breakdown_on_company is the sentiment number; breakdown "
                         "includes off-entity articles",
            })
        elif tool == "get_sentiment":
            block.update({"label": res.get("label"), "score": res.get("score")})
        elif tool == "get_corporate_announcements":
            block.update({
                "count": res.get("count"),
                "likely_announcement_count": res.get("likely_announcement_count"),
                "on_company_count": res.get("on_company_count"),
                "flag_breakdown": _flag_breakdown(res.get("announcements")),
            })
        elif tool in ("get_company_news", "search_news"):
            block.update({
                "count": res.get("count"),
                "on_company_count": res.get("on_company_count"),
                "flag_breakdown": _flag_breakdown(res.get("results")),
            })

        if block:
            prov[tool] = block
    return prov


# --------------------------------------------------------------------------- #
async def run(query: str, *, model_name: str = DEFAULT_MODEL) -> dict:
    """Answer one news / sentiment / announcements question."""
    return await _base.run_agent(
        server_path=RESEARCH_SERVER,
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
    q = " ".join(sys.argv[1:]) or "what's the market sentiment on TCS right now"
    print(json.dumps(run_sync(q), indent=2, default=str))
