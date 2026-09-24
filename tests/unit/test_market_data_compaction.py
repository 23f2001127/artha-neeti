"""Price-history compaction applied before market data reaches the model."""

from __future__ import annotations

from agents.market_data_agent import _PRICE_SAMPLES, _compact, _summarize_history


def _rows(n: int) -> list[dict]:
    return [
        {"date": f"2026-01-{i:02d}", "open": 100, "high": 110 + i, "low": 90 - i, "close": 100 + i, "volume": 1000 * i}
        for i in range(1, n + 1)
    ]


def test_summary_statistics() -> None:
    summary = _summarize_history(_rows(28))
    assert summary["first_close"] == 101
    assert summary["last_close"] == 128
    assert summary["change_pct"] == round((128 / 101 - 1) * 100, 2)
    assert summary["period_high"] == 138
    assert summary["period_low"] == 62
    assert summary["avg_volume"] == int(sum(1000 * i for i in range(1, 29)) / 28)


def test_sampled_series_is_bounded_and_ends_on_last_row() -> None:
    rows = _rows(250)
    sampled = _summarize_history(rows)["sampled_closes"]
    assert len(sampled) <= _PRICE_SAMPLES + 2
    assert sampled[0]["date"] == rows[0]["date"]
    assert sampled[-1] == {"date": rows[-1]["date"], "close": rows[-1]["close"]}


def test_empty_history_summarizes_to_nothing() -> None:
    assert _summarize_history([]) == {}


def test_compact_replaces_history_with_summary() -> None:
    result = {"ticker": "TCS.NS", "period": "1y", "history": _rows(30)}
    compacted = _compact("get_price_history", result)
    assert "history" not in compacted
    assert compacted["ticker"] == "TCS.NS" and compacted["period"] == "1y"
    assert compacted["summary"]["last_close"] == 130
    assert "history" in result, "the full payload must be left intact for raw_data"


def test_compact_leaves_other_tools_untouched() -> None:
    fundamentals = {"ticker": "TCS.NS", "pe_ratio": 15.5}
    assert _compact("get_fundamentals", fundamentals) is fundamentals
    assert _compact("get_price_history", {"error": "no data"}) == {"error": "no data"}
