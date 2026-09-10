"""Runs a Planner query as a background job, streaming its progress into Postgres.

``run_job`` is what ``POST /research`` fires off as a detached ``asyncio`` task.
It calls ``agents.planner.plan`` as-is (no reimplementation) and passes it a
progress callback that writes the graph's intermediate state to the job row as it
advances - so a client polling ``GET /research/{id}`` sees routing decisions land
before the specialists finish, and ``specialist_status`` flip pending -> ok/error
one agent at a time.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from agents import planner
from app import db

log = logging.getLogger("arthaneeti.jobs")


def _progress_writer(job_id: str) -> Callable[[dict], None]:
    """A sync callback the Planner invokes with state fragments. It writes straight
    through to the job row. Called from inside the Planner's event loop, but each
    write is a single-row UPDATE by primary key, so the brief block is fine here.
    """

    def write(frag: dict) -> None:
        patch: dict[str, Any] = {}
        if "routing_trace" in frag:
            patch["routing_trace"] = frag["routing_trace"]
        if "specialist_status" in frag:
            patch["specialist_status"] = frag["specialist_status"]
        if not patch:
            return
        try:
            db.update_job(job_id, **patch)
        except Exception:  # noqa: BLE001 - a failed progress write must not kill the run
            log.exception("progress write failed for job %s", job_id)

    return write


async def run_job(job_id: str, query: str) -> None:
    try:
        db.update_job(job_id, status="running")
        result = await planner.plan(query, on_progress=_progress_writer(job_id))
    except BaseException as exc:  # noqa: BLE001 - planner has its own guards; this is the last line
        log.exception("job %s crashed", job_id)
        db.update_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}")
        return

    # planner.plan returns {"query", "error"} (no "routing" key) only on a total
    # failure - bad query, or the graph itself blew up. A run where every
    # specialist 429'd still comes back as a real (degraded) report.
    if isinstance(result, dict) and "error" in result and "routing" not in result:
        db.update_job(job_id, status="error", error=str(result["error"]), report=result)
    else:
        db.update_job(
            job_id,
            status="done",
            report=result,
            specialist_status=(result or {}).get("specialist_status"),
        )
