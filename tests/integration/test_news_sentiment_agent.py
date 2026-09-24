"""News & Sentiment Agent tool choice and caveat handling against live APIs."""

from __future__ import annotations

import os

import pytest

from agents.news_sentiment_agent import run_sync

pytestmark = [pytest.mark.live, pytest.mark.pace(float(os.environ.get("GROQ_TEST_GAP_S", "45")))]


def _text_blob(result: dict) -> str:
    return " ".join([result.get("summary", ""), *result.get("findings", []), *result.get("caveats", [])]).lower()


def test_general_news_uses_news_tools_only() -> None:
    r = run_sync("what's the latest news on Reliance")
    assert "error" not in r, r.get("error")
    called = set(r["tools_called"])
    assert called & {"search_news", "get_company_news"}, f"called {sorted(called)}"
    assert not (called & {"get_sentiment", "get_corporate_announcements"}), f"called {sorted(called)}"
    assert r["findings"]


def test_sentiment_query_runs_aggregate_mode_and_hedges() -> None:
    r = run_sync("what's the market sentiment on TCS right now")
    assert "error" not in r, r.get("error")
    assert "get_sentiment" in set(r["tools_called"])
    assert r.get("raw_data", {}).get("get_sentiment", {}).get("mode") == "aggregate"
    assert "breakdown_on_company" in r.get("provenance", {}).get("get_sentiment", {})

    blob = _text_blob(r)
    assert any(k in blob for k in ("breakdown_on_company", "on-company", "on company",
                                   "not calibrated", "self-reported", "not a calibrated"))
    assert any(w in blob for w in ("positive", "negative", "neutral"))


def test_announcements_carry_source_and_entity_caveats() -> None:
    r = run_sync("any recent dividend or earnings announcements from M&M")
    assert "error" not in r, r.get("error")
    assert "get_corporate_announcements" in set(r["tools_called"])

    prov = r.get("provenance", {}).get("get_corporate_announcements", {})
    assert "disclaimer" in prov and "likely_announcement_count" in prov

    caveats = " ".join(r.get("caveats", [])).lower()
    assert r.get("caveats")
    assert "nse" in caveats and ("not" in caveats or "search" in caveats), caveats[:120]
    assert any(w in caveats for w in ("group compan", "tech mahindra", "mahindra finance",
                                      "disambigu", "peer", "not the company")), caveats[:160]
