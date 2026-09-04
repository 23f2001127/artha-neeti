"""Standalone test for agents/news_sentiment_agent.py.

Not pytest - drives the agent against three reasoning patterns and prints, for
each: the reasoning trace, the full structured output (findings, CAVEATS,
provenance, summary). Then assertions on tool choice AND on whether the agent
actually respected the tools' caveats rather than dressing raw output in prose.

    python agents/test_news_sentiment_agent.py

Needs GROQ_API_KEY + TAVILY_API_KEY + GEMINI_API_KEY + network. Spawns
research-mcp as a subprocess. get_sentiment aggregate mode makes a Gemini call
(shared quota); Groq handles the agent reasoning.
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

from agents.news_sentiment_agent import run_sync  # noqa: E402
from shared import llm_rate_limiter as rl  # noqa: E402

_failures: list[str] = []


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
    print(f"\n  ticker/company : {r.get('ticker')}  /  {r.get('company')}")
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


def _text_blob(r: dict) -> str:
    return " ".join([r.get("summary", ""), *r.get("findings", []), *r.get("caveats", [])]).lower()


# --------------------------------------------------------------------------- #
def test_general_news() -> None:
    section("1. general news  ::  \"what's the latest news on Reliance\"")
    r = run_sync("what's the latest news on Reliance")
    show(r)
    if "error" in r:
        check("1 completed", False, r["error"][:90])
        return
    called = set(r["tools_called"])
    check("1 used a news tool", bool(called & {"search_news", "get_company_news"}), f"called {sorted(called)}")
    check("1 did NOT call sentiment or announcements",
          not (called & {"get_sentiment", "get_corporate_announcements"}), f"called {sorted(called)}")
    check("1 produced findings", bool(r["findings"]))


def test_sentiment_aggregate() -> None:
    section("2. sentiment  ::  \"what's the market sentiment on TCS right now\"")
    r = run_sync("what's the market sentiment on TCS right now")
    show(r)
    if "error" in r:
        check("2 completed", False, r["error"][:90])
        return
    called = set(r["tools_called"])
    check("2 called get_sentiment", "get_sentiment" in called, f"called {sorted(called)}")
    raw = r.get("raw_data", {}).get("get_sentiment", {})
    check("2 get_sentiment ran in AGGREGATE mode (agent passed a ticker, not text)",
          raw.get("mode") == "aggregate", f"mode={raw.get('mode')}")
    prov = r.get("provenance", {}).get("get_sentiment", {})
    check("2 provenance surfaces breakdown_on_company (the trustworthy number)",
          "breakdown_on_company" in prov)
    blob = _text_blob(r)
    check("2 output flags breakdown_on_company / on-company as the number to trust, "
          "or notes score isn't calibrated",
          any(k in blob for k in ("breakdown_on_company", "on-company", "on company",
                                  "not calibrated", "self-reported", "not a calibrated")))
    check("2 findings state the overall sentiment label",
          any(w in blob for w in ("positive", "negative", "neutral")))


def test_announcements_caveat() -> None:
    section("3. announcements  ::  \"any recent dividend or earnings announcements from M&M\"")
    r = run_sync("any recent dividend or earnings announcements from M&M")
    show(r)
    if "error" in r:
        check("3 completed", False, r["error"][:90])
        return
    called = set(r["tools_called"])
    check("3 called get_corporate_announcements", "get_corporate_announcements" in called,
          f"called {sorted(called)}")
    prov = r.get("provenance", {}).get("get_corporate_announcements", {})
    check("3 provenance carries the disclaimer + likely_announcement_count",
          "disclaimer" in prov and "likely_announcement_count" in prov)
    caveats_blob = " ".join(r.get("caveats", [])).lower()
    check("3 a caveat says this is NOT the NSE/BSE official feed",
          "nse" in caveats_blob and ("not" in caveats_blob or "search" in caveats_blob),
          caveats_blob[:120])
    check("3 a caveat raises the entity / group-company disambiguation risk",
          any(w in caveats_blob for w in ("group compan", "tech mahindra", "mahindra finance",
                                          "disambigu", "peer", "not the company")),
          caveats_blob[:160])
    check("3 caveats list is non-empty", bool(r.get("caveats")))


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"model chain primary = {os.environ.get('GROQ_AGENT_MODEL', 'openai/gpt-oss-120b')}")
    print(f"limiter snapshot at start: {json.dumps(rl.snapshot())}")

    # Groq's ~8k tokens/min cap (shared across the model chain) is the binding
    # limit; these three queries carry big news payloads, so pace them apart.
    _gap = float(os.environ.get("GROQ_TEST_GAP_S", "45"))
    test_general_news()
    time.sleep(_gap)
    test_sentiment_aggregate()
    time.sleep(_gap)
    test_announcements_caveat()

    section("SUMMARY")
    print(f"limiter snapshot at end: {json.dumps(rl.snapshot())}")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        sys.exit(1)
    print("\n  all checks passed")
    sys.exit(0)
