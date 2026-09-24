"""Background jobs that add a company's annual report to the filings index,
either from an uploaded PDF or one found on the web.

Both paths end in ``ingest_file`` (the same chunk, embed and store pipeline the
seeded corpus uses), run in a worker thread with progress written to the job
row for the client to poll.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from agents.filings_agent import invalidate_ticker_cache
from app import db
from mcp_servers.filings_rag_mcp.embeddings import EmbeddingQuotaError
from mcp_servers.filings_rag_mcp.fetch import FetchError, fetch_filing_pdf
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


def _validate_ticker(ticker: str) -> str:
    norm = normalize_ticker(ticker)
    if not norm or not re.fullmatch(r"[A-Z0-9&.\-]{1,20}", norm):
        raise UploadError("ticker looks invalid - use the NSE-style symbol, e.g. RELIANCE, M&M.")
    return norm


def validate_upload(filename: str, size: int, ticker: str) -> str:
    """Raises UploadError with a client-facing message, or returns the
    normalized ticker."""
    if not filename.lower().endswith(".pdf"):
        raise UploadError("only PDF files are accepted.")
    if size <= 0:
        raise UploadError("the uploaded file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise UploadError(f"file is {size / 1e6:.1f}MB - the limit is {MAX_UPLOAD_BYTES / 1e6:.0f}MB.")
    return _validate_ticker(ticker)


def validate_fetch_request(ticker: str) -> str:
    return _validate_ticker(ticker)


def _save_pdf(content: bytes, job_id: str, ticker: str, tag: str) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # job_id in the filename guarantees uniqueness across concurrent/duplicate
    # jobs for the same ticker - ingest_file's DB identity key is the filename.
    dest = UPLOAD_DIR / f"{ticker}_{tag}_{job_id}.pdf"
    dest.write_bytes(content)
    return dest


def save_upload(content: bytes, job_id: str, ticker: str) -> Path:
    return _save_pdf(content, job_id, ticker, "UPLOAD")


async def _ingest_and_finish(
    job_id: str, pdf_path: Path, *, ticker: str, company: str | None, fiscal_year: str | None
) -> None:
    def progress(embedded: int, total: int) -> None:
        try:
            db.update_upload_job(job_id, status="running", chunks_done=embedded, chunks_total=total, detail=None)
        except Exception:  # noqa: BLE001 - a failed progress write must not kill the run
            log.exception("progress write failed for filing job %s", job_id)

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
        db.update_upload_job(job_id, status="running", detail="parsing and embedding the PDF...")
        result = await asyncio.to_thread(do_ingest)
    except EmbeddingQuotaError as exc:
        log.warning("filing job %s stopped on embedding quota: %s", job_id, exc)
        db.update_upload_job(
            job_id, status="error",
            error=f"Daily embedding quota reached partway through: {exc}. "
                  f"Try again after the quota resets - it restarts this file "
                  f"from the beginning (partial embeddings aren't kept).",
        )
        return
    except BaseException as exc:  # noqa: BLE001 - last line for this job
        log.exception("filing job %s crashed", job_id)
        db.update_upload_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}")
        return

    if result.get("skipped"):
        db.update_upload_job(job_id, status="error", error="no extractable text found in this PDF.")
        return

    db.update_upload_job(job_id, status="done", chunks=result["chunks"], chunks_done=result["chunks"])
    invalidate_ticker_cache()


async def run_upload_job(
    job_id: str, pdf_path: Path, *, ticker: str, company: str | None, fiscal_year: str | None
) -> None:
    await _ingest_and_finish(job_id, pdf_path, ticker=ticker, company=company, fiscal_year=fiscal_year)


async def run_fetch_job(job_id: str, *, ticker: str, company: str | None, fiscal_year: str | None) -> None:
    """Search the web for a downloadable annual-report PDF and ingest it -
    same tail as an upload, just a different source for the PDF bytes."""

    def do_fetch():
        return fetch_filing_pdf(company or ticker, fiscal_year, max_bytes=MAX_UPLOAD_BYTES)

    try:
        db.update_upload_job(job_id, status="running", detail="searching the web for a PDF...")
        content, hit = await asyncio.to_thread(do_fetch)
    except FetchError as exc:
        log.info("fetch job %s: %s", job_id, exc)
        db.update_upload_job(job_id, status="error", error=str(exc))
        return
    except BaseException as exc:  # noqa: BLE001 - last line for this job
        log.exception("fetch job %s crashed while searching/downloading", job_id)
        db.update_upload_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}")
        return

    db.update_upload_job(job_id, source_url=hit["url"], detail=f"downloaded from {hit['url']}")
    pdf_path = await asyncio.to_thread(_save_pdf, content, job_id, ticker, "FETCH")
    await _ingest_and_finish(job_id, pdf_path, ticker=ticker, company=company, fiscal_year=fiscal_year)
