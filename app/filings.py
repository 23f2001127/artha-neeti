"""Runs an ad-hoc filing upload as a background job, mirroring app/jobs.py's
shape for research jobs: a job row is the source of truth, a detached asyncio
task does the work, and a client polls for progress.

The actual chunk/embed/store pipeline is unchanged from the seeded corpus's
CLI ingestion (mcp_servers/filings_rag_mcp/ingest.py's ``ingest_file``) - this
module's only job is: validate the upload, save it under a unique filename,
run that pipeline in a worker thread (it's blocking I/O - embedding HTTP calls
+ psycopg2), and stream its progress into Postgres.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from agents.filings_agent import invalidate_ticker_cache
from app import db
from mcp_servers.filings_rag_mcp.embeddings import EmbeddingQuotaError
from mcp_servers.filings_rag_mcp.ingest import ingest_file

log = logging.getLogger("arthaneeti.filings")

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "data" / "uploads"
MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # 40MB - generous for a single annual report


class UploadError(ValueError):
    """A bad request (not our fault to retry) - bad file type, too large, bad ticker."""


def normalize_ticker(raw: str) -> str:
    t = (raw or "").strip().upper()
    for suf in (".NS", ".BO"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t


def validate_upload(filename: str, size: int, ticker: str) -> str:
    """Raises UploadError with a client-facing message, or returns the
    normalized ticker."""
    if not filename.lower().endswith(".pdf"):
        raise UploadError("only PDF files are accepted.")
    if size <= 0:
        raise UploadError("the uploaded file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise UploadError(f"file is {size / 1e6:.1f}MB - the limit is {MAX_UPLOAD_BYTES / 1e6:.0f}MB.")
    norm = normalize_ticker(ticker)
    if not norm or not re.fullmatch(r"[A-Z0-9&.\-]{1,20}", norm):
        raise UploadError("ticker looks invalid - use the NSE-style symbol, e.g. RELIANCE, M&M.")
    return norm


def save_upload(content: bytes, job_id: str, ticker: str) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # job_id in the filename guarantees uniqueness across concurrent/duplicate
    # uploads of the same ticker - ingest_file's DB identity key is the filename.
    dest = UPLOAD_DIR / f"{ticker}_UPLOAD_{job_id}.pdf"
    dest.write_bytes(content)
    return dest


async def run_upload_job(
    job_id: str, pdf_path: Path, *, ticker: str, company: str | None, fiscal_year: str | None
) -> None:
    def progress(embedded: int, total: int) -> None:
        try:
            db.update_upload_job(job_id, status="running", chunks_done=embedded, chunks_total=total)
        except Exception:  # noqa: BLE001 - a failed progress write must not kill the run
            log.exception("progress write failed for upload job %s", job_id)

    def do_ingest() -> dict:
        return ingest_file(
            pdf_path,
            ticker=ticker,
            company=company or ticker,
            fiscal_year=fiscal_year,
            progress_cb=progress,
            log=lambda msg: log.info("[%s] %s", job_id, msg),
        )

    try:
        db.update_upload_job(job_id, status="running")
        result = await asyncio.to_thread(do_ingest)
    except EmbeddingQuotaError as exc:
        log.warning("upload job %s stopped on embedding quota: %s", job_id, exc)
        db.update_upload_job(
            job_id, status="error",
            error=f"Daily embedding quota reached partway through: {exc}. "
                  f"Re-upload the same file after the quota resets - it restarts "
                  f"this file from the beginning (partial embeddings aren't kept).",
        )
        return
    except BaseException as exc:  # noqa: BLE001 - last line for this job
        log.exception("upload job %s crashed", job_id)
        db.update_upload_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}")
        return

    if result.get("skipped"):
        db.update_upload_job(job_id, status="error", error="no extractable text found in this PDF.")
        return

    db.update_upload_job(job_id, status="done", chunks=result["chunks"], chunks_done=result["chunks"])
    invalidate_ticker_cache()
