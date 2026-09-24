"""ArthaNeeti HTTP API.

Research runs take minutes, so they are jobs: POST /research stores a row and
starts the Planner in the background, and clients poll GET /research/{job_id}
for routing, per-specialist progress and the finished report. Job state lives
in Postgres; see app/README.md for the full endpoint reference.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.filings_agent import ingested_tickers
from app import db, filings, followups, jobs
from app.report_pdf import render_report_pdf
from shared import llm_rate_limiter as rl

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arthaneeti.api")

# The event loop holds tasks weakly; keep background jobs alive until they finish.
_TASKS: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_schema()
    interrupted = db.fail_stale_jobs()
    if interrupted:
        log.warning("closed %d job(s) left unfinished by a previous process", interrupted)
    yield


app = FastAPI(
    title="ArthaNeeti",
    version="0.1.0",
    description="Multi-agent research on NSE-listed companies.",
    lifespan=lifespan,
)

# Localhost is always allowed; deployed frontends are listed in
# CORS_ALLOWED_ORIGINS (comma-separated).
_cors_extra_origins = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_origins=_cors_extra_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# The daily cap is global rather than per visitor: the LLM quota it protects is
# shared by every user of the deployment. 0 disables it.
_MAX_DAILY_JOBS = int(os.environ.get("MAX_DAILY_JOBS", "0"))

# Burst protection per client IP. In memory: it only has to hold within one process.
_THROTTLE_WINDOW_S = 60.0
_THROTTLE_MAX_PER_WINDOW = int(os.environ.get("IP_THROTTLE_PER_MINUTE", "6"))
_ip_hits: dict[str, deque[float]] = defaultdict(deque)


def _check_ip_throttle(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    hits = _ip_hits[ip]
    while hits and now - hits[0] > _THROTTLE_WINDOW_S:
        hits.popleft()
    if len(hits) >= _THROTTLE_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many requests - please slow down and try again shortly.")
    hits.append(now)


def _check_daily_job_cap() -> None:
    if _MAX_DAILY_JOBS <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = db.count_jobs_since(cutoff)
    if count >= _MAX_DAILY_JOBS:
        raise HTTPException(
            status_code=429,
            detail="Today's research limit has been reached. Please try again tomorrow.",
        )


class ResearchRequest(BaseModel):
    query: str = Field(
        min_length=3,
        max_length=500,
        examples=["give me a complete research view on TCS"],
    )


@app.get("/")
def root() -> dict:
    return {
        "name": "ArthaNeeti research API",
        "docs": "/docs",
        "endpoints": [
            "POST /research", "GET /research/{job_id}", "GET /research/{job_id}/report",
            "GET /research/{job_id}/visuals", "GET /research/{job_id}/report.pdf",
            "POST /research/{job_id}/followups", "GET /research/{job_id}/followups",
            "POST /research/{job_id}/followups/escalate",
            "GET /companies", "POST /filings/upload", "POST /filings/fetch",
            "GET /filings/jobs/{job_id}", "GET /status",
        ],
    }


@app.get("/status")
def status() -> dict:
    """Current usage of each rate-limited LLM bucket."""
    return {"buckets": rl.snapshot()}


@app.post("/research", status_code=202)
async def submit_research(req: ResearchRequest, request: Request) -> dict:
    """Queue a research job and return its id; poll GET /research/{job_id}."""
    _check_ip_throttle(request)
    _check_daily_job_cap()
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
    if row["status"] in ("queued", "running") and await asyncio.to_thread(db.fail_stale_jobs, str(job_id)):
        row = await asyncio.to_thread(db.get_job, str(job_id))
    return {
        "job_id": str(row["job_id"]),
        "query": row["query"],
        "status": row["status"],
        "routing_trace": row["routing_trace"],
        "routing": row["routing"],
        "specialist_status": row["specialist_status"],
        "estimated_duration_seconds": row["estimated_duration_seconds"],
        "estimated_duration_samples": row["estimated_duration_samples"],
        "report": row["report"],
        "error": row["error"],
        "conversation_id": str(row["conversation_id"]) if row["conversation_id"] else None,
        "parent_job_id": str(row["parent_job_id"]) if row["parent_job_id"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class FollowupRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500, examples=["what was its ROE again?"])


class EscalateFollowupRequest(BaseModel):
    standalone_query: str = Field(min_length=1, max_length=500)


@app.get("/research/{job_id}/report")
async def get_report(job_id: uuid.UUID) -> dict:
    """The finished report; 409 while the job is still queued or running."""
    row = await asyncio.to_thread(db.get_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in ("done", "error") or row["report"] is None:
        raise HTTPException(status_code=409, detail=f"job is '{row['status']}', report not ready")
    return row["report"]


@app.get("/research/{job_id}/visuals")
async def get_visuals(job_id: uuid.UUID) -> dict:
    """Chart data for a finished report: price history, KPIs, financial trends,
    margins, sentiment and (for multi-company reports) a comparison block."""
    row = await asyncio.to_thread(db.get_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] != "done" or not row["report"]:
        raise HTTPException(status_code=409, detail=f"job is '{row['status']}', report not ready")
    visuals = await jobs.ensure_visuals(str(job_id), row)
    if not visuals:
        raise HTTPException(status_code=404, detail="no chart data available for this report")
    return visuals


@app.get("/research/{job_id}/report.pdf")
async def get_report_pdf(job_id: uuid.UUID) -> Response:
    """The finished report as a downloadable PDF, charts included."""
    row = await asyncio.to_thread(db.get_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in ("done", "error") or row["report"] is None:
        raise HTTPException(status_code=409, detail=f"job is '{row['status']}', report not ready")
    report = row["report"]
    if row["status"] == "done" and not report.get("visuals"):
        visuals = await jobs.ensure_visuals(str(job_id), row)
        if visuals:
            report = {**report, "visuals": visuals}
    try:
        pdf_bytes = await asyncio.to_thread(render_report_pdf, report)
    except Exception as exc:  # noqa: BLE001
        log.exception("PDF render failed for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"could not render PDF: {exc}") from exc

    tickers = list((row["report"].get("reports") or {}).keys())
    slug = "-".join(t.lower() for t in tickers) or "report"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="arthaneeti-{slug}.pdf"'},
    )


@app.post("/research/{job_id}/followups")
async def ask_followup(job_id: uuid.UUID, req: FollowupRequest) -> dict:
    """Answer a follow-up question from the finished report in one LLM call.

    When the report can't answer it, the response carries
    ``sufficient_data: false`` and a ``standalone_query`` to send to
    .../followups/escalate for a new research run."""
    try:
        return await followups.ask(str(job_id), req.query.strip())
    except followups.FollowupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/research/{job_id}/followups")
async def list_followups(job_id: uuid.UUID) -> dict:
    """Past follow-up turns for this job's conversation (chronological)."""
    row = await asyncio.to_thread(db.get_job, str(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    conversation_id = row["conversation_id"] or row["job_id"]
    turns = await asyncio.to_thread(db.get_followup_turns, str(conversation_id))
    return {
        "conversation_id": str(conversation_id),
        "turns": [
            {
                "query": t["query"],
                "answer": t["answer"],
                "sufficient_data": t["sufficient_data"],
                "caveat": t["caveat"],
                "missing_reason": t["missing_reason"],
                "standalone_query": t["standalone_query"],
                "created_at": t["created_at"],
            }
            for t in turns
        ],
    }


@app.post("/research/{job_id}/followups/escalate", status_code=202)
async def escalate_followup(job_id: uuid.UUID, req: EscalateFollowupRequest, request: Request) -> dict:
    """Start a new research job that continues this conversation."""
    _check_ip_throttle(request)
    _check_daily_job_cap()
    try:
        new_job_id = await asyncio.to_thread(
            followups.create_escalation_job, str(job_id), req.standalone_query
        )
    except followups.FollowupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task = asyncio.create_task(jobs.run_job(new_job_id, req.standalone_query.strip()))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job_id": new_job_id, "status": "queued"}


@app.get("/companies")
def list_companies() -> dict:
    """Companies with an indexed annual report (all three specialists), and the
    market-data-and-news coverage every other NSE company gets."""
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
                "Any NSE-listed company. Annual-report analysis needs the company's report "
                "indexed first: POST /filings/upload or POST /filings/fetch."
            ),
        },
    }


class FetchFilingRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, examples=["ITC"])
    company: str | None = Field(None, max_length=200, examples=["ITC Limited"])
    fiscal_year: str | None = Field(None, max_length=20, examples=["2024-25"])


@app.post("/filings/upload", status_code=202)
async def upload_filing(
    request: Request,
    file: UploadFile = File(..., description="The annual-report PDF."),
    ticker: str = Form(..., description="NSE-style symbol, e.g. RELIANCE, M&M."),
    company: str | None = Form(None, description="Display name; defaults to the ticker."),
    fiscal_year: str | None = Form(None, description="e.g. '2024-25'; left blank if unknown."),
) -> dict:
    """Index an uploaded annual-report PDF; poll GET /filings/jobs/{job_id}."""
    _check_ip_throttle(request)
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
async def fetch_filing(req: FetchFilingRequest, request: Request) -> dict:
    """Search for the company's annual-report PDF and index it.

    Only direct PDF links in search results are accepted; when none is found the
    job ends in 'error' and the client should offer an upload instead."""
    _check_ip_throttle(request)
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
