"""Standalone test for agents/market_data_agent.py.

Not pytest - a runnable script that drives the agent against real queries covering
three reasoning patterns and prints, for each:
  - the reasoning trace (which tools it chose, in order)
  - the full structured output (findings, provenance, raw_data, summary)

Then a few assertions on which tools were called for which query.

    python agents/test_market_data_agent.py

Needs GEMINI_API_KEY + network. Spawns market-data-mcp as a subprocess. Makes
~3-4 rate-limited Gemini calls per query (ReAct loop + one synthesis call).

Free-tier Gemini generate quota is tiny (~20/day for gemini-3-flash-preview and
gemini-flash-latest; gemini-flash-lite-latest tolerates more). The shared limiter
defaults conservatively; if it blocks a run, raise it and/or point at the roomier
model:

    GEMINI_RL_GENERATE_RPD=300 GEMINI_AGENT_MODEL=gemini-flash-lite-latest \\
        python agents/test_market_data_agent.py
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
for _n in ("google_genai", "google_genai.models", "httpx", "langchain_google_genai"):
    logging.getLogger(_n).setLevel(logging.ERROR)

from agents.market_data_agent import run_sync  # noqa: E402
from shared import gemini_rate_limiter as grl  # noqa: E402

CASES = [
    {
        "name": "single-tool (price)",
        "query": "what's Reliance's current stock price?",
        "expect_any": [{"get_fundamentals"}, {"get_price_history"}],
        "expect_not": {"get_peer_comparison"},
    },
    {
        "name": "multi-tool (valuation vs fundamentals)",
        "query": "how is TCS valued compared to its fundamentals?",
        "expect_all": {"get_fundamentals", "get_ratios"},
        "expect_not": {"get_peer_comparison"},
    },
    {
        "name": "peer comparison",
        "query": "compare Reliance, TCS, and M&M",
        "expect_all": {"get_peer_comparison"},
        "expect_not": {"get_fundamentals", "get_ratios", "get_price_history"},
    },
]

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(t: str) -> None:
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def show_result(r: dict) -> None:
    if "error" in r:
        print(f"  !! agent returned an error: {r['error']}")
        if r.get("tools_called"):
            print(f"     (tools called before the error: {r['tools_called']})")
        return

    print("  reasoning trace:")
    for step in r.get("reasoning_trace", []):
        if step["step"] == "tool_call":
            print(f"    -> call  {step['tool']}({step['args']})")
        elif step["step"] == "tool_result":
            print(f"    <- result {step['tool']}  ({step['chars']} chars)")
        elif step["step"] == "agent_answer":
            print(f"    == answer: {step['text'][:200]}")

    print(f"\n  ticker/company : {r['ticker']}  /  {r['company']}")
    print(f"  tools_called   : {r['tools_called']}")
    print(f"  summary        : {r['summary']}")
    print("  findings:")
    for f in r["findings"]:
        print(f"    - {f}")
    print("  provenance:")
    print("    " + json.dumps(r.get("provenance", {}), default=str, indent=2).replace("\n", "\n    "))
    print("  raw_data keys  : " + ", ".join(r.get("raw_data", {})))


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"model chain primary = {os.environ.get('GEMINI_AGENT_MODEL', 'gemini-3-flash-preview')}")
    print(f"limiter snapshot at start: {json.dumps(grl.snapshot())}")

    for case in CASES:
        section(f"{case['name']}  ::  {case['query']!r}")
        result = run_sync(case["query"])
        show_result(result)

        called = set(result.get("tools_called", []))
        if "error" in result:
            check(f"{case['name']} completed", False, result["error"][:80])
            continue
        check(f"{case['name']} produced findings", bool(result.get("findings")))
        if "expect_all" in case:
            check(
                f"{case['name']} called {sorted(case['expect_all'])}",
                case["expect_all"].issubset(called),
                f"called {sorted(called)}",
            )
        if "expect_any" in case:
            check(
                f"{case['name']} called one of {[sorted(s) for s in case['expect_any']]}",
                any(s.issubset(called) for s in case["expect_any"]),
                f"called {sorted(called)}",
            )
        if "expect_not" in case:
            bad = case["expect_not"] & called
            check(f"{case['name']} avoided {sorted(case['expect_not'])}", not bad,
                  f"wrongly called {sorted(bad)}" if bad else "")
        check(
            f"{case['name']} carried provenance (as_of/fiscal_year/roe_source)",
            any("as_of" in v or "fiscal_year" in v or "per_company" in v
                for v in result.get("provenance", {}).values()),
        )

    section("SUMMARY")
    print(f"limiter snapshot at end: {json.dumps(grl.snapshot())}")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        sys.exit(1)
    print("\n  all checks passed")
    sys.exit(0)
