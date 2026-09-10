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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.filings_agent import INGESTED_TICKERS
from app import db, jobs

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
        "endpoints": ["POST /research", "GET /research/{job_id}", "GET /research/{job_id}/report", "GET /companies"],
    }


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
        "specialist_status": row["specialist_status"],
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
    annual report - limited to the ingested corpus (``INGESTED_TICKERS``).
    partial_coverage: any NSE-listed company that resolves on yfinance still gets
    market data + news/sentiment; filings analysis is simply skipped, with a
    stated reason in the routing trace.
    """
    from mcp_servers.filings_rag_mcp.config import COMPANY_NAMES

    full = [{"ticker": t, "name": COMPANY_NAMES.get(t, t)} for t in INGESTED_TICKERS]
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
                "report each), and is skipped with a reason for everything else."
            ),
        },
    }
