"""Filings Agent tool choice and citation discipline against the live corpus.

Requires RELIANCE, TCS and M&M to be ingested.
"""

from __future__ import annotations

import os
import re

import pytest

from agents.filings_agent import run_sync
from tests.helpers import norm_text as _norm

pytestmark = [pytest.mark.live, pytest.mark.pace(float(os.environ.get("GROQ_TEST_GAP_S", "90")))]

_PAGE_RE = re.compile(r"(p{1,2}\.?\s?\d+|page[s]?\s+\d+)", re.I)
# A "not found" statement is not a filing fact and needs no page citation.
_NEGATION_RE = re.compile(
    r"(not found|not disclose|does not|did not|no .*(mention|reference|disclosure|figure)|"
    r"not (stated|available|present|provided|retrieved)|could not find)", re.I
)


def _uncited(findings: list[str]) -> list[str]:
    return [f for f in findings if not _PAGE_RE.search(f) and not _NEGATION_RE.search(f)]


def test_semantic_risk_query_uses_search_and_cites_pages() -> None:
    r = run_sync("what are Reliance's key disclosed risks")
    assert "error" not in r, r.get("error")
    called = set(r["tools_called"])
    assert "search_filing" in called, f"called {sorted(called)}"
    assert not (called & {"get_financial_statement_section", "compare_yoy_metrics"}), f"called {sorted(called)}"
    assert r["findings"]
    assert not _uncited(r["findings"])
    assert r.get("provenance", {}).get("search_filing", {}).get("pages")
    assert r.get("ticker") in ("RELIANCE", "RELIANCE.NS") and r.get("company")


def test_income_statement_query_flags_basis_and_extraction_limits() -> None:
    r = run_sync("what was TCS's revenue and profit for the year, from the income statement")
    assert "error" not in r, r.get("error")
    assert "get_financial_statement_section" in set(r["tools_called"])
    raw = r.get("raw_data", {}).get("get_financial_statement_section", {})
    assert raw.get("statement_type") == "income_statement"
    assert not _uncited(r["findings"])

    blob = _norm(" ".join(r["findings"] + r.get("caveats", []) + [r.get("summary", "")]))
    assert (any(w in blob for w in ("standalone", "consolidated"))
            or r.get("statement_basis") in ("standalone", "consolidated", "mixed"))

    caveats = _norm(" ".join(r.get("caveats", [])))
    assert r.get("caveats")
    assert any(w in caveats for w in ("search-based", "not a parsed", "parsed statement",
                                      "flatten", "column-collapse", "column-flatten", "tabular")), caveats[:160]


def test_yoy_query_states_single_filing_scope() -> None:
    r = run_sync("how has M&M's EBITDA changed year over year")
    assert "error" not in r, r.get("error")
    assert "compare_yoy_metrics" in set(r["tools_called"])
    prov = r.get("provenance", {}).get("compare_yoy_metrics", {})
    assert "basis" in prov and "limitation" in prov
    assert not _uncited(r["findings"])
    assert r.get("caveats")

    blob = _norm(" ".join(r["findings"] + r.get("caveats", []) + [r.get("summary", "")]))
    assert any(p in blob for p in ("one annual report", "single filing", "single annual report",
                                   "cross-filing", "not a multi-year", "not a true multi-year",
                                   "only one year", "single year-on-year", "one year-over-year",
                                   "one year-on-year", "prior-year column", "one report per company",
                                   "not a cross")), blob[:200]
