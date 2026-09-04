"""Cross-process test for shared/llm_rate_limiter.py.

Not pytest - a runnable script. It spawns real child processes that hammer the
limiter against a throwaway SQLite ledger with tiny fake limits, then checks the
COMBINED behaviour across processes:

  1. per-minute coordination - no sliding window ever exceeds the request cap,
     even though 3 independent processes are pushing as fast as they can;
  2. the daily cap - exactly `rpd` requests succeed across all processes, then
     every process gets QuotaExceededError;
  3. single-process functional - acquire / refund / snapshot / reserve() ctx-mgr.

No Gemini API calls, so it costs no quota.

    python shared/test_llm_rate_limiter.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(t: str) -> None:
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# --------------------------------------------------------------------------- #
# child-process worker
# --------------------------------------------------------------------------- #
def _worker(bucket: str, n_iters: int, tokens: int, out_file: str) -> None:
    from shared import llm_rate_limiter as rl

    # each worker writes to ITS OWN file (out_file.<pid>) - concurrent appends from
    # 3 processes to one file interleave on the OS and lose lines.
    lines: list[str] = []
    for _ in range(n_iters):
        try:
            rid = rl.acquire(tokens, bucket, count=1, timeout=120.0)
        except rl.QuotaExceededError:
            lines.append(f"QUOTA {time.time():.4f} {os.getpid()}")
            break
        lines.append(f"OK {time.time():.4f} {os.getpid()} {rid}")
        time.sleep(0.01)
    with open(f"{out_file}.{os.getpid()}", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _spawn(env_extra: dict, bucket: str, n_iters: int, tokens: int, out_file: str) -> subprocess.Popen:
    env = {**os.environ, **{k: str(v) for k, v in env_extra.items()}}
    return subprocess.Popen(
        [sys.executable, __file__, "worker", bucket, str(n_iters), str(tokens), out_file],
        env=env,
        cwd=str(_REPO_ROOT),
    )


def _read_events(out_file: str) -> tuple[list[float], list[str]]:
    oks: list[float] = []
    quotas: list[str] = []
    base = Path(out_file)
    for part_file in sorted(base.parent.glob(base.name + ".*")):
        for line in part_file.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "OK":
                oks.append(float(parts[1]))
            elif parts[0] == "QUOTA":
                quotas.append(parts[2])
    return sorted(oks), quotas


def _max_in_any_window(timestamps: list[float], window: float) -> int:
    worst = 0
    for i, t0 in enumerate(timestamps):
        j = i
        while j < len(timestamps) and timestamps[j] < t0 + window:
            j += 1
        worst = max(worst, j - i)
    return worst


# --------------------------------------------------------------------------- #
def test_per_minute_coordination() -> None:
    section("1. per-minute coordination across 3 processes")
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "rl.db")
        out = os.path.join(d, "events.txt")
        Path(out).touch()
        window, rpm = 6, 12
        env = {
            "LLM_RATE_LIMITER_DB": db,
            "LLM_RL_WINDOW_SECONDS": window,
            "LLM_RL_EMBED_RPM": rpm,
            "LLM_RL_EMBED_TPM": 10_000_000,
            "LLM_RL_EMBED_RPD": 10_000_000,
        }
        t0 = time.time()
        procs = [_spawn(env, "embed", 10, 5, out) for _ in range(3)]
        for p in procs:
            p.wait(timeout=180)
        elapsed = time.time() - t0

        oks, quotas = _read_events(out)
        worst = _max_in_any_window(oks, window)
        print(f"  30 acquires across 3 procs in {elapsed:.1f}s; "
              f"busiest {window}s window held {worst} (cap {rpm})")
        check("all 30 acquires eventually succeeded", len(oks) == 30, f"{len(oks)}/30")
        check(f"no {window}s window exceeded the {rpm}-req cap", worst <= rpm, f"worst={worst}")
        check("it actually had to throttle (took > 1 window)", elapsed > window, f"{elapsed:.1f}s")
        check("no spurious QuotaExceededError", not quotas)


def test_daily_cap() -> None:
    section("2. daily cap enforced across 2 processes")
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "rl.db")
        out = os.path.join(d, "events.txt")
        Path(out).touch()
        rpd = 15
        env = {
            "LLM_RATE_LIMITER_DB": db,
            "LLM_RL_WINDOW_SECONDS": 2,
            "LLM_RL_EMBED_RPM": 10_000,
            "LLM_RL_EMBED_TPM": 10_000_000,
            "LLM_RL_EMBED_RPD": rpd,
        }
        procs = [_spawn(env, "embed", 20, 5, out) for _ in range(2)]
        for p in procs:
            p.wait(timeout=120)

        oks, quotas = _read_events(out)
        print(f"  {len(oks)} succeeded, {len(quotas)} processes hit the daily wall")
        check(f"exactly {rpd} requests succeeded across both processes",
              len(oks) == rpd, f"{len(oks)}")
        check("both processes hit QuotaExceededError", len(quotas) == 2, f"{quotas}")


def test_single_process_functional() -> None:
    section("3. single-process functional (acquire / refund / snapshot / reserve)")
    d = tempfile.mkdtemp()
    try:
        os.environ["LLM_RATE_LIMITER_DB"] = os.path.join(d, "rl.db")
        os.environ["LLM_RL_WINDOW_SECONDS"] = "60"
        os.environ["LLM_RL_GENERATE_RPM"] = "100"
        os.environ["LLM_RL_GENERATE_RPD"] = "100"
        # fresh import so the env is picked up
        for m in [k for k in list(sys.modules) if k.startswith("shared.llm_rate_limiter")]:
            del sys.modules[m]
        from shared import llm_rate_limiter as rl

        rl.reset()
        ids = [rl.acquire(100, "generate:test-model") for _ in range(3)]
        rl.refund(ids[0], "generate:test-model")
        snap = rl.snapshot().get("generate:test-model", {})
        check("snapshot reflects 3 acquired - 1 refunded = 2",
              snap.get("today_requests") == 2, str(snap.get("today_requests")))

        before = rl.snapshot()["generate:test-model"]["today_requests"]
        try:
            with rl.reserve(50, "generate:test-model"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        after = rl.snapshot()["generate:test-model"]["today_requests"]
        check("reserve() auto-refunds when the block raises", after == before, f"{before}->{after}")

        os.environ["LLM_RL_GENERATE_RPD"] = "2"
        rl.reset()
        rl.acquire(10, "generate:cap"); rl.acquire(10, "generate:cap")
        try:
            rl.acquire(10, "generate:cap", timeout=1.0)
            check("daily cap raises QuotaExceededError", False, "no raise")
        except rl.QuotaExceededError as exc:
            check("daily cap raises QuotaExceededError", True, str(exc)[:60])

        rl.close()
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        _worker(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
        sys.exit(0)

    test_per_minute_coordination()
    test_daily_cap()
    test_single_process_functional()

    section("SUMMARY")
    if _failures:
        print(f"  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        sys.exit(1)
    print("  all checks passed")
    sys.exit(0)
