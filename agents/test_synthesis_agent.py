"""Standalone test for agents/synthesis_agent.py.

Not pytest. It runs all THREE specialist agents for real against one company
(TCS - fully data-complete, and Indian IT is the case most likely to show
fundamentals-vs-sentiment divergence), then feeds their REAL outputs into the
Synthesis Agent. No synthetic specialist dicts.

    python agents/test_synthesis_agent.py

Two cases:
  1. all 3 specialists -> full report; checks conflict-surfacing, caveat
     carry-through, per-claim sources.
  2. filings dropped -> checks it still produces a coherent report and says
     plainly what's missing (reuses case 1's fetched outputs, no extra calls).

Needs GROQ_API_KEY + TAVILY_API_KEY + GEMINI_API_KEY + DATABASE_URL + network.
Spawns market-data-mcp / research-mcp / filings-rag-mcp as subprocesses. Heavy:
~3-5 Groq calls per specialist + ~2 synthesis calls; paced for the ~7.5k
tokens/min Groq cap.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
for _n in ("groq", "httpx", "langchain_groq", "google_genai", "google_genai.models"):
    logging.getLogger(_n).setLevel(logging.ERROR)

from agents.filings_agent import run_sync as filings_run  # noqa: E402
from agents.market_data_agent import run_sync as market_run  # noqa: E402
from agents.news_sentiment_agent import run_sync as news_run  # noqa: E402
from agents.synthesis_agent import synthesize_sync  # noqa: E402
from shared import llm_rate_limiter as rl  # noqa: E402

_GAP = float(os.environ.get("SYNTH_TEST_GAP_S", "40"))
_failures: list[str] = []


def _norm(s: str) -> str:
    return (s or "").replace("‐", "-").replace("‑", "-").replace("–", "-").lower()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(t: str) -> None:
    print("\n" + "=" * 82 + f"\n{t}\n" + "=" * 82)


def show_specialist(name: str, r: dict) -> None:
    print(f"\n  --- {name} ---")
    if "error" in r:
        print(f"    !! error: {r['error'][:160]}")
        return
    print(f"    ticker/company : {r.get('ticker')} / {r.get('company')}")
    print(f"    tools_called   : {r.get('tools_called')}")
    print(f"    summary        : {r.get('summary')}")
    for f in r.get("findings", []):
        print(f"      - {f}")
    for c in r.get("caveats", []):
        print(f"      ! {c}")


def show_report(r: dict) -> None:
    if "error" in r:
        print(f"  !! synthesis error: {r['error']}")
        print(f"     inputs_received: {r.get('inputs_received')}")
        return
    print("  reasoning trace:")
    for s in r.get("reasoning_trace", []):
        print(f"    . {json.dumps(s, default=str)}")
    print(f"\n  companies         : {r.get('companies')}")
    print(f"  specialists_used  : {r.get('specialists_used')}")
    print(f"\n  EXECUTIVE SUMMARY :\n    {r.get('executive_summary')}")
    print("\n  SECTIONS:")
    for k, v in r.get("sections", {}).items():
        print(f"    [{k}]\n      {v}")
    print("\n  CONFLICTS FLAGGED:")
    for c in r.get("conflicts_flagged", []):
        print(f"    * {c.get('topic')}")
        print(f"        {c.get('specialist_a')}: {c.get('position_a')}")
        print(f"        {c.get('specialist_b')}: {c.get('position_b')}")
        print(f"        => {c.get('assessment')}")
    if not r.get("conflicts_flagged"):
        print("    (none)")
    print("\n  OVERALL CAVEATS:")
    for c in r.get("overall_caveats", []):
        print(f"    ! {c}")
    print("\n  MISSING DATA:")
    for m in r.get("missing_data", []):
        print(f"    ? {m}")
    if not r.get("missing_data"):
        print("    (none)")
    print("\n  SOURCES BY CLAIM:")
    for claim, meta in r.get("sources_by_claim", {}).items():
        print(f"    - {claim}")
        print(f"        sources: {meta.get('sources')}")
        print(f"        caveat : {meta.get('caveat')}")


def _report_blob(r: dict) -> str:
    parts = [r.get("executive_summary", "")]
    parts += list(r.get("sections", {}).values())
    parts += r.get("overall_caveats", [])
    parts += r.get("missing_data", [])
    for c in r.get("conflicts_flagged", []):
        parts += [c.get("position_a", ""), c.get("position_b", ""), c.get("assessment", "")]
    for meta in r.get("sources_by_claim", {}).values():
        parts.append(meta.get("caveat") or "")
    return _norm(" ".join(parts))


# --------------------------------------------------------------------------- #
_UPSTREAM_HEDGES = (
    "as_of", "as of", "fiscal year", "fiscal-year", "fy20", "trailing",
    "self-reported", "not calibrated", "sample", "surfaced news",
    "tabular", "flatten", "column-collapse", "column-flatten",
    "roe_source", "computed", "not the nse", "nse/bse", "official feed",
    "one annual report", "single filing", "single annual report", "not a multi-year",
)

COMPANY = "TCS"
TOP_QUERY = (
    "Give me the overall picture on TCS - fundamentals, market sentiment and the "
    "risks it discloses. Is the near-term outlook as strong as the fundamentals?"
)


def gather_specialists() -> dict:
    print("  running market_data_agent ...")
    md = market_run("how is TCS valued compared to its fundamentals?")
    show_specialist("market_data", md)
    time.sleep(_GAP)

    print("\n  running news_sentiment_agent ...")
    ns = news_run("what's the market sentiment on TCS right now?")
    show_specialist("news_sentiment", ns)
    time.sleep(_GAP)

    print("\n  running filings_agent ...")
    fl = filings_run("what are TCS's key disclosed risks?")
    show_specialist("filings", fl)
    time.sleep(_GAP)

    return {"market_data": md, "news_sentiment": ns, "filings": fl}


def test_full(outs: dict) -> None:
    section("CASE 1  ::  synthesize all three specialists")
    r = synthesize_sync(TOP_QUERY, outs)
    show_report(r)

    if "error" in r:
        check("1 synthesis completed", False, r["error"][:100])
        return

    ok_specialists = [k for k, v in outs.items() if isinstance(v, dict) and "error" not in v]
    for key in ("query", "companies", "executive_summary", "sections",
                "conflicts_flagged", "overall_caveats", "missing_data", "sources_by_claim"):
        check(f"1 report has '{key}'", key in r)

    check("1 companies names TCS", any("tcs" in _norm(c) or "tata" in _norm(c) for c in r["companies"]),
          str(r["companies"]))
    check("1 executive_summary is substantial", len(r.get("executive_summary", "")) > 120)
    check("1 sections has all three keys", set(r["sections"]) == {"market_data", "news_sentiment", "filings"})
    check("1 every present specialist has a non-trivial section",
          all(len(r["sections"][k]) > 40 for k in ok_specialists))
    check("1 sources_by_claim non-empty", bool(r["sources_by_claim"]))
    check("1 every claim names at least one source",
          all(m.get("sources") for m in r["sources_by_claim"].values()))
    check("1 claims attribute to real specialists",
          all(any(s.split()[0].strip(":,") in ("market_data", "news_sentiment", "filings")
                  for s in m["sources"])
              for m in r["sources_by_claim"].values()))
    check("1 overall_caveats non-empty", bool(r["overall_caveats"]))

    blob = _report_blob(r)
    hits = [h for h in _UPSTREAM_HEDGES if h in blob]
    check("1 report preserves upstream hedges (not just confident phrasing)",
          len(hits) >= 2, f"found: {hits}")
    claim_caveats = [m["caveat"] for m in r["sources_by_claim"].values() if m.get("caveat")]
    check("1 at least one claim carries an explicit caveat", bool(claim_caveats),
          f"{len(claim_caveats)} of {len(r['sources_by_claim'])} claims")

    check("1 missing_data does not claim a present specialist is missing",
          not any("not provided" in _norm(m) and any(k in _norm(m) for k in ok_specialists)
                  for m in r["missing_data"]),
          str(r["missing_data"]))

    # conflict surfacing is data-dependent; report it, and require it when the
    # sentiment specialist actually landed a non-positive read against fundamentals.
    ns_out = outs.get("news_sentiment", {})
    ns_blob = _norm(" ".join(ns_out.get("findings", []) + [ns_out.get("summary", "")]))
    leans_negative = ("negative" in ns_blob or "cautious" in ns_blob or "weak" in ns_blob
                      or "muted" in ns_blob or "decline" in ns_blob or "concern" in ns_blob)
    print(f"\n  [info] conflicts_flagged: {len(r['conflicts_flagged'])}   "
          f"news leans negative/cautious: {leans_negative}")
    if leans_negative and "market_data" in ok_specialists and "news_sentiment" in ok_specialists:
        check("1 surfaced the fundamentals-vs-sentiment tension",
              bool(r["conflicts_flagged"])
              and any("sentiment" in _norm(c.get("topic", "") + c.get("position_a", "")
                                          + c.get("position_b", "") + c.get("assessment", ""))
                      for c in r["conflicts_flagged"]))
    else:
        check("1 conflicts_flagged is a list (no forced tension in this data)",
              isinstance(r["conflicts_flagged"], list))


def test_partial(outs: dict) -> None:
    section("CASE 2  ::  synthesize with filings DROPPED (partial-failure handling)")
    partial = {k: v for k, v in outs.items() if k != "filings"}
    r = synthesize_sync(TOP_QUERY, partial)
    show_report(r)

    if "error" in r:
        check("2 synthesis completed on the partial set", False, r["error"][:100])
        return

    check("2 still produced an executive summary", len(r.get("executive_summary", "")) > 120)
    check("2 specialists_used excludes filings", "filings" not in r.get("specialists_used", []))
    check("2 missing_data calls out filings",
          any("filings" in _norm(m) for m in r["missing_data"]), str(r["missing_data"]))
    check("2 filings section marked unavailable",
          _norm(r["sections"].get("filings", "")).startswith("not available"),
          r["sections"].get("filings", "")[:80])
    check("2 market_data + news_sentiment sections still populated",
          len(r["sections"].get("market_data", "")) > 40 and len(r["sections"].get("news_sentiment", "")) > 40)
    invented = [c for c, m in r["sources_by_claim"].items()
                if any("filings" in s.lower() for s in m["sources"])]
    check("2 did not invent filings-sourced claims", not invented,
          f"claims citing absent filings: {invented}" if invented else "")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"model chain primary = {os.environ.get('GROQ_AGENT_MODEL', 'openai/gpt-oss-120b')}")
    print(f"limiter snapshot at start: {json.dumps(rl.snapshot())}")

    section(f"GATHERING SPECIALISTS  ::  {COMPANY}")
    outs = gather_specialists()

    n_ok = sum(1 for v in outs.values() if isinstance(v, dict) and "error" not in v)
    print(f"\n  specialists that succeeded: {n_ok}/3")
    if n_ok == 0:
        print("  !! all specialists errored (quota?) - cannot test synthesis. Re-run later.")
        sys.exit(1)

    test_full(outs)
    time.sleep(_GAP)
    test_partial(outs)

    section("SUMMARY")
    print(f"limiter snapshot at end: {json.dumps(rl.snapshot())}")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        sys.exit(1)
    print("\n  all checks passed")
    sys.exit(0)
