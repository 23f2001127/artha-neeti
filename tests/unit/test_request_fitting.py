"""Per-request token fitting and provider error classification in agents/_base.py."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agents import _base

_GROQ_413 = (
    'Error code: 413 - {"error":{"message":"Request too large for model `openai/gpt-oss-120b` '
    "in organization `org_x` service tier `on_demand` on tokens per minute (TPM): Limit 8000, "
    'Requested 20082, please reduce your message size and try again.","type":"tokens",'
    '"code":"rate_limit_exceeded"}}'
)
_GROQ_429 = 'Error code: 429 - {"error":{"message":"Rate limit reached for model","code":"rate_limit_exceeded"}}'


def _conversation() -> list:
    return [
        SystemMessage("s" * 800),
        HumanMessage("what is TCS trading at"),
        AIMessage("", tool_calls=[{"name": "get_price_history", "args": {}, "id": "call-1"}]),
        ToolMessage("x" * 40_000, tool_call_id="call-1", name="get_price_history"),
        ToolMessage("y" * 15_000, tool_call_id="call-2", name="get_ratios"),
    ]


def _total_chars(messages: list) -> int:
    return sum(len(m.content) for m in messages)


def test_fit_messages_is_noop_under_budget() -> None:
    messages = [SystemMessage("short"), HumanMessage("question")]
    assert _base.fit_messages(messages, 5_000) is messages


def test_fit_messages_shrinks_to_budget() -> None:
    fitted = _base.fit_messages(_conversation(), 5_000)
    # The omission marker adds a few chars per trimmed message on top of the budget.
    assert _total_chars(fitted) <= 5_000 * 3 + 200


def test_fit_messages_never_trims_system_prompt() -> None:
    original = _conversation()
    assert _base.fit_messages(original, 2_000)[0] is original[0]


def test_fit_messages_preserves_tool_call_ids_and_marks_cuts() -> None:
    fitted = _base.fit_messages(_conversation(), 5_000)
    assert [m.tool_call_id for m in fitted if isinstance(m, ToolMessage)] == ["call-1", "call-2"]
    assert "omitted to fit" in fitted[3].content


def test_fit_messages_does_not_mutate_inputs() -> None:
    original = _conversation()
    _base.fit_messages(original, 2_000)
    assert len(original[3].content) == 40_000
    assert len(original[4].content) == 15_000


def test_fit_messages_trims_largest_message_first() -> None:
    fitted = _base.fit_messages(_conversation(), 16_000)
    assert len(fitted[3].content) < 40_000
    assert fitted[4].content == "y" * 15_000


def test_413_is_too_large_not_rate_limited() -> None:
    exc = Exception(_GROQ_413)
    assert _base.is_too_large_error(exc)
    assert not _base.is_rate_error(exc), "413 bodies carry rate_limit_exceeded but must not rotate models"


def test_429_is_rate_limited() -> None:
    exc = Exception(_GROQ_429)
    assert _base.is_rate_error(exc)
    assert not _base.is_too_large_error(exc)


def test_requested_tokens_parsed_from_413() -> None:
    assert _base._requested_tokens(Exception(_GROQ_413)) == 20082
    assert _base._requested_tokens(Exception("no count here")) is None


@pytest.mark.parametrize(
    ("exc", "prefix"),
    [
        (_base.rl.QuotaExceededError("all fallback models are rate limited"), "LLM rate limit: QuotaExceededError"),
        (_base.RequestTooLargeError("still too large"), "Request too large: RequestTooLargeError"),
        (ValueError("boom"), "ValueError: boom"),
    ],
)
def test_describe_error_labels_real_cause(exc: BaseException, prefix: str) -> None:
    assert _base.describe_error(exc).startswith(prefix)


def test_describe_error_finds_cause_inside_exception_group() -> None:
    group = ExceptionGroup("task group", [RuntimeError("secondary"), _base.RequestTooLargeError("too big")])
    assert _base.describe_error(group).startswith("Request too large:")


def test_prompt_json_is_compact_and_keeps_unicode() -> None:
    payload = {"ticker": "TCS", "price": "₹2,135", "items": [1, 2]}
    text = _base.prompt_json(payload)
    assert text == '{"ticker":"TCS","price":"₹2,135","items":[1,2]}'
    assert len(text) < len(json.dumps(payload, indent=2))
