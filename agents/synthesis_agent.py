"""Synthesis agent: merges the specialists' outputs into one cited report.

Unlike the specialists it has no MCP server or ReAct loop; it takes their
finished outputs and makes one structured-output call:

    synthesize(query, {"market_data": out, "news_sentiment": out, "filings": out}) -> dict

The report surfaces disagreement between sources in ``conflicts_flagged`` (and
judges whether it is a contradiction or a difference of lens, such as different
fiscal years), carries each claim's strongest upstream caveat, and attributes
every claim to its sources in ``sources_by_claim``. Missing or failed
specialists are reported in ``unavailable`` rather than guessed around.
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Any

from pydantic import BaseModel, Field

from agents import _base
from agents._base import DEFAULT_MODEL

SPECIALIST_KEYS = ("market_data", "news_sentiment", "filings")
_STR_CAP = 600  # per-string cap when compacting a specialist's provenance


# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = """You are the Synthesis Agent for ArthaNeeti, an Indian-equity \
research system. You receive the finished structured outputs of up to three \
specialist agents and merge them into ONE cited research report:
- market_data: valuation, ratios, price (from yfinance, usually the latest FY).
- news_sentiment: recent news, aggregate sentiment, corporate announcements.
- filings: the company's own annual-report disclosures (ONE fixed year:
  FY2024-25, or FY2025-26 for TCS).

You do NOT fetch anything. You reconcile and report on exactly what you are given.

CORE RULES:
1. SURFACE DISAGREEMENT - do not average it away. If two specialists point \
different ways (strong fundamentals vs negative sentiment; a filing risk recent \
news is / isn't covering; a figure two specialists state differently), put it in \
conflicts_flagged AND judge it: a real contradiction, or different lenses \
(trailing performance vs one recent event; different fiscal years; a news sample \
vs the whole market)?
2. FISCAL-YEAR VINTAGE. market_data (yfinance, often ~FY2026) and filings (one \
fixed annual report, FY2024-25 / TCS FY2025-26) are frequently DIFFERENT YEARS. \
Never merge a market_data figure and a filings figure into one comparison without \
stating the period gap. Read each specialist's provenance for as_of / fiscal_year.
3. CARRY THE STRONGEST CAVEAT. Every specialist already hedged. When you repeat a \
claim, attach the strongest hedge that applied to it upstream - never upgrade a \
hedged finding to a confident one. Hedges to keep when relevant: filings \
"may_contain_tabular_data / numbers may be column-flattened by PDF extraction"; \
filings "one annual report only, not a multi-year trend"; news \
"get_corporate_announcements is NOT the NSE/BSE official feed"; news "aggregate \
sentiment score is self-reported, not calibrated, and is a sample of surfaced \
news"; market_data "roe_source (computed vs reported)" and "as_of / fiscal_year".
4. ATTRIBUTE. Every material claim names the specialist(s) it came from; if it \
rests on one specific article or filing page, name that too.
5. WORK WITH WHAT YOU HAVE. If a specialist is missing or errored, build the \
report from the rest and state in missing_data what is absent and what that means \
you cannot cover. Never guess to fill the gap.

Never introduce a fact or number that is not in the specialist outputs."""

_INSTRUCTIONS = """Produce the research report as structured output.

companies: the company / companies the report is about (display names).
executive_summary: 3-6 sentences - the bottom line a reader needs, INCLUDING the \
main tension if there is one. Do not overstate confidence.
market_data_section / news_sentiment_section / filings_section: 2-4 sentences \
each, grounded in that specialist's findings. If that specialist is missing or \
errored, set the field to "Not available - <one-line reason>".
key_claims: up to 6 of the report's load-bearing claims. Each:
  - claim: one sentence.
  - sources: a COMMA-SEPARATED string of specialist name(s) - e.g. "market_data" \
or "news_sentiment, filings"; append a specific article + date or a page number \
where the claim rests on one.
  - caveat: the strongest upstream hedge on this claim, or null if genuinely \
unhedged. Do not leave it null just because it is inconvenient.
conflicts_flagged: one entry per genuine cross-specialist tension (topic, \
specialist_a, position_a, specialist_b, position_b, assessment). The assessment \
says whether it is a real contradiction or different lenses, and why. Empty list \
ONLY if the specialists genuinely agree or do not overlap.
overall_caveats: hedges that apply to the whole report - the data-vintage gap \
between market_data and filings, sentiment being a non-exhaustive sample, filings \
being a single year, any specialist that returned thin data. Non-empty whenever \
any specialist carried caveats.
missing_data: each absent / errored specialist and what the report therefore \
cannot cover; plus within-specialist gaps a specialist itself flagged (market_data \
"missing" fields, filings "metric not disclosed", etc.).

Everything except key_claims.sources and the specialist_a / specialist_b fields is \
read by investors: refer to sources as "market data", "news coverage" or "the annual \
report", never by internal names (market_data, news_sentiment, filings), tool names \
(get_ratios) or field names (as_of, may_contain_tabular_data); write dates as \
"21 Sep 2026", not timestamps."""


# --------------------------------------------------------------------------- #
class _Claim(BaseModel):
    claim: str = Field(description="one-sentence load-bearing claim")
    # a COMMA-joined string, not a list - a list nested inside a list of objects is
    # what tips gpt-oss into a degenerate generation. Split back to a list on output.
    sources: str = Field(
        description="specialist name(s), comma-separated (market_data, news_sentiment, "
        "filings); append an article+date or page number where the claim rests on one"
    )
    caveat: str | None = Field(
        default=None, description="strongest upstream hedge on this claim, or null if genuinely unhedged"
    )


class _Conflict(BaseModel):
    topic: str = Field(description="what the specialists disagree about")
    specialist_a: str
    position_a: str
    specialist_b: str
    position_b: str
    assessment: str = Field(
        description="real contradiction, or different lenses (trailing vs recent, "
        "different fiscal years, sample vs whole)? say which and why"
    )


class _SynthesisReport(BaseModel):
    companies: list[str]
    executive_summary: str
    market_data_section: str | None = None
    news_sentiment_section: str | None = None
    filings_section: str | None = None
    key_claims: list[_Claim]
    conflicts_flagged: list[_Conflict]
    overall_caveats: list[str]
    missing_data: list[str]


# --------------------------------------------------------------------------- #
def _trim(obj: Any) -> Any:
    """Cap strings and list lengths so a specialist's provenance can't bloat the
    synthesis prompt. The specialists already distilled raw_data into findings, so
    raw_data is dropped entirely upstream of this."""
    if isinstance(obj, str):
        return obj if len(obj) <= _STR_CAP else obj[:_STR_CAP] + "…"
    if isinstance(obj, dict):
        return {k: _trim(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_trim(v) for v in obj[:25]]
    return obj


def _compact_specialist(name: str, out: Any) -> dict:
    """One specialist's output, shrunk to what synthesis actually needs: its
    distilled findings + caveats + summary + provenance. raw_data is not passed."""
    if not isinstance(out, dict):
        return {"specialist": name, "status": "failed", "reason": "no output object"}
    if "error" in out:
        return {
            "specialist": name,
            "status": "failed",
            "reason": str(out["error"])[:300],
            "tools_called": out.get("tools_called") or [],
        }
    findings = list(out.get("findings") or [])
    block: dict[str, Any] = {
        "specialist": name,
        "status": "ok" if findings else "thin",
        "ticker": out.get("ticker"),
        "company": out.get("company"),
        "summary": out.get("summary"),
        "findings": findings,
        "caveats": list(out.get("caveats") or []),
        "provenance": _trim(out.get("provenance") or {}),
        "tools_called": out.get("tools_called") or [],
    }
    for k in ("fiscal_year", "statement_basis"):
        if out.get(k) is not None:
            block[k] = out[k]
    return block


def _classify(specialist_outputs: dict | None) -> tuple[dict, dict, list[str]]:
    """Split the given outputs into ok / failed / missing."""
    outputs = specialist_outputs or {}
    ok: dict[str, Any] = {}
    failed: dict[str, Any] = {}
    missing: list[str] = []
    for key in SPECIALIST_KEYS:
        out = outputs.get(key)
        if out is None:
            missing.append(key)
        elif isinstance(out, dict) and "error" in out:
            failed[key] = out
        else:
            ok[key] = out
    for key, out in outputs.items():  # tolerate extra specialist keys
        if key not in SPECIALIST_KEYS and isinstance(out, dict):
            (failed if "error" in out else ok)[key] = out
    return ok, failed, missing


_GEN_FAILURE_MARKERS = ("tool_use_failed", "failed to call a function", "failed_generation",
                        "json decode", "jsondecodeerror", "validationerror", "outputparserexception")


def _looks_like_gen_failure(exc: BaseException) -> bool:
    t = f"{type(exc).__name__} {exc}".lower()
    return any(m in t for m in _GEN_FAILURE_MARKERS)



# Commas inside a citation's parentheses ("news_sentiment (site, date)") are not separators.
_SOURCE_SPLIT_RE = re.compile(r",(?![^()]*\))")

_SECTION_NAMES = {
    "market_data": "Market data",
    "news_sentiment": "News coverage",
    "filings": "Annual-report analysis",
}


def _unavailable_reason(error: Any) -> str:
    """User-facing reason a specialist's section is missing; never the raw exception."""
    text = str(error or "").lower()
    if "rate limit" in text or "quota" in text:
        return "The data provider's usage limit was reached during this run."
    if "too large" in text:
        return "The source material was too large to process in this run."
    return "This source could not be retrieved during this run."


async def _invoke_structured(structured, msgs: list, attempts: int = 4) -> _SynthesisReport:
    """A structured-output call that survives a degenerate generation. Groq's
    gpt-oss models occasionally loop a token run until the function-call JSON is
    malformed ('tool_use_failed'); a retry (which also rotates the model via the
    RateLimitedChatGroq fallback chain) usually lands cleanly. On the last attempt
    the nudge asks for a deliberately compact object."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            report = await structured.ainvoke(msgs)
            return _SynthesisReport(**report) if isinstance(report, dict) else report
        except BaseException as exc:  # noqa: BLE001
            last = exc
            if not _looks_like_gen_failure(exc) or i == attempts - 1:
                raise
            msgs = msgs + [_base.HumanMessage(
                "Your previous attempt produced malformed output. Return a COMPACT, "
                "valid object: <=6 key_claims, <=3 conflicts_flagged, <=5 "
                "overall_caveats, short strings, no repeated keys."
            )]
    raise last  # unreachable


async def _run_synthesis(model, query: str, payload: str) -> _SynthesisReport:
    structured = model.with_structured_output(_SynthesisReport)
    msgs = [
        _base.SystemMessage(_SYSTEM_PROMPT),
        _base.HumanMessage(
            f"ORIGINAL USER QUERY:\n{query}\n\n"
            f"SPECIALIST OUTPUTS (JSON):\n{payload}\n\n{_INSTRUCTIONS}"
        ),
    ]
    report = await _invoke_structured(structured, msgs)

    es = (report.executive_summary or "").strip().lower()
    if not es or any(p in es for p in ("were not provided", "no specialist", "no data was provided")):
        report = await _invoke_structured(structured, msgs + [_base.HumanMessage(
            "The SPECIALIST OUTPUTS above are real and populated. Write the report "
            "strictly from them; do not claim they are empty."
        )])
    return report


# --------------------------------------------------------------------------- #
async def synthesize(
    query: str,
    specialist_outputs: dict[str, dict],
    *,
    model_name: str = DEFAULT_MODEL,
) -> dict:
    """Merge specialist outputs into one cited report. See module docstring."""
    if not query or not query.strip():
        return {"query": query, "error": "query is empty."}

    ok, failed, missing = _classify(specialist_outputs)
    if not ok:
        return {
            "query": query,
            "error": "no usable specialist outputs to synthesize.",
            "missing_data": [f"{k}: not provided" for k in missing]
            + [f"{k}: errored ({str(v.get('error'))[:120]})" for k, v in failed.items()],
        }

    compacted = [_compact_specialist(k, ok[k]) for k in ok] + [
        _compact_specialist(k, failed[k]) for k in failed
    ]
    payload = _base.prompt_json(compacted)
    trace: list[dict] = [{
        "step": "inputs",
        "ok": sorted(ok),
        "failed": sorted(failed),
        "missing": sorted(missing),
        "payload_chars": len(payload),
    }]

    try:
        # max_tokens caps a degenerate generation - a gpt-oss token-run loop
        # truncates (-> parse error -> retry) instead of running forever.
        model = _base.make_model(model_name, max_tokens=3500)
        report = await _run_synthesis(model, query, payload)
    except BaseException as exc:  # noqa: BLE001 - unwrap anyio/limiter groups
        return {
            "query": query,
            "error": _base.describe_error(exc),
            "inputs_received": {"ok": sorted(ok), "failed": sorted(failed), "missing": sorted(missing)},
        }

    # --- assemble the requested output shape -------------------------------- #
    section_fields = {
        "market_data": report.market_data_section,
        "news_sentiment": report.news_sentiment_section,
        "filings": report.filings_section,
    }
    sections: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    for key, field in section_fields.items():
        if key in ok:
            sections[key] = (field or "").strip() or (ok[key].get("summary") or "")
        elif key in failed:
            unavailable[key] = _unavailable_reason(failed[key].get("error"))
        else:
            unavailable[key] = "Not part of this analysis."

    sources_by_claim = {
        c.claim: {
            "sources": [s.strip() for s in _SOURCE_SPLIT_RE.split(c.sources or "") if s.strip()],
            "caveat": c.caveat,
        }
        for c in report.key_claims
    }

    missing_data = list(report.missing_data or [])
    for k in missing:
        if not any(k in m for m in missing_data):
            missing_data.append(f"{_SECTION_NAMES.get(k, k)} is not part of this analysis.")
    for k, v in failed.items():
        if not any(k in m for m in missing_data):
            missing_data.append(f"{_SECTION_NAMES.get(k, k)}: {_unavailable_reason(v.get('error'))}")

    trace.append({
        "step": "synthesis_report",
        "model": model_name,
        "claims": len(report.key_claims),
        "conflicts_flagged": len(report.conflicts_flagged),
        "overall_caveats": len(report.overall_caveats),
    })

    return {
        "query": query,
        "companies": report.companies,
        "executive_summary": report.executive_summary,
        "sections": sections,
        "unavailable": unavailable,
        "conflicts_flagged": [c.model_dump() for c in report.conflicts_flagged],
        "overall_caveats": report.overall_caveats,
        "missing_data": missing_data,
        "sources_by_claim": sources_by_claim,
        "specialists_used": sorted(ok),
        "reasoning_trace": trace,
        "model": model_name,
    }


def synthesize_sync(
    query: str, specialist_outputs: dict[str, dict], *, model_name: str = DEFAULT_MODEL
) -> dict:
    """Blocking wrapper around :func:`synthesize` for scripts / the Planner node."""
    return asyncio.run(synthesize(query, specialist_outputs, model_name=model_name))


if __name__ == "__main__":
    print(
        "synthesis_agent takes already-gathered specialist outputs, not a query alone.\n"
        "Run agents/test_synthesis_agent.py for a real end-to-end example.",
        file=sys.stderr,
    )
