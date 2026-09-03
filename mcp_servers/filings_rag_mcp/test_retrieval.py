"""Standalone retrieval-quality test for filings-rag-mcp.

Not pytest - a runnable script that prints the ACTUAL retrieved chunk text and
page numbers so retrieval quality can be judged by eye, not just pass/fail.

Prerequisite: ingestion has run for at least RELIANCE, TCS, M&M
(``python -m mcp_servers.filings_rag_mcp.ingest``).

    python mcp_servers/filings_rag_mcp/test_retrieval.py

Needs DATABASE_URL and GEMINI_API_KEY in .env. Makes ~1 Gemini embedding call per
query (shared quota with research-mcp), spaced to stay polite.
"""

from __future__ import annotations

import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

for _n in ("google_genai", "google_genai.models", "httpx"):
    logging.getLogger(_n).setLevel(logging.WARNING)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mcp_servers.filings_rag_mcp import db, retrieval as rt

REQUESTED_TICKERS = ["RELIANCE", "TCS", "M&M"]


def _ingested_subset() -> list[str]:
    try:
        have = set(db.available_tickers())
    except Exception:  # noqa: BLE001
        return []
    pending = [t for t in REQUESTED_TICKERS if t not in have]
    if pending:
        print(f"\n!! not yet ingested (skipping their retrieval tests): {pending}")
        print("   run: python -m mcp_servers.filings_rag_mcp.ingest --only " + " ".join(pending))
    return [t for t in REQUESTED_TICKERS if t in have]


TICKERS = _ingested_subset()
SEARCH_QUERIES = [
    "what was the revenue growth this year and what drove it",
    "key risks and risk factors disclosed",
    "capital expenditure plans and investments",
]
STATEMENTS = ["income_statement", "balance_sheet", "cash_flow"]
_YOY_ALL = [("RELIANCE", "revenue"), ("TCS", "net profit"), ("M&M", "EBITDA")]
YOY = [(t, m) for t, m in _YOY_ALL if t in TICKERS]

_SPACING = float(os.environ.get("GEMINI_TEST_SPACING_S", "1.5"))
_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(title: str) -> None:
    print("\n" + "=" * 74 + f"\n{title}\n" + "=" * 74)


def show_hits(hits: list[dict], excerpt: int = 420) -> None:
    for h in hits:
        flag = "  [TABLE?]" if h.get("may_contain_tabular_data") else ""
        kw = h.get("matched_header_keyword") or h.get("matched_yoy_phrase")
        kw = f"  kw={kw!r}" if kw else ""
        sim = h.get("similarity")
        sim_s = f"{sim:.3f}" if isinstance(sim, (int, float)) else "kw-match"
        print(
            f"\n  -- page {h['page_number']}  sim={sim_s}"
            f"  numeric_density={h.get('numeric_density')}{flag}{kw}"
        )
        text = " ".join((h.get("text") or "").split())
        print("     " + text[:excerpt] + ("..." if len(text) > excerpt else ""))


# --------------------------------------------------------------------------- #
def test_corpus_present() -> None:
    section("corpus check")
    try:
        summary = db.corpus_summary()
    except Exception as exc:  # noqa: BLE001
        check("database reachable", False, str(exc))
        return
    for row in summary["by_ticker"]:
        print(f"  {row['ticker']:<10} {row['chunks']:>5} chunks  "
              f"{row['tabular_chunks']:>4} tabular  pages {row['min_page']}-{row['max_page']}")
    print(f"  TOTAL: {summary['total_chunks']} chunks")
    ingested = {r["ticker"] for r in summary["by_ticker"]}
    check("at least one requested ticker is ingested", bool(TICKERS), f"testing: {TICKERS}")
    for t in TICKERS:
        check(f"{t} is ingested", t in ingested)


def test_search_filing() -> None:
    for ticker in TICKERS:
        for q in SEARCH_QUERIES:
            section(f"search_filing({ticker!r}, {q!r}, top_k=4)")
            res = rt.search_filing(q, ticker, top_k=4)
            if "error" in res:
                check(f"{ticker} / {q[:30]}", False, res["error"])
                continue
            check(f"{ticker} / {q[:30]} returned hits", res["count"] > 0)
            check(
                f"{ticker} / {q[:30]} top hit is relevant (sim > 0.5)",
                res["results"] and res["results"][0]["similarity"] > 0.5,
                f"top sim = {res['results'][0]['similarity'] if res['results'] else 'n/a'}",
            )
            show_hits(res["results"])
            time.sleep(_SPACING)


def test_statements() -> None:
    for ticker in TICKERS:
        for st in STATEMENTS:
            section(f"get_financial_statement_section({ticker!r}, {st!r})")
            res = rt.get_financial_statement_section(ticker, st)
            if "error" in res:
                check(f"{ticker} / {st}", False, res["error"])
                continue
            check(f"{ticker} / {st} returned hits", res["count"] > 0)
            check(
                f"{ticker} / {st} landed on a plausible page (>1/3 into the doc)",
                bool(res["pages_returned"]) and max(res["pages_returned"]) > 40,
                f"pages {res['pages_returned']}",
            )
            print(f"  pages_returned: {res['pages_returned']}")
            show_hits(res["results"], excerpt=500)
            time.sleep(_SPACING)


def test_yoy() -> None:
    for ticker, metric in YOY:
        section(f"compare_yoy_metrics({ticker!r}, {metric!r})")
        res = rt.compare_yoy_metrics(ticker, metric)
        if "error" in res:
            check(f"{ticker} yoy {metric}", False, res["error"])
            continue
        check(f"{ticker} yoy {metric} returned hits", res["count"] > 0)
        check(f"{ticker} yoy carries the single-filing limitation", "limitation" in res)
        print(f"  basis: {res['basis']}")
        print(f"  limitation: {res['limitation']}")
        show_hits(res["results"])
        time.sleep(_SPACING)


def test_failures() -> None:
    section("FOCUS: graceful failure handling")
    check("empty query -> error", "error" in rt.search_filing("", "RELIANCE"))
    check("empty ticker -> error", "error" in rt.search_filing("revenue", ""))
    bad = rt.search_filing("revenue", "NOTATICKER")
    check("unknown ticker -> clear error", "error" in bad and "ingested" in bad["error"].lower())
    print(f"    -> {bad.get('error')}")
    bad_st = rt.get_financial_statement_section("RELIANCE", "cash flow of unicorns")
    check("unknown statement_type -> error listing options",
          "error" in bad_st and "supported" in bad_st["error"].lower())


if __name__ == "__main__":
    test_corpus_present()
    test_search_filing()
    test_statements()
    test_yoy()
    test_failures()

    section("SUMMARY")
    if _failures:
        print(f"  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        sys.exit(1)
    print("  all checks passed")
    sys.exit(0)
