"""Research API mechanics, in-process via httpx's ASGI transport.

Submits a real single-specialist job and polls it to completion, asserting on
job lifecycle (routing visible before completion, incremental specialist
status, report availability), not research quality.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import httpx
import pytest

from app import db
from app.main import app

pytestmark = pytest.mark.live

CHEAP_QUERY = "what's Reliance's current stock price"
POLL_EVERY_S = 3.0
POLL_TIMEOUT_S = float(os.environ.get("API_TEST_TIMEOUT_S", "900"))


def _cells(specialist_status: dict | None) -> dict:
    return {f"{t}/{sp}": st for t, per in (specialist_status or {}).items() for sp, st in per.items()}


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_companies_distinguishes_coverage() -> None:
    async def run() -> httpx.Response:
        async with await _client() as c:
            return await c.get("/companies")

    r = asyncio.run(run())
    assert r.status_code == 200
    body = r.json()
    full = body.get("full_coverage", {})
    assert full.get("count", 0) >= 10
    assert set(full.get("specialists", [])) == {"market_data", "news_sentiment", "filings"}
    assert set(body.get("partial_coverage", {}).get("specialists", [])) == {"market_data", "news_sentiment"}
    assert any(x["ticker"] == "RELIANCE" for x in full.get("companies", []))


def test_job_error_paths() -> None:
    async def run() -> tuple[int, int]:
        async with await _client() as c:
            unknown = await c.get(f"/research/{uuid.uuid4()}")
            malformed = await c.get("/research/not-a-uuid")
            return unknown.status_code, malformed.status_code

    assert asyncio.run(run()) == (404, 422)


def test_job_lifecycle() -> None:
    asyncio.run(_run_job_lifecycle())


async def _run_job_lifecycle() -> None:
    db.init_schema()
    async with await _client() as c:
        started = time.monotonic()
        r = await c.post("/research", json={"query": CHEAP_QUERY})
        submit_ms = (time.monotonic() - started) * 1000
        assert r.status_code == 202
        job_id = r.json().get("job_id")
        assert job_id
        assert submit_ms < 3000, f"submit blocked for {submit_ms:.0f} ms"

        assert (await c.get(f"/research/{job_id}/report")).status_code == 409

        routing_seen_at = done_at = None
        snapshots: list[dict] = []
        poll_start = time.monotonic()
        while True:
            await asyncio.sleep(POLL_EVERY_S)
            elapsed = time.monotonic() - poll_start
            state = (await c.get(f"/research/{job_id}")).json()
            cells = _cells(state.get("specialist_status"))
            if state.get("routing_trace") and routing_seen_at is None:
                routing_seen_at = elapsed
            if cells and (not snapshots or snapshots[-1] != cells):
                snapshots.append(cells)
            if state["status"] in ("done", "error"):
                done_at = elapsed
                final = state
                break
            assert elapsed <= POLL_TIMEOUT_S, f"job still {state['status']} after {elapsed:.0f}s"

        assert routing_seen_at is not None and routing_seen_at < done_at, "routing must be visible before completion"
        assert isinstance(final.get("routing_trace"), list) and len(final["routing_trace"]) >= 2

        assert snapshots, "specialist_status was never observed mid-run"
        first, last = snapshots[0], snapshots[-1]
        assert any(v == "pending" for v in first.values()), first
        assert first != last and not any(v == "pending" for v in last.values()), (first, last)
        assert {k.split("/")[1] for k in last} == {"market_data"}

        assert final["status"] == "done", final.get("error")
        report = final.get("report")
        assert isinstance(report, dict) and report
        assert "routing" in report and "reports" in report

        r = await c.get(f"/research/{job_id}/report")
        assert r.status_code == 200
        assert r.json() == report
