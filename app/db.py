"""Postgres persistence for research jobs, follow-up turns and filing jobs.

Uses the same database as filings-rag-mcp (``DATABASE_URL``). Each call opens
its own short-lived connection; job rows see a handful of writes per run, so a
pool isn't needed.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()  # repo-root .env

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_jobs (
    job_id                     uuid        PRIMARY KEY,
    query                      text        NOT NULL,
    status                     text        NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    routing_trace              jsonb,                                   -- raw trace lines, set when routing finishes
    routing                    jsonb,                                   -- structured routing decision, same time
    specialist_status          jsonb,                                   -- {ticker: {specialist: pending|<stage text>|ok|error:...}}
    estimated_duration_seconds real,                                    -- set once routing is known (historical avg for this mode)
    estimated_duration_samples int,                                     -- how many past jobs backed that estimate
    report                     jsonb,                                   -- final Planner output
    error                      text,
    conversation_id            uuid,                                    -- groups turns of one conversation; a fresh top-level query = its own job_id
    parent_job_id              uuid REFERENCES research_jobs (job_id),  -- set only for an escalated follow-up: the job it continued from
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS research_jobs_status_idx  ON research_jobs (status);
CREATE INDEX IF NOT EXISTS research_jobs_created_idx ON research_jobs (created_at DESC);
-- research_jobs predates these columns - add them for a DB that already has
-- the table (CREATE TABLE IF NOT EXISTS is a no-op there). Must run BEFORE
-- anything that references these columns (the index below, the backfill).
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS routing jsonb;
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS estimated_duration_seconds real;
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS estimated_duration_samples int;
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS conversation_id uuid;
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS parent_job_id uuid REFERENCES research_jobs (job_id);
CREATE INDEX IF NOT EXISTS research_jobs_conversation_idx ON research_jobs (conversation_id);
-- every job is a valid conversation root until it's known to be a follow-up
UPDATE research_jobs SET conversation_id = job_id WHERE conversation_id IS NULL;

CREATE TABLE IF NOT EXISTS followup_turns (
    id               bigserial   PRIMARY KEY,
    conversation_id  uuid        NOT NULL,
    job_id           uuid        NOT NULL REFERENCES research_jobs (job_id),  -- which report this was asked against
    query            text        NOT NULL,
    answer           text,
    sufficient_data  boolean     NOT NULL,
    caveat           text,
    missing_reason   text,
    standalone_query text,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS followup_turns_conversation_idx ON followup_turns (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS filing_upload_jobs (
    job_id         uuid        PRIMARY KEY,
    ticker         text        NOT NULL,
    company        text,
    fiscal_year    text,
    filename       text        NOT NULL,
    source         text        NOT NULL DEFAULT 'upload',   -- upload | fetch
    source_url     text,                                    -- set for 'fetch': where the PDF came from
    detail         text,                                    -- short human phase text, e.g. "searching the web..."
    status         text        NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    chunks_done    int         NOT NULL DEFAULT 0,
    chunks_total   int,                                     -- null until parsing finishes
    chunks         int,                                     -- final count, set on 'done'
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS filing_upload_jobs_status_idx ON filing_upload_jobs (status);
-- filing_upload_jobs predates the source/source_url/detail columns - add them
-- for a DB that already has the table (CREATE TABLE IF NOT EXISTS is a no-op there).
ALTER TABLE filing_upload_jobs ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'upload';
ALTER TABLE filing_upload_jobs ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE filing_upload_jobs ADD COLUMN IF NOT EXISTS detail text;
"""

_UPDATABLE = {
    "status", "routing_trace", "routing", "specialist_status", "report", "error",
    "estimated_duration_seconds", "estimated_duration_samples",
}
_JSONB = {"routing_trace", "routing", "specialist_status", "report"}

_UPLOAD_UPDATABLE = {"status", "chunks_done", "chunks_total", "chunks", "error", "detail", "source_url"}


class DBError(RuntimeError):
    pass


@contextmanager
def connect() -> Iterator["psycopg2.extensions.connection"]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DBError("DATABASE_URL is not set (checked the environment and the project .env).")
    try:
        conn = psycopg2.connect(url, connect_timeout=20)
    except psycopg2.Error as exc:  # pragma: no cover - network
        raise DBError(f"could not connect to Postgres: {exc}") from exc
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)
        conn.commit()


# --------------------------------------------------------------------------- #
def create_job(query: str, *, conversation_id: str | None = None, parent_job_id: str | None = None) -> str:
    """A fresh top-level query is its own conversation root (conversation_id
    defaults to its own job_id). An escalated follow-up (see app/followups.py)
    passes the ORIGINAL conversation_id and its parent_job_id explicitly."""
    job_id = str(uuid.uuid4())
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO research_jobs (job_id, query, status, conversation_id, parent_job_id)
               VALUES (%s, %s, 'queued', %s, %s)""",
            (job_id, query, conversation_id or job_id, parent_job_id),
        )
        conn.commit()
    return job_id


def count_jobs_since(cutoff: datetime) -> int:
    """Research jobs created at or after `cutoff` (the daily job cap)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM research_jobs WHERE created_at >= %s", (cutoff,))
        return cur.fetchone()[0]


INTERRUPTED_MESSAGE = "This run was interrupted by a server restart. Please start it again."

# A running research job refreshes updated_at every HEARTBEAT_SECONDS; one that
# has been silent for STALE_AFTER lost its process.
HEARTBEAT_SECONDS = 60
STALE_AFTER = timedelta(minutes=3)


def touch_job(job_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE research_jobs SET updated_at = now() WHERE job_id = %s", (job_id,))
        conn.commit()


def fail_stale_jobs(job_id: str | None = None) -> int:
    """Mark queued/running research jobs with no recent heartbeat as
    interrupted: all of them, or only `job_id`. Returns the number closed."""
    sql = (
        "UPDATE research_jobs SET status = 'error', error = %s, updated_at = now() "
        "WHERE status IN ('queued', 'running') AND updated_at < now() - %s"
    )
    params: list[Any] = [INTERRUPTED_MESSAGE, STALE_AFTER]
    if job_id is not None:
        sql += " AND job_id = %s"
        params.append(job_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount


def update_job(job_id: str, **fields: Any) -> None:
    """Patch the given columns on one job row. Unknown keys are ignored; jsonb
    columns are dumped to a JSON string. No-op if nothing updatable was passed."""
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not fields:
        return
    sets: list[str] = []
    params: list[Any] = []
    for key, val in fields.items():
        if key in _JSONB:
            sets.append(f"{key} = %s::jsonb")
            params.append(json.dumps(val, default=str))
        else:
            sets.append(f"{key} = %s")
            params.append(val)
    sets.append("updated_at = now()")
    params.append(job_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE research_jobs SET {', '.join(sets)} WHERE job_id = %s", params)
        conn.commit()


def get_job(job_id: str) -> dict | None:
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM research_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def estimate_duration_seconds(mode: str) -> tuple[float | None, int]:
    """Average duration of past completed jobs in the same routing mode, as
    ``(seconds, sample_count)``. Falls back to all completed jobs when the mode
    has fewer than two samples, and to ``(None, 0)`` with no history. Finer
    buckets (company count, specialists) would mostly be empty at current volume.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                avg(extract(epoch FROM (updated_at - created_at)))
                    FILTER (WHERE report ->> 'mode' = %(mode)s) AS mode_avg,
                count(*) FILTER (WHERE report ->> 'mode' = %(mode)s) AS mode_n,
                avg(extract(epoch FROM (updated_at - created_at))) AS overall_avg,
                count(*) AS overall_n
            FROM research_jobs
            WHERE status = 'done' AND report IS NOT NULL
            """,
            {"mode": mode},
        )
        mode_avg, mode_n, overall_avg, overall_n = cur.fetchone()
    if mode_n and mode_n >= 2:
        return float(mode_avg), int(mode_n)
    if overall_n:
        return float(overall_avg), int(overall_n)
    return None, 0


# --------------------------------------------------------------------------- #
# followup_turns - the cheap chat-style Q&A on top of a finished report (see
# app/followups.py). Answered synchronously (one LLM call), so unlike
# research_jobs/filing_upload_jobs there's no status/progress to track - a
# turn is simply inserted once its answer is ready.
# --------------------------------------------------------------------------- #
def create_followup_turn(
    *,
    conversation_id: str,
    job_id: str,
    query: str,
    sufficient_data: bool,
    answer: str | None = None,
    caveat: str | None = None,
    missing_reason: str | None = None,
    standalone_query: str | None = None,
) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO followup_turns
               (conversation_id, job_id, query, answer, sufficient_data, caveat,
                missing_reason, standalone_query)
               VALUES (%(conversation_id)s, %(job_id)s, %(query)s, %(answer)s,
                       %(sufficient_data)s, %(caveat)s, %(missing_reason)s, %(standalone_query)s)""",
            {
                "conversation_id": conversation_id, "job_id": job_id, "query": query,
                "answer": answer, "sufficient_data": sufficient_data, "caveat": caveat,
                "missing_reason": missing_reason, "standalone_query": standalone_query,
            },
        )
        conn.commit()


def get_followup_turns(conversation_id: str) -> list[dict]:
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM followup_turns WHERE conversation_id = %s ORDER BY created_at",
            (conversation_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# filing_upload_jobs - same shape/rationale as research_jobs, for
# POST /filings/upload and POST /filings/fetch (see app/filings.py)
# --------------------------------------------------------------------------- #
def create_upload_job(
    *, ticker: str, company: str | None, fiscal_year: str | None, filename: str, source: str = "upload"
) -> str:
    job_id = str(uuid.uuid4())
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO filing_upload_jobs (job_id, ticker, company, fiscal_year, filename, source, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'queued')""",
            (job_id, ticker, company, fiscal_year, filename, source),
        )
        conn.commit()
    return job_id


def update_upload_job(job_id: str, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if k in _UPLOAD_UPDATABLE}
    if not fields:
        return
    sets = [f"{k} = %s" for k in fields]
    sets.append("updated_at = now()")
    params = [*fields.values(), job_id]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE filing_upload_jobs SET {', '.join(sets)} WHERE job_id = %s", params)
        conn.commit()


def get_upload_job(job_id: str) -> dict | None:
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM filing_upload_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
    return dict(row) if row else None
