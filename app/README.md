# app/

FastAPI service in front of `agents.planner`. A research query runs the whole
Planner graph — 1 to 20+ minutes on free-tier LLM pacing — so this layer is
**job-based**: submit, get an id, poll.

It reimplements none of the Planner. `jobs.run_job` calls `planner.plan(query,
on_progress=...)` as-is; everything else is accept a request, run it as a
background job, and persist/expose its progress.

## Endpoints

| | |
|---|---|
| `POST /research` `{"query": str}` | Creates a `research_jobs` row (`status: queued`), fires the Planner as a **detached `asyncio` task**, returns `{job_id, status}` at once. Never blocks on the run. |
| `GET /research/{job_id}` | The poll endpoint. `status` (`queued`/`running`/`done`/`error`), `routing_trace` (present once the route node finishes — seconds in), `specialist_status` (`{ticker: {specialist: pending\|ok\|error:…}}`, updated per specialist), `report` (the final Planner output, once done), `error`. |
| `GET /research/{job_id}/report` | Just the finished report. `409` while still `queued`/`running`. |
| `GET /companies` | `full_coverage` — the 10 companies whose annual reports are ingested, answerable by all three specialists (from `filings_agent.INGESTED_TICKERS`) — vs `partial_coverage` — any NSE ticker that resolves on yfinance gets market data + news; filings is skipped with a reason. |
| `GET /` · `GET /docs` | index / OpenAPI UI |

## How live progress works

The Planner graph's nodes push state fragments through a `ContextVar`-based
`_emit()` (added to `planner.py` — a few call sites, no rewrite). `plan()` takes
an optional `on_progress` callback; `app/jobs.py` supplies one that writes
`routing_trace` and `specialist_status` straight to the job row. So a client
polling mid-run sees the routing rationale before the slow specialist phase, and
each `pending → ok/error` transition as it happens — not silence then a finished
report.

`asyncio.create_task`, not FastAPI `BackgroundTasks`: the run is a long-lived job
whose authoritative state is the Postgres row, not something bound to a response.
The in-memory task handle is kept only so it isn't GC'd and so a crash is logged;
`run_job` writes `status='error'` on any failure, so the poll endpoint always
reflects reality.

## Persistence — `research_jobs`

`app/db.py`, same Supabase Postgres as `filings-rag-mcp`, same `connect()`
pattern (fresh connection per call). One table: `job_id uuid`, `query`, `status`,
`routing_trace jsonb`, `specialist_status jsonb`, `report jsonb`, `error`,
`created_at`, `updated_at`. Schema is created on startup.

## Known limitations

- A server restart orphans in-flight jobs (their row stays `running`). A
  production build would use a real task queue, or sweep stale `running` rows on
  startup.
- No job-concurrency cap. The shared rate limiter serialises the actual LLM
  calls, but N simultaneous jobs still spawn N sets of MCP subprocesses.
- CORS is wide-open for `localhost` — **tighten before any public deploy** (see
  the comment in `main.py`).
- The progress callback does a blocking single-row `UPDATE` from inside the
  Planner's event loop. Fine at this scale (a handful of writes per run); revisit
  if it ever matters.

## Running

```bash
uvicorn app.main:app --reload      # needs GROQ + GEMINI + TAVILY keys + DATABASE_URL
python app/test_api.py             # in-process (httpx ASGI), submits a cheap job, asserts the progression
```
