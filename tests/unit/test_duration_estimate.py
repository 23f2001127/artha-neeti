"""Duration estimate (app/db.py) from past jobs, with the database stubbed out."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import db


def _routing(*company_specialists: int) -> dict:
    return {"sub_queries": {f"T{i}": {f"s{j}": "q" for j in range(n)} for i, n in enumerate(company_specialists)}}


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_):
        pass

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def history(monkeypatch: pytest.MonkeyPatch):
    def install(rows):
        @contextmanager
        def fake_connect():
            class Conn:
                def cursor(self):
                    return _Cursor(rows)

            yield Conn()

        monkeypatch.setattr(db, "connect", fake_connect)

    return install


def test_planned_tasks_counts_company_specialist_pairs() -> None:
    assert db.planned_tasks(_routing(3, 2)) == 5
    assert db.planned_tasks({}) == 0
    assert db.planned_tasks(None) == 0


def test_estimate_scales_with_planned_work(history) -> None:
    history([
        ("single", _routing(1), 120.0),
        ("single", _routing(3), 420.0),
        ("single", _routing(3), 480.0),
    ])
    one, samples = db.estimate_duration_seconds("single", 1)
    three, _ = db.estimate_duration_seconds("single", 3)
    assert samples == 3
    assert one == pytest.approx(140.0)
    assert three == pytest.approx(420.0)


def test_modes_keep_their_own_rate(history) -> None:
    history([
        ("single", _routing(3), 360.0),
        ("single", _routing(3), 360.0),
        ("multi", _routing(3, 3), 1800.0),
        ("multi", _routing(3, 3), 2160.0),
    ])
    single, _ = db.estimate_duration_seconds("single", 3)
    multi, _ = db.estimate_duration_seconds("multi", 6)
    assert single == pytest.approx(360.0)
    assert multi == pytest.approx(1980.0)


def test_sparse_mode_falls_back_to_all_jobs(history) -> None:
    history([("single", _routing(2), 240.0), ("single", _routing(2), 240.0), ("multi", _routing(3, 3), 1800.0)])
    seconds, samples = db.estimate_duration_seconds("multi", 6)
    assert samples == 3
    assert seconds == pytest.approx(720.0)


def test_no_history_or_no_work_gives_no_estimate(history) -> None:
    history([])
    assert db.estimate_duration_seconds("single", 3) == (None, 0)
    assert db.estimate_duration_seconds("single", 0) == (None, 0)
