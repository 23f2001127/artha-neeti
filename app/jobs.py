"""Runs a Planner query as a background job and writes its progress to Postgres.

The progress callback stores routing as soon as it is decided and updates
``specialist_status`` as each specialist moves, so a polling client can show
the run as it happens. Chart data is built when the report is finished.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from agents import planner
from app import db, visuals

log = logging.getLogger("arthaneeti.jobs")


async def build_visuals(report: dict) -> dict | None:
    """Chart data for a report. Never raises: charts are additive, a failure
    here must not fail the research job."""
    try:
        return await asyncio.to_thread(visuals.build, report)
    except Exception:  # noqa: BLE001
        log.exception("visuals build failed")
        return None


async def ensure_visuals(job_id: str, row: dict) -> dict | None:
    """Return the report's chart data, building and persisting it for reports
    created before charts existed."""
    report = row.get("report") or {}
    if report.get("visuals"):
        return report["visuals"]
    built = await build_visuals(report)
    if built:
        report["visuals"] = built
        await asyncio.to_thread(db.update_job, job_id, report=report)
    return built


def _progress_writer(job_id: str) -> Callable[[dict], None]:
    """A sync callback the Planner invokes with state fragments. It writes straight
    through to the job row. Called from inside the Planner's event loop, but each
    write is a single-row UPDATE by primary key, so the brief block is fine here.
    """

    def write(frag: dict) -> None:
        patch: dict[str, Any] = {}
        if "routing_trace" in frag:
            patch["routing_trace"] = frag["routing_trace"]
        if "routing" in frag:
            patch["routing"] = frag["routing"]
        if "specialist_status" in frag:
            patch["specialist_status"] = frag["specialist_status"]
        if "mode" in frag:
            # Estimated once, when the run's shape is known, so the client has a
            # stable number to count down from.
            try:
                seconds, samples = db.estimate_duration_seconds(frag["mode"])
            except Exception:  # noqa: BLE001 - an ETA is a nicety, never fatal
                seconds, samples = None, 0
            if seconds is not None:
                patch["estimated_duration_seconds"] = seconds
                patch["estimated_duration_samples"] = samples
        if not patch:
            return
        try:
            db.update_job(job_id, **patch)
        except Exception:  # noqa: BLE001 - a failed progress write must not kill the run
            log.exception("progress write failed for job %s", job_id)

    return write


RUN_FAILED_MESSAGE = "The research run failed unexpectedly. Please try again."


async def _heartbeat(job_id: str) -> None:
    """Keeps updated_at fresh so other processes can tell this job is alive."""
    while True:
        await asyncio.sleep(db.HEARTBEAT_SECONDS)
        try:
            await asyncio.to_thread(db.touch_job, job_id)
        except Exception:  # noqa: BLE001
            log.warning("heartbeat failed for job %s", job_id, exc_info=True)


async def run_job(job_id: str, query: str) -> None:
    beat = asyncio.create_task(_heartbeat(job_id))
    try:
        await _run(job_id, query)
    finally:
        beat.cancel()


async def _run(job_id: str, query: str) -> None:
    try:
        db.update_job(job_id, status="running")
        result = await planner.plan(query, on_progress=_progress_writer(job_id))
    except BaseException:  # noqa: BLE001 - last line of defence; the planner guards its own nodes
        log.exception("job %s crashed", job_id)
        db.update_job(job_id, status="error", error=RUN_FAILED_MESSAGE)
        return

    # Only a total failure (no routing at all) is an error; a run where some
    # specialists failed still produces a degraded report.
    if isinstance(result, dict) and "error" in result and "routing" not in result:
        log.error("job %s failed: %s", job_id, result["error"])
        db.update_job(job_id, status="error", error=RUN_FAILED_MESSAGE, report=result)
    else:
        result["visuals"] = await build_visuals(result)
        db.update_job(
            job_id,
            status="done",
            report=result,
            specialist_status=(result or {}).get("specialist_status"),
        )
