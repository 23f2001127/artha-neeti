"""Framework-agnostic retrieval logic (the real work behind the MCP tools).

Same conventions as market_data_mcp / research_mcp: plain args in, plain dicts out,
``{"error": "..."}`` on failure (never raises), an ``as_of`` timestamp on success.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import config, db
from .db import DBError
from .embeddings import EmbeddingError, embed_query

# statement_type -> (semantic query, header keywords for the ILIKE boost)
_STATEMENT_QUERIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "balance_sheet": (
        "balance sheet: total assets, total liabilities, equity, share capital, "
        "reserves and surplus, borrowings, as at 31 March",
        ("consolidated balance sheet", "standalone balance sheet", "total equity and liabilities"),
    ),
    "income_statement": (
        "statement of profit and loss: total revenue from operations, other income, "
        "total expenses, profit before tax, tax expense, profit for the year, "
        "earnings per share",
        # the actual statement headers - "statement of profit and loss" alone also
        # matches every note that references the P&L, so require the fuller phrase.
        ("consolidated statement of profit and loss", "standalone statement of profit and loss",
         "statement of profit and loss for the year"),
    ),
    "cash_flow": (
        "cash flow statement: net cash from operating activities, investing "
        "activities, financing activities, net increase decrease in cash and cash "
        "equivalents",
        ("statement of cash flows", "cash flow statement", "cash flows from operating activities"),
    ),
    "equity_changes": (
        "statement of changes in equity: opening balance, profit for the year, "
        "other comprehensive income, dividends, closing balance",
        ("statement of changes in equity", "changes in equity"),
    ),
}
_STATEMENT_ALIASES = {
    "income statement": "income_statement",
    "profit and loss": "income_statement",
    "p&l": "income_statement",
    "pnl": "income_statement",
    "balance sheet": "balance_sheet",
    "cash flow": "cash_flow",
    "cash flow statement": "cash_flow",
    "cashflow": "cash_flow",
    "changes in equity": "equity_changes",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_ticker(ticker: str) -> str:
    t = str(ticker or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t


def _format_hit(row: dict[str, Any]) -> dict[str, Any]:
    sim = row.get("similarity")
    return {
        "page_number": row["page_number"],
        "similarity": round(float(sim), 4) if sim is not None else None,
        "may_contain_tabular_data": row["may_contain_tabular_data"],
        "numeric_density": round(float(row["numeric_density"] or 0.0), 3),
        "filename": row["filename"],
        "fiscal_year": row["fiscal_year"],
        "text": row["text"],
    }


def _ensure_ticker_available(ticker: str) -> str | None:
    try:
        available = db.available_tickers()
    except DBError as exc:
        return f"database error: {exc}"
    if ticker not in available:
        return (
            f"No ingested filing for '{ticker}'. Ingested tickers: "
            f"{', '.join(available) or '(none - run ingest.py first)'}."
        )
    return None


# --------------------------------------------------------------------------- #
def search_filing(query: str, ticker: str, top_k: int = 5) -> dict:
    """Semantic search within one company's annual report."""
    if not query or not str(query).strip():
        return {"error": "query is empty."}
    ticker = _resolve_ticker(ticker)
    if not ticker:
        return {"error": "ticker is empty."}
    top_k = max(1, min(int(top_k) if str(top_k).lstrip("-").isdigit() else 5, 20))

    err = _ensure_ticker_available(ticker)
    if err:
        return {"error": err}

    try:
        qvec = embed_query(str(query).strip())
    except EmbeddingError as exc:
        return {"error": f"could not embed the query: {exc}"}
    try:
        rows = db.similarity_search(qvec, ticker, top_k)
    except DBError as exc:
        return {"error": f"database error: {exc}"}

    hits = [_format_hit(r) for r in rows]
    return {
        "ticker": ticker,
        "company": config.company_name(ticker),
        "query": str(query).strip(),
        "top_k": top_k,
        "count": len(hits),
        "results": hits,
        "as_of": _now(),
        "note": (
            "Similarity is cosine (1.0 = identical direction). Chunks with "
            "may_contain_tabular_data=true are likely a financial-statement table "
            "that PDF extraction has flattened into run-on text - read the numbers "
            "with care and cite the page."
        ),
    }


def get_financial_statement_section(ticker: str, statement_type: str) -> dict:
    """Targeted retrieval of a named financial statement from the filing.

    Approach: a hand-written semantic query per statement type, plus a keyword
    boost - chunks whose text contains the statement's header phrase are pulled in
    and ranked first. No hard page-range assumption: annual-report structure is
    only *roughly* predictable (statements sit in the back third, standalone before
    consolidated) and varies by company, so we let similarity + keywords find it
    and report the pages we landed on. Limits: see README.
    """
    ticker = _resolve_ticker(ticker)
    if not ticker:
        return {"error": "ticker is empty."}
    raw_type = str(statement_type or "").strip().lower()
    key = _STATEMENT_ALIASES.get(raw_type, raw_type.replace(" ", "_"))
    if key not in _STATEMENT_QUERIES:
        return {
            "error": f"unknown statement_type '{statement_type}'. Supported: "
            f"{', '.join(sorted(_STATEMENT_QUERIES))} (aliases: 'income statement', "
            f"'balance sheet', 'cash flow', 'changes in equity')."
        }

    err = _ensure_ticker_available(ticker)
    if err:
        return {"error": err}

    semantic_query, keywords = _STATEMENT_QUERIES[key]
    try:
        qvec = embed_query(semantic_query)
    except EmbeddingError as exc:
        return {"error": f"could not embed the query: {exc}"}

    try:
        semantic_rows = db.similarity_search(qvec, ticker, 12)
        keyword_rows = _keyword_rows(ticker, keywords, limit=4)
    except DBError as exc:
        return {"error": f"database error: {exc}"}

    # merge: keyword-matched chunks first (they literally contain the header),
    # then the rest by similarity, de-duplicated on (page, chunk_index)
    seen: set[tuple[int, int]] = set()
    merged: list[dict[str, Any]] = []
    for row in keyword_rows + semantic_rows:
        pk = (row["page_number"], row["chunk_index"])
        if pk in seen:
            continue
        seen.add(pk)
        merged.append(row)
    merged = merged[:8]

    hits = [{**_format_hit(r), "matched_header_keyword": r.get("_kw")} for r in merged]
    pages = sorted({h["page_number"] for h in hits})
    return {
        "ticker": ticker,
        "company": config.company_name(ticker),
        "statement_type": key,
        "semantic_query": semantic_query,
        "pages_returned": pages,
        "count": len(hits),
        "results": hits,
        "as_of": _now(),
        "note": (
            "Search-based, not a parsed statement. Chunks come from a semantic query "
            "for this statement plus a header-keyword boost; most will have "
            "may_contain_tabular_data=true and the numbers may be column-flattened. "
            "A company usually files both standalone and consolidated versions - "
            "results can mix the two; check the surrounding text on the cited page."
        ),
    }


def compare_yoy_metrics(ticker: str, metric: str) -> dict:
    """Year-over-year figures for a metric, AS REPORTED WITHIN THE SINGLE FILING.

    HONEST SCOPE: ArthaNeeti holds exactly one annual report per company, so this
    is **not** a comparison across separate years' filings. It retrieves the
    filing's own year-on-year disclosure - the current + prior-year columns in the
    statements, and the MD&A / Board's Report commentary ("Revenue grew X% Y-o-Y")
    - for the requested metric. For a true multi-year trend you would need to
    ingest prior years' reports (out of scope for v1). See README.
    """
    ticker = _resolve_ticker(ticker)
    if not ticker:
        return {"error": "ticker is empty."}
    if not metric or not str(metric).strip():
        return {"error": "metric is empty."}
    metric = str(metric).strip()

    err = _ensure_ticker_available(ticker)
    if err:
        return {"error": err}

    fy = _fiscal_year_for(ticker)
    semantic_query = (
        f"{metric}: year-over-year change, growth or decline versus the previous "
        f"year, current year compared to prior year, {fy or 'FY25'} vs the year "
        f"before, percentage increase or decrease"
    )
    try:
        qvec = embed_query(semantic_query)
    except EmbeddingError as exc:
        return {"error": f"could not embed the query: {exc}"}
    try:
        semantic_rows = db.similarity_search(qvec, ticker, 12)
        yoy_rows = _keyword_rows(
            ticker,
            ("y-o-y", "year-on-year", "year on year", "compared to the previous year",
             "over the previous year", "vis-a-vis", "versus"),
            limit=8,
        )
    except DBError as exc:
        return {"error": f"database error: {exc}"}

    seen: set[tuple[int, int]] = set()
    merged: list[dict[str, Any]] = []
    for row in yoy_rows + semantic_rows:
        pk = (row["page_number"], row["chunk_index"])
        if pk not in seen:
            seen.add(pk)
            merged.append(row)
    hits = [{**_format_hit(r), "matched_yoy_phrase": r.get("_kw")} for r in merged[:8]]

    return {
        "ticker": ticker,
        "company": config.company_name(ticker),
        "metric": metric,
        "fiscal_year": fy,
        "basis": (
            f"single filing's own reported year-over-year figures "
            f"({fy or 'the filing year'} vs the prior year, as stated in the document)"
        ),
        "limitation": (
            "NOT a cross-filing multi-year comparison - ArthaNeeti has one annual "
            "report per company. Trend analysis beyond the two years this filing "
            "itself reports is not possible here."
        ),
        "count": len(hits),
        "results": hits,
        "as_of": _now(),
    }


# --------------------------------------------------------------------------- #
def _keyword_rows(ticker: str, keywords: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
    """Chunks for a ticker whose text ILIKE-matches any keyword, tabular-first."""
    import psycopg2.extras

    clauses = " OR ".join(["text ILIKE %s"] * len(keywords))
    params = [ticker, *[f"%{k}%" for k in keywords], limit]
    # page_number > 8: no financial statement sits in the first pages of a
    # 150-360pp annual report, but the table of contents lists every statement
    # header - excluding the front matter kills that false match.
    sql = f"""
        SELECT filename, company, fiscal_year, page_number, chunk_index, text,
               token_count, numeric_density, may_contain_tabular_data,
               NULL::float AS similarity
        FROM {config.CHUNKS_TABLE}
        WHERE ticker = %s AND page_number > 8 AND ({clauses})
        ORDER BY may_contain_tabular_data DESC, page_number
        LIMIT %s
    """
    with db.connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["_kw"] = next(
            (k for k in keywords if k.lower() in (r["text"] or "").lower()), None
        )
    return rows


def _fiscal_year_for(ticker: str) -> str | None:
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT fiscal_year FROM {config.CHUNKS_TABLE} WHERE ticker = %s LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except DBError:
        return None
