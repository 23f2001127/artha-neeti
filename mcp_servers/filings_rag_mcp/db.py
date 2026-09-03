"""Postgres / pgvector access for filings-rag-mcp.

Uses psycopg2 directly (the ``pgvector`` python helper isn't a project dependency).
Embeddings are passed to/from Postgres as the pgvector text literal ``'[a,b,c]'``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

import psycopg2
import psycopg2.extras

from . import config

_SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS {config.CHUNKS_TABLE} (
    id                       bigserial PRIMARY KEY,
    ticker                   text    NOT NULL,
    company                  text,
    filename                 text    NOT NULL,
    fiscal_year              text,
    page_number              int     NOT NULL,
    chunk_index              int     NOT NULL,
    text                     text    NOT NULL,
    token_count              int,
    numeric_density          real,
    may_contain_tabular_data boolean NOT NULL DEFAULT false,
    embedding                vector({config.EMBED_DIM}),
    created_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (filename, chunk_index)
);

CREATE INDEX IF NOT EXISTS {config.CHUNKS_TABLE}_ticker_idx
    ON {config.CHUNKS_TABLE} (ticker);

CREATE INDEX IF NOT EXISTS {config.CHUNKS_TABLE}_embedding_idx
    ON {config.CHUNKS_TABLE} USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS {config.INGESTIONS_TABLE} (
    filename     text PRIMARY KEY,
    ticker       text,
    company      text,
    fiscal_year  text,
    pages        int,
    chunks       int,
    tabular_chunks int,
    embed_model  text,
    embed_dim    int,
    ingested_at  timestamptz NOT NULL DEFAULT now()
);
"""


class DBError(RuntimeError):
    pass


@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    if not config.DATABASE_URL:
        raise DBError("DATABASE_URL is not set (checked the environment and the project .env).")
    try:
        conn = psycopg2.connect(config.DATABASE_URL, connect_timeout=20)
    except psycopg2.Error as exc:  # pragma: no cover - network
        raise DBError(f"Could not connect to Postgres: {exc}") from exc
    try:
        yield conn
    finally:
        conn.close()


def to_vector_literal(values: Sequence[float]) -> str:
    """[0.1, 0.2] -> '[0.1,0.2]' (pgvector's text input format)."""
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"


def init_schema() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)
        conn.commit()


# --------------------------------------------------------------------------- #
# ingestion-side helpers
# --------------------------------------------------------------------------- #
def ingestion_status() -> dict[str, dict[str, Any]]:
    """filename -> row from filing_ingestions (completed ingestions only)."""
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {config.INGESTIONS_TABLE}")
        return {r["filename"]: dict(r) for r in cur.fetchall()}


def chunk_counts_by_filename() -> dict[str, int]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT filename, count(*) FROM {config.CHUNKS_TABLE} GROUP BY filename"
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def delete_filing(filename: str) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {config.CHUNKS_TABLE} WHERE filename = %s", (filename,))
        cur.execute(f"DELETE FROM {config.INGESTIONS_TABLE} WHERE filename = %s", (filename,))
        deleted = cur.rowcount
        conn.commit()
        return deleted


def insert_chunk_batch(conn, rows: Iterable[dict[str, Any]]) -> None:
    """Insert a batch of chunk dicts (each already carrying its embedding list)."""
    payload = [
        (
            r["ticker"], r["company"], r["filename"], r["fiscal_year"],
            r["page_number"], r["chunk_index"], r["text"], r["token_count"],
            r["numeric_density"], r["may_contain_tabular_data"],
            to_vector_literal(r["embedding"]),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"""INSERT INTO {config.CHUNKS_TABLE}
                (ticker, company, filename, fiscal_year, page_number, chunk_index,
                 text, token_count, numeric_density, may_contain_tabular_data, embedding)
                VALUES %s
                ON CONFLICT (filename, chunk_index) DO NOTHING""",
            payload,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
        )
    conn.commit()


def record_ingestion(conn, meta: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {config.INGESTIONS_TABLE}
                (filename, ticker, company, fiscal_year, pages, chunks, tabular_chunks,
                 embed_model, embed_dim)
                VALUES (%(filename)s,%(ticker)s,%(company)s,%(fiscal_year)s,%(pages)s,
                        %(chunks)s,%(tabular_chunks)s,%(embed_model)s,%(embed_dim)s)
                ON CONFLICT (filename) DO UPDATE SET
                    pages=EXCLUDED.pages, chunks=EXCLUDED.chunks,
                    tabular_chunks=EXCLUDED.tabular_chunks,
                    embed_model=EXCLUDED.embed_model, embed_dim=EXCLUDED.embed_dim,
                    ingested_at=now()""",
            meta,
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# query-side helpers
# --------------------------------------------------------------------------- #
def similarity_search(
    query_embedding: Sequence[float],
    ticker: str,
    top_k: int,
    page_range: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Cosine-similarity search within one ticker's chunks.

    Returns rows ordered best-first with a ``similarity`` in [0, 1]
    (``1 - cosine_distance``).
    """
    vec = to_vector_literal(query_embedding)

    where = ["ticker = %s"]
    where_params: list[Any] = [ticker]
    if page_range is not None:
        where.append("page_number BETWEEN %s AND %s")
        where_params.extend([page_range[0], page_range[1]])

    sql = f"""
        SELECT filename, company, fiscal_year, page_number, chunk_index, text,
               token_count, numeric_density, may_contain_tabular_data,
               1 - (embedding <=> %s::vector) AS similarity
        FROM {config.CHUNKS_TABLE}
        WHERE {' AND '.join(where)}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    # param order matches the %s left-to-right: SELECT vec, WHERE..., ORDER BY vec, LIMIT
    params = [vec, *where_params, vec, top_k]

    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def corpus_summary() -> dict[str, Any]:
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""SELECT ticker, company, count(*) AS chunks,
                       count(*) FILTER (WHERE may_contain_tabular_data) AS tabular_chunks,
                       min(page_number) AS min_page, max(page_number) AS max_page
                FROM {config.CHUNKS_TABLE} GROUP BY ticker, company ORDER BY ticker"""
        )
        by_ticker = [dict(r) for r in cur.fetchall()]
        cur.execute(f"SELECT count(*) AS n FROM {config.CHUNKS_TABLE}")
        total = cur.fetchone()["n"]
    return {"total_chunks": total, "by_ticker": by_ticker}


def available_tickers() -> list[str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT ticker FROM {config.CHUNKS_TABLE} ORDER BY ticker")
        return [r[0] for r in cur.fetchall()]
