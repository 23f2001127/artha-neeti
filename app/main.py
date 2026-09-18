"""ArthaNeeti research API - a job-based wrapper around ``agents.planner``.

A Planner query takes 1-20+ minutes (free-tier LLM pacing), so this layer never
blocks a request on a run:

    POST /research            -> creates a job row, fires the Planner as a
                                 detached asyncio task, returns {job_id} at once
    GET  /research/{job_id}   -> the poll endpoint: status + routing_trace (as
                                 soon as the route node finishes) + live
                                 specialist_status + the final report when done
    GET  /research/{job_id}/report -> just the finished report (409 until done)
    GET  /companies           -> full-coverage (3 specialists) vs partial (market
                                 data + news only) so a client can be upfront

All job state lives in Postgres (``research_jobs``); the in-memory task handle is
only kept so it isn't garbage-collected and so failures get logged.

Run:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.filings_agent import ingested_tickers
from app import db, filings, jobs
from shared import llm_rate_limiter as rl

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arthaneeti.api")

_TASKS: set[asyncio.Task] = set()  # strong refs so background jobs aren't GC'd


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_schema()
    log.info("research_jobs schema ready")
    yield


app = FastAPI(
    title="ArthaNeeti",
    version="0.1.0",
    description="Multi-agent Indian equity research - job-based API over the LangGraph Planner.",
    lifespan=lifespan,
)

# CORS: wide open for local frontend development.
# ------------------------------------------------------------------------------
# TIGHTEN THIS BEFORE ANY PUBLIC DEPLOYMENT. Replace allow_origin_regex with an
# explicit allow_origins list of the real frontend origin(s), and review whether
# credentials should be allowed.
# ------------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


class ResearchRequest(BaseModel):
    query: str = Field(
        min_length=3,
        max_length=500,
        examples=["give me a complete research view on TCS"],
    )


# --------------------------------------------------------------------------- #
@app.get("/")
def root() -> dict:
    return {
        "name": "ArthaNeeti research API",
        "docs": "/docs",
        "endpoints": [
            "POST /research", "GET /research/{job_id}", "GET /research/{job_id}/report",
            "GET /companies", "POST /filings/upload", "POST /filings/fetch",
            "GET /filings/jobs/{job_id}", "GET /status",
        ],
    }


@app.get("/status")
def status() -> dict:
    """Live shared-quota usage per LLM provider bucket (Groq, Gemini generate,
    Gemini embed) - the same accounting `shared/llm_rate_limiter.py` uses to
    pace every call, exposed read-only. Useful for explaining a slow run (a
    bucket near its daily/per-minute cap) rather than leaving it a mystery."""
    return {"buckets": rl.snapshot()}


@app.post("/research", status_code=202)
async def submit_research(req: ResearchRequest) -> dict:
    """Queue a research job. Returns immediately; poll GET /research/{job_id}.

    The run is a detached ``asyncio.create_task`` rather than FastAPI
    ``BackgroundTasks``: BackgroundTasks are tied to this request's response
    lifecycle and give no handle to observe or log. This is a long-lived job
    whose authoritative state is the Postgres row - a bare task on the event
    loop models that better. (Trade-off: a server restart orphans in-flight
    jobs, leaving their row at 'running'. A production build would use a real
    queue or sweep stale rows on startup.)
    """
    query = req.query.strip()
    job_id = await asyncio.to_thread(db.create_job, query)
    task = asyncio.create_task(jobs.run_job(job_id, query))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job_id": job_id, "status": "queued"}


@app.get("/research/{job_id}")
async def get_research(job_id: uuid.UUID) -> dict:
    row = await asyncio.to_thread(db.get_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": str(row["job_id"]),
        "query": row["query"],
        "status": row["status"],
        "routing_trace": row["routing_trace"],
        "routing": row["routing"],  # structured decision, set the same moment as routing_trace
        "specialist_status": row["specialist_status"],
        "estimated_duration_seconds": row["estimated_duration_seconds"],  # real historical avg; null until routing lands or there's no history yet
        "estimated_duration_samples": row["estimated_duration_samples"],  # how many past jobs backed that number
        "report": row["report"],  # null until the run finishes
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@app.get("/research/{job_id}/report")
async def get_report(job_id: uuid.UUID) -> dict:
    """Just the finished report. 409 while the job is still queued/running, so a
    client can call this directly once it sees status == 'done' from the poll."""
    row = await asyncio.to_thread(db.get_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in ("done", "error") or row["report"] is None:
        raise HTTPException(status_code=409, detail=f"job is '{row['status']}', report not ready")
    return row["report"]


@app.get("/companies")
def list_companies() -> dict:
    """What the system can meaningfully answer about.

    full_coverage: all three specialists, including RAG over the company's actual
    annual report - the seeded corpus plus anything since uploaded or auto-fetched
    (``agents.filings_agent.ingested_tickers()``, DB-backed).
    partial_coverage: any NSE-listed company that resolves on yfinance still gets
    market data + news/sentiment; filings analysis is simply skipped, with a
    stated reason in the routing trace.
    """
    from mcp_servers.filings_rag_mcp import db as filings_db

    names = filings_db.company_names()
    full = [{"ticker": t, "name": names.get(t, t)} for t in ingested_tickers()]
    return {
        "full_coverage": {
            "specialists": ["market_data", "news_sentiment", "filings"],
            "count": len(full),
            "companies": full,
        },
        "partial_coverage": {
            "specialists": ["market_data", "news_sentiment"],
            "note": (
                "Any NSE-listed company that resolves on yfinance. Filings analysis "
                "is only available for the full-coverage list above (one annual "
                "report each), and is skipped with a reason for everything else. "
                "Missing a company's filing? POST /filings/upload adds one, or "
                "POST /filings/fetch tries to find and ingest it automatically."
            ),
        },
    }


class FetchFilingRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, examples=["ITC"])
    company: str | None = Field(None, max_length=200, examples=["ITC Limited"])
    fiscal_year: str | None = Field(None, max_length=20, examples=["2024-25"])


@app.post("/filings/upload", status_code=202)
async def upload_filing(
    file: UploadFile = File(..., description="The annual-report PDF."),
    ticker: str = Form(..., description="NSE-style symbol, e.g. RELIANCE, M&M."),
    company: str | None = Form(None, description="Display name; defaults to the ticker."),
    fiscal_year: str | None = Form(None, description="e.g. '2024-25'; left blank if unknown."),
) -> dict:
    """Ingest an ad-hoc annual-report PDF into the filings RAG corpus, so the
    Filings Agent (and Planner routing) can answer questions about a company
    outside the 10 seeded ones. Returns immediately; poll
    GET /filings/jobs/{job_id}. Same asyncio.create_task pattern as
    POST /research, for the same reason - this can run for minutes against the
    shared embedding rate limit.
    """
    content = await file.read()
    try:
        norm_ticker = filings.validate_upload(file.filename or "", len(content), ticker)
    except filings.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = await asyncio.to_thread(
        db.create_upload_job,
        ticker=norm_ticker, company=(company or None), fiscal_year=(fiscal_year or None),
        filename=file.filename or "upload.pdf", source="upload",
    )
    pdf_path = await asyncio.to_thread(filings.save_upload, content, job_id, norm_ticker)
    task = asyncio.create_task(
        filings.run_upload_job(
            job_id, pdf_path, ticker=norm_ticker, company=company, fiscal_year=fiscal_year
        )
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job_id": job_id, "status": "queued", "ticker": norm_ticker}


@app.post("/filings/fetch", status_code=202)
async def fetch_filing(req: FetchFilingRequest) -> dict:
    """Best-effort alternative to /filings/upload: search the web for the
    company's annual-report PDF and ingest it automatically - no file needed.

    This is genuinely best-effort (see mcp_servers/filings_rag_mcp/fetch.py's
    docstring for exactly why): it only accepts a search result that is
    itself a direct PDF link, and does not scrape HTML pages for one. A miss
    ends the job with status='error' and a message pointing at
    POST /filings/upload as the reliable fallback - it is not a bug, just a
    search that didn't turn up a direct link this time.
    """
    try:
        norm_ticker = filings.validate_fetch_request(req.ticker)
    except filings.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = await asyncio.to_thread(
        db.create_upload_job,
        ticker=norm_ticker, company=req.company, fiscal_year=req.fiscal_year,
        filename=f"{norm_ticker} (auto-fetch)", source="fetch",
    )
    task = asyncio.create_task(
        filings.run_fetch_job(job_id, ticker=norm_ticker, company=req.company, fiscal_year=req.fiscal_year)
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job_id": job_id, "status": "queued", "ticker": norm_ticker}


@app.get("/filings/jobs/{job_id}")
async def get_filing_job(job_id: uuid.UUID) -> dict:
    row = await asyncio.to_thread(db.get_upload_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="filing job not found")
    return {
        "job_id": str(row["job_id"]),
        "ticker": row["ticker"],
        "company": row["company"],
        "fiscal_year": row["fiscal_year"],
        "filename": row["filename"],
        "source": row["source"],
        "source_url": row["source_url"],
        "detail": row["detail"],
        "status": row["status"],
        "chunks_done": row["chunks_done"],
        "chunks_total": row["chunks_total"],
        "chunks": row["chunks"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
