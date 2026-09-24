"""research-mcp tool functions against live Tavily and Gemini."""

from __future__ import annotations

import os

import pytest

from mcp_servers.research_mcp import research as rz

# Gemini's free tier allows ~5 requests/minute per model.
_GEMINI_SPACING = float(os.environ.get("GEMINI_TEST_SPACING_S", "14"))

pytestmark = pytest.mark.live

COMPANIES = ["RELIANCE.NS", "TCS.NS", "M&M.NS"]


def test_search_news_market_query() -> None:
    res = rz.search_news("India stock market Nifty Sensex today", max_results=4)
    assert "error" not in res, res.get("error")
    assert res.get("count", 0) > 0


def test_search_news_topic_query_has_title_and_url() -> None:
    res = rz.search_news("Reliance Jio subscriber growth", max_results=3)
    assert res.get("count", 0) > 0
    assert all(r.get("title") and r.get("url") for r in res.get("results", []))


@pytest.mark.parametrize("company", COMPANIES)
def test_company_news(company: str) -> None:
    res = rz.get_company_news(company, days_back=30)
    assert "error" not in res, res.get("error")
    assert res.get("count", 0) > 0
    assert res.get("company") and res.get("company") != company, "ticker should resolve to a full name"
    assert all("mentions_company" in r for r in res.get("results", []))
    assert res.get("on_company_count", 0) > 0


@pytest.mark.pace(_GEMINI_SPACING)
@pytest.mark.parametrize("company", COMPANIES)
def test_aggregate_sentiment(company: str) -> None:
    res = rz.get_sentiment(company)
    assert "error" not in res, res.get("error")
    assert res.get("mode") == "aggregate"
    assert res.get("overall", {}).get("label") in ("positive", "neutral", "negative")
    assert sum(res.get("breakdown", {}).values()) == res.get("article_count")
    assert sum(res.get("breakdown_on_company", {}).values()) == res.get("on_company_count")
    assert all("mentions_company" in a for a in res.get("articles", []))


@pytest.mark.pace(_GEMINI_SPACING)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "The company crushed earnings estimates, raised full-year guidance, and "
            "announced a special dividend; the stock jumped 12% to an all-time high.",
            "positive",
        ),
        (
            "The regulator fined the bank a record amount for governance lapses, the "
            "CEO resigned abruptly, and analysts slashed their price targets as the "
            "stock sank to a multi-year low.",
            "negative",
        ),
    ],
    ids=["positive", "negative"],
)
def test_text_sentiment(text: str, expected: str) -> None:
    res = rz.get_sentiment(text)
    assert res.get("mode") == "text"
    assert res.get("label") == expected


@pytest.mark.parametrize("company", COMPANIES)
def test_corporate_announcements(company: str) -> None:
    res = rz.get_corporate_announcements(company, days_back=45)
    assert "error" not in res, res.get("error")
    assert res.get("count", 0) > 0
    disclaimer = res.get("disclaimer") or ""
    assert "NOT" in disclaimer and "NSE/BSE" in disclaimer
    assert res.get("likely_announcement_count", 0) > 0
    flags = [a.get("likely_announcement") for a in res.get("announcements", [])]
    assert flags == sorted(flags, reverse=True), "likely announcements must sort first"
    assert all(a.get("mentions_company") for a in res.get("announcements", []) if a.get("likely_announcement"))


def test_empty_inputs_return_errors() -> None:
    assert "error" in rz.search_news("   ")
    assert "error" in rz.get_sentiment("")


def test_missing_tavily_key_returns_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(rz, "_tavily_client", None)
    res = rz.search_news("Reliance Industries")
    assert "error" in res and "TAVILY_API_KEY" in res["error"]


def test_empty_result_set_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rz, "_tavily_search", lambda *a, **k: [])

    thin = rz.search_news("anything", max_results=5)
    assert "error" not in thin and thin.get("count") == 0 and thin.get("note")

    thin_company = rz.get_company_news("RELIANCE.NS")
    assert "error" not in thin_company and thin_company.get("count") == 0 and thin_company.get("note")

    assert "error" in rz.get_sentiment("RELIANCE.NS"), "aggregate sentiment needs articles"
