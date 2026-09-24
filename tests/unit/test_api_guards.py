"""Deployment guards in app/main.py: per-IP throttle, daily job cap, CORS origins.

The limits are read from the environment at import, so each test reloads the
module under the environment it needs and restores it afterwards.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as app_main


@pytest.fixture
def load_main(monkeypatch: pytest.MonkeyPatch):
    def _load(**env: str):
        for key in ("MAX_DAILY_JOBS", "IP_THROTTLE_PER_MINUTE", "CORS_ALLOWED_ORIGINS"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(app_main)

    yield _load
    monkeypatch.undo()
    importlib.reload(app_main)


def _request(ip: str = "203.0.113.7") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_ip_throttle_blocks_after_limit(load_main) -> None:
    main = load_main(IP_THROTTLE_PER_MINUTE="2")
    main._check_ip_throttle(_request())
    main._check_ip_throttle(_request())
    with pytest.raises(HTTPException) as exc:
        main._check_ip_throttle(_request())
    assert exc.value.status_code == 429


def test_ip_throttle_is_per_client(load_main) -> None:
    main = load_main(IP_THROTTLE_PER_MINUTE="1")
    main._check_ip_throttle(_request("198.51.100.1"))
    main._check_ip_throttle(_request("198.51.100.2"))


def test_ip_throttle_window_expires(load_main, monkeypatch: pytest.MonkeyPatch) -> None:
    main = load_main(IP_THROTTLE_PER_MINUTE="1")
    clock = [1_000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    main._check_ip_throttle(_request())
    clock[0] += main._THROTTLE_WINDOW_S + 1
    main._check_ip_throttle(_request())


def test_ip_throttle_tolerates_missing_client(load_main) -> None:
    main = load_main(IP_THROTTLE_PER_MINUTE="1")
    main._check_ip_throttle(SimpleNamespace(client=None))
    with pytest.raises(HTTPException):
        main._check_ip_throttle(SimpleNamespace(client=None))


def test_daily_cap_disabled_by_default(load_main, monkeypatch: pytest.MonkeyPatch) -> None:
    main = load_main()

    def fail(_cutoff):
        raise AssertionError("the job count must not be queried when the cap is disabled")

    monkeypatch.setattr(main.db, "count_jobs_since", fail)
    main._check_daily_job_cap()


@pytest.mark.parametrize(("jobs_today", "blocked"), [(2, False), (3, True), (10, True)])
def test_daily_cap_enforced_at_limit(load_main, monkeypatch: pytest.MonkeyPatch, jobs_today: int, blocked: bool) -> None:
    main = load_main(MAX_DAILY_JOBS="3")
    cutoffs: list[datetime] = []

    def count(cutoff: datetime) -> int:
        cutoffs.append(cutoff)
        return jobs_today

    monkeypatch.setattr(main.db, "count_jobs_since", count)
    if blocked:
        with pytest.raises(HTTPException) as exc:
            main._check_daily_job_cap()
        assert exc.value.status_code == 429
    else:
        main._check_daily_job_cap()

    window = datetime.now(timezone.utc) - cutoffs[0]
    assert timedelta(hours=23, minutes=59) < window <= timedelta(hours=24, minutes=1)


def test_cors_origins_parsed_from_env(load_main) -> None:
    main = load_main(CORS_ALLOWED_ORIGINS=" https://arthaneeti.vercel.app , https://example.com ,, ")
    assert main._cors_extra_origins == ["https://arthaneeti.vercel.app", "https://example.com"]


def test_cors_keeps_localhost_and_adds_configured_origins(load_main) -> None:
    main = load_main(CORS_ALLOWED_ORIGINS="https://arthaneeti.vercel.app")
    cors = next(m for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_origins"] == ["https://arthaneeti.vercel.app"]
    assert "localhost" in cors.kwargs["allow_origin_regex"]


def test_cors_defaults_to_localhost_only(load_main) -> None:
    main = load_main()
    assert main._cors_extra_origins == []
