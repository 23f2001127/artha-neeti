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
"""

_UPDATABLE = {"status", "routing_trace", "specialist_status", "report", "error"}
_JSONB = {"routing_trace", "specialist_status", "report"}


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
