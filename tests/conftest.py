from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]

_NOISY_LOGGERS = ("groq", "httpx", "langchain_groq", "google_genai", "google_genai.models", "yfinance")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests that call external APIs (Groq, Gemini, Tavily, yfinance, Postgres) and consume quota",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--live"):
        load_dotenv(REPO_ROOT / ".env", override=False)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="calls external APIs and consumes quota; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _pace_live_calls(request: pytest.FixtureRequest):
    """Space out quota-bound live tests. Groq's free tier allows ~8k tokens/min
    shared across the model chain, so back-to-back agent runs would 429."""
    yield
    marker = request.node.get_closest_marker("pace")
    if marker and marker.args and request.config.getoption("--live"):
        time.sleep(float(marker.args[0]))
