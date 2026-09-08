"""Standalone test for agents/filings_agent.py.

Not pytest - drives the agent against three reasoning patterns and prints, for
each: the reasoning trace, then the full structured output (findings, CAVEATS,
statement_basis, provenance, summary). Then assertions on tool choice AND on
whether the agent actually respected filings-rag-mcp's caveats - page citations
on every filing fact, the flattened-table hedge, and the honest single-filing
scope of compare_yoy_metrics - rather than dressing raw chunks in prose.

    python agents/test_filings_agent.py

Needs GROQ_API_KEY + GEMINI_API_KEY (query embedding) + DATABASE_URL + network.
Spawns filings-rag-mcp as a subprocess. Requires RELIANCE, TCS and M&M to be
ingested. Groq reasoning + one Gemini embedding call per retrieval.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
for _n in ("groq", "httpx", "langchain_groq", "google_genai", "google_genai.models"):
    logging.getLogger(_n).setLevel(logging.ERROR)

from agents.filings_agent import run_sync  # noqa: E402
from shared import llm_rate_limiter as rl  # noqa: E402

_failures: list[str] = []

# a page cite: "p.142", "p 142", "page 142", "pp. 140-142"
_PAGE_RE = re.compile(r"(p{1,2}\.?\s?\d+|page[s]?\s+\d+)", re.I)
# a finding that isn't a filing fact (a "not found" statement) needs no page
_NEGATION_RE = re.compile(
    r"(not found|not disclose|does not|did not|no .*(mention|reference|disclosure|figure)|"
    r"not (stated|available|present|provided|retrieved)|could not find)", re.I
)


def _norm(s: str) -> str:
    """Groq models emit Unicode hyphens/dashes (U+2010/2011/2013); fold them to
    ASCII '-' so substring checks like 'not a cross-filing' actually match."""
    return (s or "").replace("‐", "-").replace("‑", "-").replace("–", "-").lower()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(t: str) -> None:
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


def show(r: dict) -> None:
    if "error" in r:
        print(f"  !! agent error: {r['error']}")
        if r.get("tools_called"):
            print(f"     tools before error: {r['tools_called']}")
        return
    print("  reasoning trace:")
    for s in r.get("reasoning_trace", []):
        if s["step"] == "tool_call":
            print(f"    -> call  {s['tool']}({s['args']})")
        elif s["step"] == "tool_result":
            print(f"    <- result {s['tool']}  ({s['chars']} chars)")
        elif s["step"] == "agent_answer":
            print(f"    == answer: {s['text'][:220]}")
    print(f"\n  ticker/company : {r.get('ticker')}  /  {r.get('company')}   FY {r.get('fiscal_year')}")
    print(f"  statement_basis: {r.get('statement_basis')}")
    print(f"  tools_called   : {r['tools_called']}")
    print(f"  summary        : {r['summary']}")
    print("  findings:")
    for f in r["findings"]:
        print(f"    - {f}")
    print("  caveats:")
    for c in r.get("caveats", []):
        print(f"    ! {c}")
    print("  provenance:")
    print("    " + json.dumps(r.get("provenance", {}), default=str, indent=2).replace("\n", "\n    "))
    print("  raw_data keys  : " + ", ".join(r.get("raw_data", {})))
    # prove full chunk text survived the trimming, for citation
    for tool, res in r.get("raw_data", {}).items():
        if isinstance(res, dict) and res.get("results"):
            longest = max((len(h.get("text", "")) for h in res["results"] if isinstance(h, dict)), default=0)
            print(f"    raw_data[{tool}]: {len(res['results'])} chunks, longest text {longest} chars")


def _findings_are_cited(findings: list[str]) -> tuple[bool, list[str]]:
    bad = [f for f in findings if not _PAGE_RE.search(f) and not _NEGATION_RE.search(f)]
    return (not bad), bad


# --------------------------------------------------------------------------- #
def test_semantic_risks() -> None:
    section('1. semantic  ::  "what are Reliance\'s key disclosed risks"')
    r = run_sync("what are Reliance's key disclosed risks")
    show(r)
    if "error" in r:
        check("1 completed", False, r["error"][:90])
        return
    called = set(r["tools_called"])
    check("1 used search_filing", "search_filing" in called, f"called {sorted(called)}")
    check("1 did NOT call statement/yoy tools",
          not (called & {"get_financial_statement_section", "compare_yoy_metrics"}),
          f"called {sorted(called)}")
    check("1 produced findings", bool(r["findings"]))
    ok, bad = _findings_are_cited(r["findings"])
    check("1 every filing finding cites a page", ok, f"un-cited: {bad}" if bad else "")
    prov = r.get("provenance", {}).get("search_filing", {})
    check("1 provenance carries the retrieved pages", bool(prov.get("pages")), str(prov.get("pages")))
    check("1 ticker/company resolved", r.get("ticker") in ("RELIANCE", "RELIANCE.NS") and bool(r.get("company")))


def test_income_statement() -> None:
    section('2. statement  ::  "what was TCS\'s revenue and profit for the year, from the income statement"')
    r = run_sync("what was TCS's revenue and profit for the year, from the income statement")
    show(r)
    if "error" in r:
        check("2 completed", False, r["error"][:90])
        return
    called = set(r["tools_called"])
    check("2 called get_financial_statement_section", "get_financial_statement_section" in called,
          f"called {sorted(called)}")
    raw = r.get("raw_data", {}).get("get_financial_statement_section", {})
    check("2 asked for the income statement", raw.get("statement_type") == "income_statement",
          f"statement_type={raw.get('statement_type')}")
    ok, bad = _findings_are_cited(r["findings"])
    check("2 every figure finding cites a page", ok, f"un-cited: {bad}" if bad else "")
    blob = _norm(" ".join(r["findings"] + r.get("caveats", []) + [r.get("summary", "")]))
    check("2 flags standalone vs consolidated (in findings/caveats/basis)",
          any(w in blob for w in ("standalone", "consolidated"))
          or r.get("statement_basis") in ("standalone", "consolidated", "mixed"),
          f"statement_basis={r.get('statement_basis')}")
    caveats_blob = _norm(" ".join(r.get("caveats", [])))
    check("2 a caveat says it's search-based / not a parsed statement, or flags table-flattening",
          any(w in caveats_blob for w in ("search-based", "not a parsed", "parsed statement",
                                          "flatten", "column-collapse", "column-flatten", "tabular")),
          caveats_blob[:160])
    check("2 caveats non-empty", bool(r.get("caveats")))


def test_yoy_scope() -> None:
    section('3. yoy scope  ::  "how has M&M\'s EBITDA changed year over year"')
    r = run_sync("how has M&M's EBITDA changed year over year")
    show(r)
    if "error" in r:
        check("3 completed", False, r["error"][:90])
        return
    called = set(r["tools_called"])
    check("3 called compare_yoy_metrics", "compare_yoy_metrics" in called, f"called {sorted(called)}")
    prov = r.get("provenance", {}).get("compare_yoy_metrics", {})
    check("3 provenance carries basis + limitation", "basis" in prov and "limitation" in prov,
          f"keys={sorted(prov)}")
    ok, bad = _findings_are_cited(r["findings"])
    check("3 every filing finding cites a page", ok, f"un-cited: {bad}" if bad else "")
    blob = _norm(" ".join(r["findings"] + r.get("caveats", []) + [r.get("summary", "")]))
    check("3 is upfront this is NOT a true multi-year / cross-filing trend",
          any(p in blob for p in ("one annual report", "single filing", "single annual report",
                                  "cross-filing", "not a multi-year", "not a true multi-year",
                                  "only one year", "single year-on-year", "one year-over-year",
                                  "one year-on-year", "prior-year column", "one report per company",
                                  "not a cross")),
          blob[:200])
    check("3 caveats non-empty", bool(r.get("caveats")))


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"model chain primary = {os.environ.get('GROQ_AGENT_MODEL', 'openai/gpt-oss-120b')}")
    print(f"limiter snapshot at start: {json.dumps(rl.snapshot())}")

    # Groq's ~7.5k tokens/min bucket is shared across the model chain; the
    # retrieval chunks make each ReAct turn heavy, so pace the queries well apart.
    _gap = float(os.environ.get("GROQ_TEST_GAP_S", "90"))
    test_semantic_risks()
    time.sleep(_gap)
    test_income_statement()
    time.sleep(_gap)
    test_yoy_scope()

    section("SUMMARY")
    print(f"limiter snapshot at end: {json.dumps(rl.snapshot())}")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        sys.exit(1)
    print("\n  all checks passed")
    sys.exit(0)
