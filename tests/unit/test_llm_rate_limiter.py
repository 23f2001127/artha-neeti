"""Cross-process and single-process behaviour of shared/llm_rate_limiter.py.

Runs against throwaway SQLite ledgers with tiny limits; no provider API calls.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import llm_rate_limiter as rl

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("rate_limiter_worker.py")


def _spawn(env_extra: dict, bucket: str, iterations: int, tokens: int, out_file: Path) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), **{k: str(v) for k, v in env_extra.items()}}
    return subprocess.Popen(
        [sys.executable, str(WORKER), bucket, str(iterations), str(tokens), str(out_file)],
        env=env,
        cwd=str(REPO_ROOT),
    )


def _read_events(out_file: Path) -> tuple[list[float], list[str]]:
    oks: list[float] = []
    quotas: list[str] = []
    for part in sorted(out_file.parent.glob(out_file.name + ".*")):
        for line in part.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "OK":
                oks.append(float(fields[1]))
            elif fields[0] == "QUOTA":
                quotas.append(fields[2])
    return sorted(oks), quotas


def _max_in_any_window(timestamps: list[float], window: float) -> int:
    worst = 0
    for i, start in enumerate(timestamps):
        j = i
        while j < len(timestamps) and timestamps[j] < start + window:
            j += 1
        worst = max(worst, j - i)
    return worst


def test_per_minute_cap_is_enforced_across_processes(tmp_path: Path) -> None:
    window, rpm = 6, 12
    env = {
        "LLM_RATE_LIMITER_DB": tmp_path / "rl.db",
        "LLM_RL_WINDOW_SECONDS": window,
        "LLM_RL_EMBED_RPM": rpm,
        "LLM_RL_EMBED_TPM": 10_000_000,
        "LLM_RL_EMBED_RPD": 10_000_000,
    }
    out = tmp_path / "events.txt"
    started = time.time()
    procs = [_spawn(env, "embed", 10, 5, out) for _ in range(3)]
    for p in procs:
        assert p.wait(timeout=180) == 0
    elapsed = time.time() - started

    oks, quotas = _read_events(out)
    assert len(oks) == 30
    assert _max_in_any_window(oks, window) <= rpm
    assert elapsed > window, "limiter should have throttled across more than one window"
    assert not quotas


def test_daily_cap_is_enforced_across_processes(tmp_path: Path) -> None:
    rpd = 15
    env = {
        "LLM_RATE_LIMITER_DB": tmp_path / "rl.db",
        "LLM_RL_WINDOW_SECONDS": 2,
        "LLM_RL_EMBED_RPM": 10_000,
        "LLM_RL_EMBED_TPM": 10_000_000,
        "LLM_RL_EMBED_RPD": rpd,
    }
    out = tmp_path / "events.txt"
    procs = [_spawn(env, "embed", 20, 5, out) for _ in range(2)]
    for p in procs:
        assert p.wait(timeout=120) == 0

    oks, quotas = _read_events(out)
    assert len(oks) == rpd
    assert len(quotas) == 2


@pytest.fixture
def isolated_limiter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Drop any cached handle so the limiter reopens against the temp ledger,
    # never the real one a running backend may be using.
    rl.close()
    monkeypatch.setenv("LLM_RATE_LIMITER_DB", str(tmp_path / "rl.db"))
    monkeypatch.setenv("LLM_RL_GENERATE_RPM", "100")
    monkeypatch.setenv("LLM_RL_GENERATE_RPD", "100")
    rl.reset()
    yield rl
    rl.close()


def test_snapshot_reflects_acquires_minus_refunds(isolated_limiter) -> None:
    ids = [isolated_limiter.acquire(100, "generate:test-model") for _ in range(3)]
    isolated_limiter.refund(ids[0], "generate:test-model")
    assert isolated_limiter.snapshot()["generate:test-model"]["today_requests"] == 2


def test_reserve_refunds_when_block_raises(isolated_limiter) -> None:
    isolated_limiter.acquire(10, "generate:test-model")
    before = isolated_limiter.snapshot()["generate:test-model"]["today_requests"]
    with pytest.raises(RuntimeError):
        with isolated_limiter.reserve(50, "generate:test-model"):
            raise RuntimeError("boom")
    assert isolated_limiter.snapshot()["generate:test-model"]["today_requests"] == before


def test_daily_cap_raises_quota_exceeded(isolated_limiter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_RL_GENERATE_RPD", "2")
    isolated_limiter.acquire(10, "generate:cap")
    isolated_limiter.acquire(10, "generate:cap")
    with pytest.raises(isolated_limiter.QuotaExceededError):
        isolated_limiter.acquire(10, "generate:cap", timeout=1.0)
