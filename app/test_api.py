"""Standalone test for the research API.

Runs the FastAPI app in-process via httpx's ASGI transport (no separate uvicorn),
submits a real job, and polls it to done - asserting the *mechanics*, not the
research quality:

  - GET /companies distinguishes full vs partial coverage
  - POST /research returns a job_id without blocking
  - routing_trace appears in the poll response BEFORE status == 'done'
  - specialist_status advances incrementally (pending -> ok/error per specialist),
    not empty -> fully-complete in one jump
  - the final report lands, and GET /research/{id}/report serves it
  - 404 for an unknown job, 409 for a report that isn't ready

Uses a deliberately cheap single-specialist query ("Reliance's current stock
price" -> market_data only) so it proves the plumbing on ~6-7 Groq calls.

    python app/test_api.py

Needs GROQ + GEMINI + TAVILY keys + DATABASE_URL + network.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

_failures: list[str] = []
CHEAP_QUERY = "what's Reliance's current stock price"
POLL_EVERY_S = 3.0
POLL_TIMEOUT_S = float(os.environ.get("API_TEST_TIMEOUT_S", "900"))


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def section(t: str) -> None:
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def _status_cells(specialist_status: dict | None) -> dict:
    """{'RELIANCE/market_data': 'pending', ...} flattened, for easy comparison."""
    out = {}
    for ticker, per in (specialist_status or {}).items():
        for sp, st in per.items():
            out[f"{ticker}/{sp}"] = st
    return out


async def main() -> int:
    db.init_schema()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

        # -- /companies --------------------------------------------------------
        section("GET /companies")
        r = await c.get("/companies")
        check("companies 200", r.status_code == 200, str(r.status_code))
        body = r.json()
        full = body.get("full_coverage", {})
        print(f"  full_coverage: {full.get('count')} companies, specialists {full.get('specialists')}")
        print(f"  partial_coverage: {body.get('partial_coverage', {}).get('specialists')}")
        check("full_coverage lists the ingested corpus (10)", full.get("count") == 10, str(full.get("count")))
        check("full_coverage = all 3 specialists",
              set(full.get("specialists", [])) == {"market_data", "news_sentiment", "filings"})
        check("partial_coverage = market_data + news only",
              set(body.get("partial_coverage", {}).get("specialists", [])) == {"market_data", "news_sentiment"})
        check("RELIANCE is in full coverage",
              any(x["ticker"] == "RELIANCE" for x in full.get("companies", [])))

        # -- 404 / 409 edges --------------------------------------------------
        section("error paths")
        r = await c.get(f"/research/{uuid.uuid4()}")
        check("unknown job -> 404", r.status_code == 404, str(r.status_code))
        r = await c.get("/research/not-a-uuid")
        check("bad job id -> 422", r.status_code == 422, str(r.status_code))

        # -- submit ----------------------------------------------------------
        section(f"POST /research  ::  {CHEAP_QUERY!r}")
        t0 = time.monotonic()
        r = await c.post("/research", json={"query": CHEAP_QUERY})
        submit_ms = (time.monotonic() - t0) * 1000
        check("submit -> 202", r.status_code == 202, str(r.status_code))
        job_id = r.json().get("job_id")
        check("submit returned a job_id", bool(job_id), str(r.json()))
        check("submit did not block on the run (< 3 s)", submit_ms < 3000, f"{submit_ms:.0f} ms")
        print(f"  job_id = {job_id}")

        # report-not-ready right after submit
        r = await c.get(f"/research/{job_id}/report")
        check("report before done -> 409", r.status_code == 409, str(r.status_code))

        # -- poll ----------------------------------------------------------
        section("poll GET /research/{job_id} until done")
        routing_seen_at: float | None = None
        done_at: float | None = None
        status_snapshots: list[dict] = []
        last_print = ""
        start = time.monotonic()

        while True:
            await asyncio.sleep(POLL_EVERY_S)
            elapsed = time.monotonic() - start
            r = await c.get(f"/research/{job_id}")
            s = r.json()
            st = s["status"]
            cells = _status_cells(s.get("specialist_status"))

            line = f"    t+{elapsed:5.0f}s  status={st:8}  routing_trace={'yes' if s.get('routing_trace') else 'no ':3}  cells={cells or '{}'}"
            if line != last_print:
                print(line)
                last_print = line

            if s.get("routing_trace") and routing_seen_at is None:
                routing_seen_at = elapsed
            if cells and (not status_snapshots or status_snapshots[-1] != cells):
                status_snapshots.append(cells)

            if st in ("done", "error"):
                done_at = elapsed
                final = s
                break
            if elapsed > POLL_TIMEOUT_S:
                check("job finished within the timeout", False, f"still {st} after {elapsed:.0f}s")
                return 1

        # -- assertions on progression -------------------------------------
        section("progression assertions")
        check("job reached a terminal state", final["status"] in ("done", "error"), final["status"])
        check("routing_trace appeared BEFORE the job finished",
              routing_seen_at is not None and done_at is not None and routing_seen_at < done_at,
              f"routing at t+{routing_seen_at}s, done at t+{done_at}s")
        check("routing_trace is a non-trivial list",
              isinstance(final.get("routing_trace"), list) and len(final["routing_trace"]) >= 2,
              f"{len(final.get('routing_trace') or [])} lines")

        print("\n  specialist_status snapshots over the run:")
        for snap in status_snapshots:
            print(f"    {snap}")
        first, last = (status_snapshots[0] if status_snapshots else {}), (status_snapshots[-1] if status_snapshots else {})
        check("specialist_status was observed mid-run (not just at the end)",
              len(status_snapshots) >= 1)
        check("first snapshot shows 'pending' (client saw the shape before completion)",
              any(v == "pending" for v in first.values()),
              str(first))
        check("final snapshot has no 'pending' left",
              first != last and not any(v == "pending" for v in last.values()),
              f"{first}  ->  {last}")
        check("the query routed to market_data only (cheap-query sanity)",
              set(k.split("/")[1] for k in last) == {"market_data"},
              str(set(k.split("/")[1] for k in last)))

        # -- final report ------------------------------------------------
        section("final report")
        check("status is 'done' (market-data-only query should not fail)",
              final["status"] == "done", final.get("error") or final["status"])
        rep = final.get("report")
        check("report is present in the poll response", isinstance(rep, dict) and bool(rep))
        if isinstance(rep, dict):
            print(f"  companies : {[c.get('ticker') for c in rep.get('companies', [])]}")
            print(f"  graph_path: {rep.get('graph_path')}")
            for tk, tr in rep.get("reports", {}).items():
                print(f"  report[{tk}] exec summary: {str(tr.get('executive_summary'))[:200]}")
            check("report carries routing + reports", "routing" in rep and "reports" in rep)

        r = await c.get(f"/research/{job_id}/report")
        check("GET /research/{id}/report -> 200 once done", r.status_code == 200, str(r.status_code))
        check("/report matches the report in the poll response", r.json() == rep)

    section("SUMMARY")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"    - {f}")
        return 1
    print("\n  all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
