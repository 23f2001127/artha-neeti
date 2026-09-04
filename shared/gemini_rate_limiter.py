"""Cross-process rate limiter for the shared Google Gemini account quota.

Why this module exists
----------------------
`research_mcp` (sentiment via `generate_content`) and `filings_rag_mcp`
(embeddings via `embed_content`) - and, soon, several LangGraph agents - all call
Gemini with the **same API key**, so they share one account-wide quota. Each
process's own in-memory throttle can't see the others; run two at once and they
blow the limit together. This module is the shared meeting point.

Design choice: a local SQLite ledger
------------------------------------
Every Gemini request reserves a row `(bucket, timestamp, tokens, requests)`.
`acquire()` opens the DB in an ``IMMEDIATE`` transaction (a cross-process write
lock), evaluates the sliding per-minute and per-day windows against that ledger,
and either records the reservation and returns, or releases the lock and sleeps
until the window frees up.

Alternatives considered and rejected for a **local, single-machine, solo** setup:

- *in-memory limiter* - what we have now; it can't see other processes (the whole
  problem).
- *Postgres* (we already hold a connection) - it's a **remote** Supabase
  instance: ~50-150 ms per rate check, and it couples `research_mcp` (which
  otherwise needs no database) to the DB's availability. A rate check should be
  local and near-free.
- *a "Gemini gateway" daemon* that every caller routes through - correct, and how
  you'd do it at scale, but it adds a long-running process to supervise, startup
  ordering, and an IPC layer. Too much machinery for one dev laptop.
- *a JSON file + advisory locks* (`fcntl` / `msvcrt` / `filelock`) - SQLite
  already does atomic cross-process read-modify-write, portably (Windows + POSIX),
  with WAL. Hand-rolling it is more code and more edge cases.

SQLite in WAL mode on a local disk gives genuine multi-process coordination with
sub-millisecond checks and **zero new dependencies** (`sqlite3` is stdlib).
Requirement: the DB file must live on a local filesystem (not NFS/SMB) - fine for
a single machine. Path: ``<repo>/.gemini_rate_limiter.db`` (gitignored), override
with ``GEMINI_RATE_LIMITER_DB``.

Limits (observed on the free tier, 2026-09 - RE-VERIFY, Google's quotas drift)
-----------------------------------------------------------------------------
                                    per minute              per day
  embed    (gemini-embedding-001)   100 req / 30k tokens    1,000 req   <- hard wall
  generate (gemini-3-flash-preview) ~5 req                  (never hit)
  generate (gemini-flash-latest)    -                       ~20 req

Each text in an ``embed_content`` batch counts as **one request** against both the
per-minute and per-day request caps (a 90-text batch = 90 requests). The default
``generate`` bucket is deliberately conservative; pass
``request_type="generate:<model>"`` to track a model separately (its own window),
which is what `research_mcp` does since it falls back across models.

Override any limit via env: ``GEMINI_RL_<FAMILY>_RPM`` / ``_TPM`` / ``_RPD``
(family = the part before ``:``), e.g. ``GEMINI_RL_EMBED_RPD=100000`` on a paid key.

Interface
---------
    rid = acquire(estimated_tokens, request_type="embed", count=90)   # blocks
    try:
        resp = client.models.embed_content(...)
    except RateLimited/429:
        refund(rid, "embed")          # 429 requests do not consume quota
        ...backoff and retry (re-acquire)...
    # on success: nothing to do, the reservation stands

    with reserve(est_tokens, "generate:gemini-3-flash-preview"):   # ctx-manager form
        resp = client.models.generate_content(...)                 # auto-refunds on error

``acquire`` raises ``QuotaExceededError`` if the daily cap is already spent (a
wait of hours is not "blocking appropriately") or if ``timeout`` seconds pass
while waiting on the per-minute window.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

try:  # stdlib on 3.9+; needs the `tzdata` package on Windows (it's in requirements.txt)
    from zoneinfo import ZoneInfo

    _RESET_TZ = ZoneInfo("America/Los_Angeles")  # Google free-tier daily quotas reset midnight PT
except Exception:  # pragma: no cover
    _RESET_TZ = timezone.utc


class QuotaExceededError(RuntimeError):
    """Daily quota for a bucket is already spent, or `timeout` elapsed while waiting."""


@dataclass(frozen=True)
class Limits:
    rpm: int  # requests per rolling 60 s
    tpm: int  # tokens per rolling 60 s
    rpd: int  # requests per reset-tz day


_DEFAULTS: dict[str, Limits] = {
    "embed": Limits(rpm=100, tpm=30_000, rpd=1_000),
    # 'generate' is per-MODEL (callers pass request_type="generate:<model>"). The
    # free tier is stingy and moved during development: gemini-3-flash-preview is
    # now ~20 req/DAY, ~5 req/min. Defaulting tight means the limiter proactively
    # trips the wall and the caller's model-fallback chain kicks in *before* a
    # messy 429. Raise per family with GEMINI_RL_GENERATE_RPD etc. on a paid key.
    "generate": Limits(rpm=6, tpm=240_000, rpd=20),
}
_FALLBACK = Limits(rpm=6, tpm=200_000, rpd=20)

# The per-minute window. Overridable only so the test suite can run in seconds
# instead of minutes; leave it at 60 in real use.
_MIN_WINDOW = float(os.environ.get("GEMINI_RL_WINDOW_SECONDS", "60"))
_PRUNE_AGE = 26 * 3600  # keep ~a day plus slack, so the daily window is always covered


# --------------------------------------------------------------------------- #
def _family(request_type: str) -> str:
    return request_type.strip().lower().split(":", 1)[0] or "generate"


def _bucket(request_type: str) -> str:
    return request_type.strip().lower() or "generate"


def _limits_for(request_type: str) -> Limits:
    fam = _family(request_type)
    base = _DEFAULTS.get(fam, _FALLBACK)

    def _env(suffix: str, default: int) -> int:
        raw = os.environ.get(f"GEMINI_RL_{fam.upper()}_{suffix}")
        if raw is None:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    return Limits(_env("RPM", base.rpm), _env("TPM", base.tpm), _env("RPD", base.rpd))


def _db_path() -> Path:
    override = os.environ.get("GEMINI_RATE_LIMITER_DB")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / ".gemini_rate_limiter.db"


def _day_start_epoch(now: float) -> float:
    dt = datetime.fromtimestamp(now, tz=_RESET_TZ)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _next_day_start_epoch(now: float) -> float:
    dt = datetime.fromtimestamp(now, tz=_RESET_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (dt + timedelta(days=1)).timestamp()


# --------------------------------------------------------------------------- #
_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=45.0, isolation_level=None)  # manual txns
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=45000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gemini_events (
               id       INTEGER PRIMARY KEY AUTOINCREMENT,
               bucket   TEXT NOT NULL,
               ts       REAL NOT NULL,
               tokens   INTEGER NOT NULL,
               requests INTEGER NOT NULL DEFAULT 1
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_bucket_ts ON gemini_events (bucket, ts)")
    _local.conn = conn
    return conn


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


# --------------------------------------------------------------------------- #
def acquire(
    estimated_tokens: int,
    request_type: str = "generate",
    *,
    count: int = 1,
    timeout: float = 300.0,
) -> int:
    """Block until a Gemini request fits the shared budget; record it; return an id.

    Args:
        estimated_tokens: rough input-token size of the request (for the TPM window).
        request_type: "embed", "generate", or "generate:<model>".
        count: how many quota "requests" this call is - 1 for generate, N for an
            N-item embed batch (each item counts).
        timeout: max seconds to wait on the per-minute window before giving up.

    Returns:
        A reservation id; pass it to ``refund()`` if the request then fails with a
        429 or never reaches Google (those don't consume quota).

    Raises:
        QuotaExceededError: the daily cap is already reached, or ``timeout`` elapsed.
    """
    est = max(0, int(estimated_tokens))
    n = max(1, int(count))
    bucket = _bucket(request_type)
    lim = _limits_for(request_type)
    conn = _conn()
    deadline = time.monotonic() + max(0.0, timeout)

    while True:
        now = time.time()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM gemini_events WHERE ts < ?", (now - _PRUNE_AGE,))

            day_start = _day_start_epoch(now)
            day_used = conn.execute(
                "SELECT COALESCE(SUM(requests), 0) FROM gemini_events "
                "WHERE bucket = ? AND ts >= ?",
                (bucket, day_start),
            ).fetchone()[0]
            if day_used + n > lim.rpd:
                _rollback(conn)
                hrs = (_next_day_start_epoch(now) - now) / 3600.0
                raise QuotaExceededError(
                    f"gemini '{bucket}': daily cap {lim.rpd} would be exceeded "
                    f"({day_used} used, +{n} requested). Resets in ~{hrs:.1f}h "
                    f"(midnight {_RESET_TZ}). Use a paid key or wait."
                )

            win_start = now - _MIN_WINDOW
            row = conn.execute(
                "SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(tokens), 0) "
                "FROM gemini_events WHERE bucket = ? AND ts >= ?",
                (bucket, win_start),
            ).fetchone()
            min_reqs, min_tokens = row[0], row[1]

            token_ok = min_tokens + est <= lim.tpm or (min_tokens == 0 and est > lim.tpm)
            if min_reqs + n <= lim.rpm and token_ok:
                cur = conn.execute(
                    "INSERT INTO gemini_events (bucket, ts, tokens, requests) VALUES (?,?,?,?)",
                    (bucket, now, est, n),
                )
                conn.execute("COMMIT")
                return int(cur.lastrowid)

            oldest = conn.execute(
                "SELECT MIN(ts) FROM gemini_events WHERE bucket = ? AND ts >= ?",
                (bucket, win_start),
            ).fetchone()[0]
            _rollback(conn)
            wait = (oldest + _MIN_WINDOW) - now + 0.1 if oldest else 1.0
        except QuotaExceededError:
            raise
        except sqlite3.Error:
            _rollback(conn)
            raise

        remaining = deadline - time.monotonic()
        if wait > remaining:
            raise QuotaExceededError(
                f"gemini '{bucket}': still per-minute rate-limited after "
                f"{timeout:.0f}s of waiting."
            )
        time.sleep(min(wait, max(0.2, remaining)))


def refund(reservation_id: int | None, request_type: str = "generate") -> None:
    """Undo a reservation - call when the reserved request 429'd or never happened."""
    if reservation_id is None:
        return
    conn = _conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM gemini_events WHERE id = ?", (int(reservation_id),))
        conn.execute("COMMIT")
    except sqlite3.Error:
        _rollback(conn)


@contextmanager
def reserve(
    estimated_tokens: int,
    request_type: str = "generate",
    *,
    count: int = 1,
    timeout: float = 300.0,
) -> Iterator[int]:
    """Context-manager form: reserves on enter, refunds if the block raises.

    Good for a single-attempt call. For a retry loop that catches 429 internally,
    use acquire()/refund() explicitly so each attempt is accounted for.
    """
    rid = acquire(estimated_tokens, request_type, count=count, timeout=timeout)
    try:
        yield rid
    except BaseException:
        refund(rid, request_type)
        raise


def snapshot() -> dict:
    """Current usage per bucket - for a status tool or debugging."""
    conn = _conn()
    now = time.time()
    day_start = _day_start_epoch(now)
    win_start = now - _MIN_WINDOW
    out: dict[str, dict] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        buckets = [r[0] for r in conn.execute("SELECT DISTINCT bucket FROM gemini_events")]
        for bucket in buckets:
            lim = _limits_for(bucket)
            m = conn.execute(
                "SELECT COALESCE(SUM(requests),0), COALESCE(SUM(tokens),0) "
                "FROM gemini_events WHERE bucket=? AND ts>=?",
                (bucket, win_start),
            ).fetchone()
            d = conn.execute(
                "SELECT COALESCE(SUM(requests),0) FROM gemini_events WHERE bucket=? AND ts>=?",
                (bucket, day_start),
            ).fetchone()[0]
            out[bucket] = {
                "last_min_requests": m[0],
                "last_min_tokens": m[1],
                "today_requests": d,
                "limits": {"rpm": lim.rpm, "tpm": lim.tpm, "rpd": lim.rpd},
                "day_remaining": max(0, lim.rpd - d),
            }
        conn.execute("COMMIT")
    except sqlite3.Error:
        _rollback(conn)
    return out


def reset() -> None:
    """Wipe the ledger. For tests / a manual 'I know quota actually reset' override."""
    conn = _conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM gemini_events")
        conn.execute("COMMIT")
    except sqlite3.Error:
        _rollback(conn)


def close() -> None:
    """Close this thread's SQLite handle. Optional - handy in tests / on shutdown."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        _local.conn = None
