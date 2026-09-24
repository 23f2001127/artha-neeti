"""Follow-up agent: answers a question about a finished report, or explains why
it can't.

One structured-output call over the report and the conversation so far. When
the report covers the question, the answer is grounded only in it and keeps its
caveats. When it doesn't, the response says what is missing and includes a
``standalone_query`` (references like "its" resolved) that can start a new
research run. Doing both in one call keeps a follow-up to a single LLM request.

    from agents.followup_agent import answer_followup
    result = answer_followup(original_query, report, prior_turns, "and its ROE?")
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from agents import _base
from agents._base import DEFAULT_MODEL

_STR_CAP = 500  # per-string cap when compacting report content into the prompt
_MAX_PRIOR_TURNS = 8  # older turns are dropped rather than let the prompt grow unbounded


# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = """You are the Follow-up Agent for ArthaNeeti, an Indian-equity \
research system. A user already received a research report; they are now asking \
a follow-up question in the same conversation.

You do NOT fetch anything new and you do NOT have live/current data - you only \
have the finished report given to you (and the prior follow-up turns in this \
conversation, for resolving references like "it" or "that company").

DECIDE ONE THING FIRST: can this follow-up be answered from the given report \
content alone?

IF YES (sufficient_data = true):
- Answer directly and only from the report. Never invent a number, company, or \
fact that isn't in it.
- If the report hedged a fact you're using (e.g. "may be column-flattened", \
"self-reported sentiment", "different fiscal year"), carry that hedge into your \
answer's `caveat` - do not launder a hedged finding into a confident one.
- Keep the answer conversational and short - a few sentences, not a re-statement \
of the whole report.

IF NO (sufficient_data = false) - this includes: the question is about a company \
not in this report, a metric/detail the report doesn't disclose, or something \
that genuinely needs FRESH/current data (the report's data has an as-of point in \
time and may already be stale for what's being asked):
- Say plainly, in `missing_reason`, what's missing and why the existing report \
can't answer it.
- Produce `standalone_query`: a complete, self-contained research question that \
captures what the user actually wants, with every reference to earlier turns \
resolved (e.g. if the user says "what about its main competitor" and the \
conversation was about TCS, the standalone query names the competitor or asks \
to identify and research TCS's main competitor explicitly - never leave a bare \
pronoun in it). This will be run as a brand-new research query with NO memory of \
this conversation, so it must stand entirely on its own.

Never do both - either answer fully from the report, or hand back a standalone \
query. Never guess to avoid saying something is missing."""


class _FollowupAnswer(BaseModel):
    sufficient_data: bool = Field(
        description="true if the given report content is enough to answer this follow-up directly"
    )
    answer: str | None = Field(
        default=None, description="the answer, grounded ONLY in the given report - set when sufficient_data is true"
    )
    caveat: str | None = Field(
        default=None, description="strongest relevant hedge carried from the report, or null if genuinely unhedged"
    )
    missing_reason: str | None = Field(
        default=None,
        description="plain-language explanation of what's missing - set when sufficient_data is false",
    )
    standalone_query: str | None = Field(
        default=None,
        description="a fully self-contained research query with all references resolved - "
        "set when sufficient_data is false",
    )


# --------------------------------------------------------------------------- #
def _trim(obj: Any) -> Any:
    """Same capping rule as synthesis_agent._trim - a report's already-distilled
    content is small, but a multi-company comparison can still add up."""
    if isinstance(obj, str):
        return obj if len(obj) <= _STR_CAP else obj[:_STR_CAP] + "…"
    if isinstance(obj, dict):
        return {k: _trim(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_trim(v) for v in obj[:20]]
    return obj


def _compact_report(report: dict) -> dict:
    """The report's load-bearing content for grounding a follow-up - the same
    fields the frontend's ReportView actually shows a user, not internal
    routing/trace detail that isn't relevant to answering a question about
    findings."""
    reports = report.get("reports") or {}
    per_company = {}
    for ticker, r in reports.items():
        if not isinstance(r, dict) or "error" in r:
            per_company[ticker] = {"status": "unavailable", "reason": str((r or {}).get("error"))[:200]}
            continue
        per_company[ticker] = _trim({
            "company": (r.get("companies") or [ticker])[0] if r.get("companies") else ticker,
            "executive_summary": r.get("executive_summary"),
            "sections": r.get("sections"),
            "key_claims": list((r.get("sources_by_claim") or {}).keys()),
            "sources_by_claim": r.get("sources_by_claim"),
            "conflicts_flagged": r.get("conflicts_flagged"),
            "overall_caveats": r.get("overall_caveats"),
            "missing_data": r.get("missing_data"),
        })
    out: dict[str, Any] = {
        "mode": report.get("mode"),
        "companies_covered": list(reports.keys()),
        "per_company": per_company,
    }
    if report.get("comparison"):
        out["comparison"] = _trim(report["comparison"])
    return out


def _compact_prior_turns(prior_turns: list[dict]) -> list[dict]:
    out = []
    for t in prior_turns[-_MAX_PRIOR_TURNS:]:
        out.append({
            "question": t.get("query"),
            "answer": t.get("answer") or f"(needed fresh research: {t.get('missing_reason')})",
        })
    return out


# --------------------------------------------------------------------------- #
async def answer_followup(
    original_query: str,
    report: dict,
    prior_turns: list[dict],
    follow_up_query: str,
    *,
    model_name: str = DEFAULT_MODEL,
) -> dict:
    """Answer one follow-up question against a finished job's report. See
    module docstring for the sufficient_data / standalone_query contract."""
    if not follow_up_query or not follow_up_query.strip():
        return {"error": "follow-up question is empty."}
    if not isinstance(report, dict) or not report.get("reports"):
        return {"error": "no usable report to follow up on."}

    payload = {
        "original_query": original_query,
        "report": _compact_report(report),
        "prior_conversation_turns": _compact_prior_turns(prior_turns),
    }
    msgs = [
        _base.SystemMessage(_SYSTEM_PROMPT),
        _base.HumanMessage(
            f"CONTEXT (JSON):\n{_base.prompt_json(payload)}\n\n"
            f"NEW FOLLOW-UP QUESTION:\n{follow_up_query.strip()}"
        ),
    ]

    try:
        model = _base.make_model(model_name, max_tokens=1200)
        structured = model.with_structured_output(_FollowupAnswer)
        result = await structured.ainvoke(msgs)
        if isinstance(result, dict):
            result = _FollowupAnswer(**result)
    except BaseException as exc:  # noqa: BLE001 - unwrap anyio/limiter groups
        return {"error": _base.describe_error(exc)}

    if result.sufficient_data and not (result.answer or "").strip():
        # A model that says "yes I can answer" but returns nothing is really a
        # "no" - treat it as insufficient rather than showing an empty answer.
        return {
            "sufficient_data": False,
            "missing_reason": "the model did not produce an answer despite marking the report sufficient.",
            "standalone_query": follow_up_query.strip(),
        }

    return {
        "sufficient_data": result.sufficient_data,
        "answer": result.answer,
        "caveat": result.caveat,
        "missing_reason": result.missing_reason,
        "standalone_query": result.standalone_query,
        "model": model_name,
    }


def answer_followup_sync(
    original_query: str,
    report: dict,
    prior_turns: list[dict],
    follow_up_query: str,
    *,
    model_name: str = DEFAULT_MODEL,
) -> dict:
    """Blocking wrapper around :func:`answer_followup` for scripts."""
    return asyncio.run(answer_followup(original_query, report, prior_turns, follow_up_query, model_name=model_name))
