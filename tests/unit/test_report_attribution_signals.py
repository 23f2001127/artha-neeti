"""Sentiment chart data and tool results stay with the company they describe."""

from __future__ import annotations

from agents import _base, planner


def _aggregate(input_: str, company: str, n: int) -> dict:
    return {"mode": "aggregate", "input": input_, "company": company,
            "breakdown": {"positive": n, "neutral": 0, "negative": 0}, "articles": [{"title": company}]}


def test_repeated_tool_calls_keep_every_result() -> None:
    log = [{"tool": "get_sentiment", "result": 1}, {"tool": "get_ratios", "result": 2},
           {"tool": "get_sentiment", "result": 3}, {"tool": "get_sentiment", "result": 4}]
    assert _base.keyed_results(log) == {"get_sentiment": 1, "get_ratios": 2, "get_sentiment#2": 3, "get_sentiment#3": 4}


def test_signals_ignore_a_peer_lookup() -> None:
    state = {"specialist_outputs": {
        "TCS": {"news_sentiment": {"raw_data": {
            "get_sentiment": _aggregate("INFY", "Infosys", 7),
            "get_sentiment#2": _aggregate("TCS.NS", "Tata Consultancy Services", 4),
        }}},
        "INFY": {"news_sentiment": {"raw_data": {"get_sentiment": _aggregate("Infosys", "Infosys", 7)}}},
    }}
    signals = planner._extract_signals(state)
    assert signals["TCS"]["sentiment"]["breakdown"]["positive"] == 4
    assert signals["INFY"]["sentiment"]["breakdown"]["positive"] == 7


def test_no_signal_when_only_a_peer_was_looked_up() -> None:
    state = {"specialist_outputs": {"TCS": {"news_sentiment": {"raw_data": {
        "get_sentiment": _aggregate("INFY", "Infosys", 7)}}}}}
    assert "TCS" not in planner._extract_signals(state)


def test_connection_errors_move_to_next_model() -> None:
    class APIConnectionError(Exception):
        pass

    model = _base.RateLimitedChatGroq.model_construct()
    state = {"messages": [], "budget": 6000, "errors": [], "rate_limited": False}
    assert model._on_failure(APIConnectionError("Connection error."), "m", 0, state) == "next"
