"""Offline entity-matching helpers in research-mcp."""

from __future__ import annotations

import pytest

from mcp_servers.research_mcp import research as rz


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RELIANCE.NS", True),
        ("Tata Consultancy Services", True),
        ("Reliance shares rose today after a big order win.", False),
    ],
)
def test_sentiment_mode_detection(text: str, expected: bool) -> None:
    assert rz._looks_like_ticker_or_name(text) is expected


_MNM = rz._company_aliases("M&M.NS", "Mahindra & Mahindra")
_RIL = rz._company_aliases("RELIANCE.NS", "Reliance Industries")


@pytest.mark.parametrize(
    ("aliases", "headline", "expected"),
    [
        (_MNM, "Mahindra & Mahindra Q1 results: profit up 34%", True),
        (_MNM, "M&M Q4 Results: PAT jumps to Rs 3,737 crore", True),
        (_MNM, "Tech Mahindra Q4 net profit rises 16%; declares dividend", False),
        (_MNM, "Mahindra & Mahindra Financial Services share price today", False),
        (_MNM, "Mahindra Finance Board Approves Merger With Subsidiary", False),
        (_MNM, "M&M and Tech Mahindra both beat estimates this quarter", True),
        (_RIL, "Reliance Industries Q4 results; dividend announced", True),
        (_RIL, "Reliance Power shares hit upper circuit", False),
        (_RIL, "Reliance, Inc. (RS) reports Q2 earnings", False),
        (_RIL, "April earnings season kicks off next week", False),
    ],
)
def test_mentions_company_disambiguates_group_companies(aliases, headline: str, expected: bool) -> None:
    assert rz._mentions_company({"title": headline, "snippet": ""}, aliases) is expected
