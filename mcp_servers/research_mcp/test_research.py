"""Standalone smoke test for research-mcp.

Not pytest - a runnable script that hits the live Tavily + Gemini APIs so you can
eyeball the actual news / sentiment output. Run it from anywhere:

    python mcp_servers/research_mcp/test_research.py

It:
  1. calls all 4 tools against RELIANCE.NS, TCS.NS, and M&M.NS and prints results
  2. checks get_sentiment's mode detection and text-mode labels on obvious cases
  3. checks graceful failure: empty input, a missing API key, an empty result set

Exit code is non-zero if any assertion fails. Needs network access and the two
API keys in the project .env (TAVILY_API_KEY, GEMINI_API_KEY).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# keep stdout happy with rupee signs / non-ascii article titles on Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# quiet google-genai's info/warning banners (AFC is disabled in research.py anyway)
logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

import research as rz

COMPANIES = ["RELIANCE.NS", "TCS.NS", "M&M.NS"]

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def dump(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))  # ensure_ascii=True -> safe on any console


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# --------------------------------------------------------------------------- #
def test_search_news() -> None:
    section("search_news('India stock market Nifty Sensex', max_results=4)")
    res = rz.search_news("India stock market Nifty Sensex today", max_results=4)
    dump(res)
    check("search_news returns results", res.get("count", 0) > 0 and "error" not in res)

    section("search_news('Reliance Jio subscriber growth', max_results=3)")
    res2 = rz.search_news("Reliance Jio subscriber growth", max_results=3)
    dump(res2)
    check("search_news (topic query) returns results", res2.get("count", 0) > 0)
    check(
        "search_news results have title + url",
        all(r.get("title") and r.get("url") for r in res2.get("results", [])),
    )


def test_company_news() -> None:
    for c in COMPANIES:
        section(f"get_company_news({c!r}, days_back=30)")
        res = rz.get_company_news(c, days_back=30)
        dump(res)
        check(f"{c} company news ok", "error" not in res)
        check(f"{c} company news has results", res.get("count", 0) > 0)
        check(
            f"{c} resolved to a full name",
            bool(res.get("company")) and res.get("company") != c,
            res.get("company", ""),
        )
        check(
            f"{c} company news flags mentions_company on every item",
            all("mentions_company" in r for r in res.get("results", [])),
        )
        check(
            f"{c} company news has >=1 on-company result",
            res.get("on_company_count", 0) > 0,
            f"{res.get('on_company_count')}/{res.get('count')}",
        )


# Gemini's free tier is ~5 requests/minute per model, so space the sentiment
# calls out. Override with GEMINI_TEST_SPACING_S=0 if you have paid quota.
_SPACING = float(os.environ.get("GEMINI_TEST_SPACING_S", "14"))


def _space() -> None:
    if _SPACING > 0:
        time.sleep(_SPACING)


def test_sentiment() -> None:
    for i, c in enumerate(COMPANIES):
        if i:
            _space()
        section(f"get_sentiment({c!r})  [expect aggregate mode]")
        res = rz.get_sentiment(c)
        dump(res)
        check(f"{c} sentiment ok", "error" not in res)
        if "error" not in res:
            check(f"{c} sentiment is aggregate mode", res.get("mode") == "aggregate")
            overall = res.get("overall", {})
            check(
                f"{c} overall label valid",
                overall.get("label") in ("positive", "neutral", "negative"),
                f"{overall.get('label')} (score {overall.get('score')})",
            )
            bd = res.get("breakdown", {})
            check(
                f"{c} breakdown sums to article_count",
                sum(bd.values()) == res.get("article_count"),
                f"breakdown={bd} count={res.get('article_count')}",
            )
            bdc = res.get("breakdown_on_company", {})
            check(
                f"{c} breakdown_on_company sums to on_company_count",
                sum(bdc.values()) == res.get("on_company_count"),
                f"on_company={bdc} count={res.get('on_company_count')}",
            )
            check(
                f"{c} every scored article carries mentions_company",
                all("mentions_company" in a for a in res.get("articles", [])),
            )

    _space()
    section("get_sentiment(<positive text>)  [expect text mode, positive]")
    pos = rz.get_sentiment(
        "The company crushed earnings estimates, raised full-year guidance, and "
        "announced a special dividend; the stock jumped 12% to an all-time high."
    )
    dump(pos)
    check("positive text -> text mode", pos.get("mode") == "text")
    check("positive text -> positive label", pos.get("label") == "positive", str(pos.get("label")))

    _space()
    section("get_sentiment(<negative text>)  [expect text mode, negative]")
    neg = rz.get_sentiment(
        "The regulator fined the bank a record amount for governance lapses, the "
        "CEO resigned abruptly, and analysts slashed their price targets as the "
        "stock sank to a multi-year low."
    )
    dump(neg)
    check("negative text -> text mode", neg.get("mode") == "text")
    check("negative text -> negative label", neg.get("label") == "negative", str(neg.get("label")))

    section("get_sentiment mode-detection unit checks")
    check("'RELIANCE.NS' looks like a ticker", rz._looks_like_ticker_or_name("RELIANCE.NS"))
    check("'Tata Consultancy Services' looks like a name", rz._looks_like_ticker_or_name("Tata Consultancy Services"))
    check(
        "a full sentence does NOT look like a ticker",
        not rz._looks_like_ticker_or_name("Reliance shares rose today after a big order win."),
    )

    section("_mentions_company entity / group-company disambiguation")
    mnm = rz._company_aliases("M&M.NS", "Mahindra & Mahindra")
    ril = rz._company_aliases("RELIANCE.NS", "Reliance Industries")
    _hs = lambda t: {"title": t, "snippet": ""}
    cases = [
        (mnm, "Mahindra & Mahindra Q1 results: profit up 34%", True),
        (mnm, "M&M Q4 Results: PAT jumps to Rs 3,737 crore", True),
        (mnm, "Tech Mahindra Q4 net profit rises 16%; declares dividend", False),
        (mnm, "Mahindra & Mahindra Financial Services share price today", False),
        (mnm, "Mahindra Finance Board Approves Merger With Subsidiary", False),
        (mnm, "M&M and Tech Mahindra both beat estimates this quarter", True),
        (ril, "Reliance Industries Q4 results; dividend announced", True),
        (ril, "Reliance Power shares hit upper circuit", False),
        (ril, "Reliance, Inc. (RS) reports Q2 earnings", False),
        (ril, "April earnings season kicks off next week", False),
    ]
    for aliases, text, expected in cases:
        got = rz._mentions_company(_hs(text), aliases)
        check(
            f"mentions_company({text[:45]!r}) == {expected}",
            got == expected,
            f"got {got}",
        )


def test_corporate_announcements() -> None:
    for c in COMPANIES:
        section(f"get_corporate_announcements({c!r}, days_back=45)")
        res = rz.get_corporate_announcements(c, days_back=45)
        dump(res)
        check(f"{c} announcements ok", "error" not in res)
        check(f"{c} announcements has results", res.get("count", 0) > 0)
        check(
            f"{c} announcements carries the search-based disclaimer",
            "NOT" in (res.get("disclaimer") or "") and "NSE/BSE" in (res.get("disclaimer") or ""),
        )
        check(
            f"{c} announcements found >=1 likely-announcement item",
            res.get("likely_announcement_count", 0) > 0,
            f"{res.get('likely_announcement_count')} likely / "
            f"{res.get('on_company_count')} on-company / {res.get('count')} total",
        )
        check(
            f"{c} announcements are sorted likely-first",
            [a.get("likely_announcement") for a in res.get("announcements", [])]
            == sorted((a.get("likely_announcement") for a in res.get("announcements", [])), reverse=True),
        )
        check(
            f"{c} every likely_announcement item actually mentions the company",
            all(
                a.get("mentions_company")
                for a in res.get("announcements", [])
                if a.get("likely_announcement")
            ),
        )


def test_failure_cases() -> None:
    section("FOCUS: graceful failure handling")

    empty = rz.search_news("   ")
    dump(empty)
    check("empty query -> error string", "error" in empty)

    empty_sent = rz.get_sentiment("")
    check("empty sentiment input -> error string", "error" in empty_sent)

    # missing API key path
    saved = os.environ.pop("TAVILY_API_KEY", None)
    rz._tavily_client = None
    try:
        no_key = rz.search_news("Reliance Industries")
        dump(no_key)
        check(
            "missing TAVILY_API_KEY -> clean error, no crash",
            "error" in no_key and "TAVILY_API_KEY" in no_key["error"],
        )
    finally:
        if saved is not None:
            os.environ["TAVILY_API_KEY"] = saved
        rz._tavily_client = None

    # empty result set -> count 0 + note, NOT an error. Tavily almost always
    # returns *something*, so force the empty case by stubbing the search helper.
    section("FOCUS: empty result set is not an error (stubbed)")
    original = rz._tavily_search
    rz._tavily_search = lambda *a, **k: []
    try:
        thin = rz.search_news("anything", max_results=5)
        dump(thin)
        check(
            "empty results -> count 0 + note, not an error",
            "error" not in thin and thin.get("count") == 0 and bool(thin.get("note")),
        )
        thin_co = rz.get_company_news("RELIANCE.NS")
        check(
            "empty company news -> count 0 + note, not an error",
            "error" not in thin_co and thin_co.get("count") == 0 and bool(thin_co.get("note")),
        )
        thin_sent = rz.get_sentiment("RELIANCE.NS")
        check(
            "empty news for aggregate sentiment -> clean error",
            "error" in thin_sent,
        )
    finally:
        rz._tavily_search = original


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    test_search_news()
    test_company_news()
    test_sentiment()
    test_corporate_announcements()
    test_failure_cases()

    section("SUMMARY")
    if _failures:
        print(f"  {len(_failures)} check(s) FAILED:")
        for name in _failures:
            print(f"    - {name}")
        sys.exit(1)
    print("  all checks passed")
    sys.exit(0)
