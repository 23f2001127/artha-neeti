"""Standalone test for agents/planner.py - the LangGraph orchestrator.

Drives the real end-to-end pipeline against four query shapes and prints, for
each: the routing decision + rationale, the routing trace, the graph path, the
per-company synthesis report(s), and (multi-company) the comparison. Then
assertions - weighted heavily toward ROUTING TRANSPARENCY, since that is the
proof this plans rather than guesses.

    python agents/test_planner.py routing   # just _route_node x4 - cheap, ~4 Groq calls
    python agents/test_planner.py 1          # one full end-to-end case (1-4)
    python agents/test_planner.py            # all four end to end (HEAVY)

Cases:
  1. "what's Reliance's current stock price"        -> market_data ONLY
  2. "give me a complete research view on TCS"       -> all three specialists
  3. "give me a full picture on State Bank of India" -> filings SKIPPED (not in corpus)
  4. "compare TCS and Infosys ..."                   -> multi-company + comparison step

The full four-case run is ~50-65 Groq calls + Gemini + Tavily; the free Groq tier
(~7.5k tokens/min, shared) will not reliably sustain that in one sitting, so
prefer `routing` (proves the planning logic) plus individual cases spaced out.
Needs GROQ + TAVILY + GEMINI keys + DATABASE_URL + network.
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
for _n in ("groq", "httpx", "langchain_groq", "google_genai", "google_genai.models", "yfinance"):
    logging.getLogger(_n).setLevel(logging.ERROR)

import asyncio  # noqa: E402

from agents.planner import plan  # noqa: E402
from shared import llm_rate_limiter as rl  # noqa: E402

_GAP = float(os.environ.get("PLANNER_TEST_GAP_S", "60"))
_failures: list[str] = []


def _norm(s: str) -> str:
    return (s or "").replace("‐", "-").replace("‑", "-").replace("–", "-").lower()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(t: str) -> None:
    print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


def show(r: dict) -> None:
    if "error" in r and "routing" not in r:
        print(f"  !! planner returned a bare error: {r['error']}")
        return
    routing = r.get("routing", {})
    print("  ROUTING DECISION:")
    print(f"    mode              : {r.get('mode')}   is_comparison={routing.get('is_comparison')}")
    print(f"    companies         : {[ (c['name'], c['ticker'], 'resolvable' if c['resolvable'] else 'UNRESOLVABLE', 'in-corpus' if c['in_filings_corpus'] else 'no-corpus') for c in r.get('companies', []) ]}")
    print(f"    specialists chosen: {routing.get('specialists_selected')}")
    print("    specialists skipped:")
    for s in routing.get("specialists_skipped", []):
        print(f"       - {s['specialist']}: {s['reason']}")
    print(f"    sub-queries       : {json.dumps(routing.get('sub_queries', {}), default=str)}")
    print(f"    rationale         : {routing.get('rationale')}")
    print("\n  ROUTING TRACE:")
    for line in r.get("routing_trace", []):
        print(f"    | {line}")
    print("\n  GRAPH PATH:")
    for step in r.get("graph_path", []):
        print(f"    -> {step}")
    print(f"\n  SPECIALIST STATUS: {json.dumps(r.get('specialist_status', {}), default=str)}")

    for ticker, rep in r.get("reports", {}).items():
        print(f"\n  ---- REPORT: {ticker} ----")
        if "error" in rep:
            print(f"    !! {rep['error']}")
            continue
        print(f"    executive_summary: {rep.get('executive_summary')}")
        print(f"    conflicts_flagged: {len(rep.get('conflicts_flagged', []))}")
        for c in rep.get("conflicts_flagged", []):
            print(f"       * {c.get('topic')}  =>  {c.get('assessment')}")
        print("    overall_caveats:")
        for c in rep.get("overall_caveats", []):
            print(f"       ! {c}")
        print("    missing_data:")
        for m in rep.get("missing_data", []):
            print(f"       ? {m}")
        print(f"    sources_by_claim ({len(rep.get('sources_by_claim', {}))}):")
        for claim, meta in list(rep.get("sources_by_claim", {}).items())[:4]:
            print(f"       - {claim}\n           {meta.get('sources')}  |  caveat: {meta.get('caveat')}")

    comp = r.get("comparison")
    if comp:
        print("\n  ---- CROSS-COMPANY COMPARISON ----")
        print(f"    verdict: {comp.get('verdict')}")
        for d in comp.get("dimensions", []):
            print(f"    [{d.get('dimension')}]  edge={d.get('edge')}\n        {d.get('assessment')}")
        for c in comp.get("caveats", []):
            print(f"    ! {c}")


def _selected(r: dict) -> set:
    return set(r.get("routing", {}).get("specialists_selected", []))


def _skipped_map(r: dict) -> dict:
    return {s["specialist"]: s["reason"] for s in r.get("routing", {}).get("specialists_skipped", [])}


# --------------------------------------------------------------------------- #
async def case1_price() -> None:
    section('CASE 1  ::  "what\'s Reliance\'s current stock price"  (expect: market_data ONLY)')
    r = await plan("what's Reliance's current stock price")
    show(r)
    if "routing" not in r:
        check("1 routing produced", False, r.get("error", "")[:100]); return
    check("1 mode is single", r.get("mode") == "single", str(r.get("mode")))
    check("1 selected == {market_data}", _selected(r) == {"market_data"}, str(_selected(r)))
    sk = _skipped_map(r)
    check("1 news_sentiment skipped with a reason", "news_sentiment" in sk and len(sk["news_sentiment"]) > 8, sk.get("news_sentiment"))
    check("1 filings skipped with a reason", "filings" in sk and len(sk["filings"]) > 8, sk.get("filings"))
    check("1 only market_data actually ran",
          set().union(*[set(v) for v in r.get("specialist_status", {}).values()] or [set()]) == {"market_data"},
          str(r.get("specialist_status")))
    check("1 graph did NOT enter compare", "compare" not in " ".join(r.get("graph_path", [])))
    check("1 routing_trace is non-empty", len(r.get("routing_trace", [])) >= 2)


async def case2_deepdive() -> None:
    section('CASE 2  ::  "give me a complete research view on TCS"  (expect: all three)')
    r = await plan("give me a complete research view on TCS")
    show(r)
    if "routing" not in r:
        check("2 routing produced", False, r.get("error", "")[:100]); return
    check("2 mode is single", r.get("mode") == "single")
    check("2 all three specialists selected", _selected(r) == {"market_data", "news_sentiment", "filings"}, str(_selected(r)))
    check("2 no specialists skipped", not _skipped_map(r), str(_skipped_map(r)))
    rep = r.get("reports", {}).get("TCS", {})
    check("2 a TCS report was built", bool(rep) and "error" not in rep, rep.get("error", "")[:100])
    check("2 report has a substantial executive_summary", len(rep.get("executive_summary", "")) > 120)
    check("2 report carries overall_caveats", bool(rep.get("overall_caveats")))
    check("2 graph path is route->gather->synthesize->finalize",
          [s.split(":")[0].split(" ")[0] for s in r.get("graph_path", [])][:1] == ["route"]
          and "compare" not in " ".join(r.get("graph_path", [])))


async def case3_no_corpus() -> None:
    section('CASE 3  ::  "full picture on State Bank of India"  (expect: filings SKIPPED - not in corpus)')
    r = await plan("give me a full picture on State Bank of India (SBI)")
    show(r)
    if "routing" not in r:
        check("3 routing produced", False, r.get("error", "")[:100]); return
    comp = next((c for c in r.get("companies", []) if c["ticker"] in ("SBIN", "SBI")), None)
    check("3 resolved SBI to a ticker", comp is not None, str(r.get("companies")))
    if comp:
        check("3 SBI ticker is resolvable on yfinance", comp["resolvable"], comp.get("resolution_note"))
        check("3 SBI is NOT in the filings corpus", not comp["in_filings_corpus"])
    check("3 market_data + news_sentiment were selected", {"market_data", "news_sentiment"}.issubset(_selected(r)), str(_selected(r)))
    check("3 filings NOT selected", "filings" not in _selected(r))
    sk = _skipped_map(r)
    fr = _norm(sk.get("filings", ""))
    check("3 filings skip reason cites the corpus / ingestion", any(w in fr for w in ("corpus", "ingest", "not one of", "annual report")), sk.get("filings"))
    rep = next(iter(r.get("reports", {}).values()), {})
    check("3 a report was still built from the 2 available specialists", bool(rep) and "error" not in rep, rep.get("error", "")[:100])
    if rep and "error" not in rep:
        check("3 report flags filings as missing",
              any("filings" in _norm(m) for m in rep.get("missing_data", [])), str(rep.get("missing_data")))


async def case4_compare() -> None:
    section('CASE 4  ::  "compare TCS and Infosys ..."  (expect: multi-company + comparison)')
    r = await plan("compare TCS and Infosys on fundamentals, sentiment and risk profile")
    show(r)
    if "routing" not in r:
        check("4 routing produced", False, r.get("error", "")[:100]); return
    check("4 mode is multi", r.get("mode") == "multi", str(r.get("mode")))
    tickers = {c["ticker"] for c in r.get("companies", [])}
    check("4 identified TCS and INFY", {"TCS", "INFY"}.issubset(tickers), str(tickers))
    good = [t for t, rep in r.get("reports", {}).items() if "error" not in rep]
    check("4 built >=2 per-company reports", len(good) >= 2, f"good={good}")
    comp = r.get("comparison")
    check("4 a comparison was produced", bool(comp), "comparison is null")
    if comp:
        check("4 comparison has >=2 dimensions", len(comp.get("dimensions", [])) >= 2, str(len(comp.get("dimensions", []))))
        check("4 comparison carries caveats", bool(comp.get("caveats")))
    check("4 graph path entered compare", "compare" in " ".join(r.get("graph_path", [])), str(r.get("graph_path")))


# --------------------------------------------------------------------------- #
# Routing-only mode: exercise just planner._route_node for every query shape.
# One Groq call per case, so it verifies the PLANNING logic (the point of this
# agent) without the full specialist fan-out that the free Groq tier can't
# sustain across all four cases in one sitting.
# --------------------------------------------------------------------------- #
from agents import planner as _p  # noqa: E402

_ROUTING_CASES = [
    {"n": 1, "q": "what's Reliance's current stock price",
     "mode": "single", "selected": {"market_data"}, "skipped": {"news_sentiment", "filings"}},
    {"n": 2, "q": "give me a complete research view on TCS",
     "mode": "single", "selected": {"market_data", "news_sentiment", "filings"}, "skipped": set()},
    {"n": 3, "q": "give me a full picture on State Bank of India (SBI)",
     "mode": "single", "selected": {"market_data", "news_sentiment"}, "skipped": {"filings"},
     "filings_skip_words": ("corpus", "ingest", "not one of", "annual report")},
    {"n": 4, "q": "compare TCS and Infosys on fundamentals, sentiment and risk profile",
     "mode": "multi", "companies": {"TCS", "INFY"}},
]


async def routing_only() -> None:
    for c in _ROUTING_CASES:
        section(f"ROUTING {c['n']}  ::  {c['q']!r}")
        st = await _p._route_node({"query": c["q"], "model_name": _p.DEFAULT_MODEL})
        rt = st["routing"]
        print("  companies :", [(x["name"], x["ticker"], x["resolvable"], x["in_filings_corpus"]) for x in st["companies"]])
        print("  mode      :", st["mode"], " selected:", rt["specialists_selected"])
        for s in rt["specialists_skipped"]:
            print(f"  skip {s['specialist']}: {s['reason']}")
        print("  rationale :", rt["rationale"])
        for line in st["routing_trace"]:
            print("  |", line)

        check(f"R{c['n']} mode == {c['mode']}", st["mode"] == c["mode"], st["mode"])
        sel = set(rt["specialists_selected"])
        if "selected" in c:
            check(f"R{c['n']} selected == {sorted(c['selected'])}", sel == c["selected"], str(sorted(sel)))
        if "skipped" in c:
            sk = {s["specialist"] for s in rt["specialists_skipped"]}
            check(f"R{c['n']} skipped == {sorted(c['skipped'])}", sk == c["skipped"], str(sorted(sk)))
            for s in rt["specialists_skipped"]:
                check(f"R{c['n']} skip of {s['specialist']} has a real reason", len(s["reason"]) > 10, s["reason"])
        if "filings_skip_words" in c:
            fr = _norm(next((s["reason"] for s in rt["specialists_skipped"] if s["specialist"] == "filings"), ""))
            check(f"R{c['n']} filings skip cites the corpus", any(w in fr for w in c["filings_skip_words"]), fr)
        if "companies" in c:
            got = {x["ticker"] for x in st["companies"]}
            check(f"R{c['n']} identified {sorted(c['companies'])}", c["companies"].issubset(got), str(sorted(got)))
        check(f"R{c['n']} routing_trace is human-readable and non-trivial", len(st["routing_trace"]) >= 3)
        check(f"R{c['n']} rationale is non-empty", len(rt["rationale"]) > 20)
        await asyncio.sleep(float(os.environ.get("PLANNER_ROUTING_GAP_S", "12")))


# --------------------------------------------------------------------------- #
_CASE_FNS = {1: case1_price, 2: case2_deepdive, 3: case3_no_corpus, 4: case4_compare}


async def _main() -> int:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    print(f"model chain primary = {os.environ.get('GROQ_AGENT_MODEL', 'openai/gpt-oss-120b')}")
    print(f"PLANNER_MAX_CONCURRENCY = {os.environ.get('PLANNER_MAX_CONCURRENCY', '(auto: 2 single / 1 multi)')}")
    print(f"mode = {arg or 'all cases'}")
    print(f"limiter snapshot at start: {json.dumps(rl.snapshot())}")

    if arg in ("routing", "route", "r"):
        await routing_only()
    elif arg in ("1", "2", "3", "4"):
        await _CASE_FNS[int(arg)]()
    else:  # all four, end to end (heavy - free Groq tier may not sustain it in one run)
        cases = (case1_price, case2_deepdive, case3_no_corpus, case4_compare)
        for i, fn in enumerate(cases):
            try:
                await fn()
            except Exception as exc:  # noqa: BLE001
                print(f"  !! case raised: {type(exc).__name__}: {exc}")
                _failures.append(f"{fn.__name__} raised")
            if i < len(cases) - 1:
                gap = _GAP * 2.5 if i == len(cases) - 2 else _GAP
                print(f"\n  ... cooling down {gap:.0f}s before next case ...")
                await asyncio.sleep(gap)

    section("SUMMARY")
    print(f"limiter snapshot at end: {json.dumps(rl.snapshot())}")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        return 1
    print("\n  all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
