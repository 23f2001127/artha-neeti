"""Postgres persistence for the research-job API.

Same Supabase instance as ``filings-rag-mcp`` (``DATABASE_URL`` in ``.env``), and
the same access pattern as ``mcp_servers/filings_rag_mcp/db.py``: a fresh
connection per call via a ``@contextmanager``. A connection pool
(``psycopg2.pool.ThreadedConnectionPool``) would be marginally better under load,
but this is a single-process dev/portfolio backend and the query rate is tiny
(one job row, updated a handful of times per run), so simplicity wins. Swap the
pool in here if that changes.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()  # repo-root .env

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_jobs (
    job_id            uuid        PRIMARY KEY,
    query             text        NOT NULL,
    status            text        NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    routing_trace     jsonb,                                   -- set when the route node finishes
    specialist_status jsonb,                                   -- {ticker: {specialist: pending|ok|error:...}}
    report            jsonb,                                   -- final Planner output
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS research_jobs_status_idx  ON research_jobs (status);
CREATE INDEX IF NOT EXISTS research_jobs_created_idx ON research_jobs (created_at DESC);

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

_UPDATABLE = {"status", "routing_trace", "specialist_status", "report", "error"}
_JSONB = {"routing_trace", "specialist_status", "report"}

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
def create_job(query: str) -> str:
    job_id = str(uuid.uuid4())
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_jobs (job_id, query, status) VALUES (%s, %s, 'queued')",
            (job_id, query),
        )
        conn.commit()
    return job_id


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
