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
| `GET /companies` | `full_coverage` — every company with an ingested filing, seeded or since uploaded (`agents.filings_agent.ingested_tickers()`, DB-backed — not a static list), answerable by all three specialists — vs `partial_coverage` — any NSE ticker that resolves on yfinance gets market data + news; filings is skipped with a reason. |
| `POST /filings/upload` (multipart: `file`, `ticker`, `company`?, `fiscal_year`?) | Ingests an ad-hoc annual-report PDF for a company outside the seeded 10, so it's immediately in `full_coverage` and routable by the Planner. Same job pattern as `/research` — returns `{job_id}` at once; the pipeline (chunk → embed → store) is the exact one `mcp_servers/filings_rag_mcp/ingest.py`'s CLI uses, just pointed at one ad-hoc file instead of `data/filings/`. |
| `GET /filings/upload/{job_id}` | Poll endpoint: `status`, `chunks_done`/`chunks_total` (live), `chunks` (final count), `error`. |
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

## Persistence — `research_jobs`, `filing_upload_jobs`

`app/db.py`, same Supabase Postgres as `filings-rag-mcp`, same `connect()`
pattern (fresh connection per call). `research_jobs`: `job_id uuid`, `query`,
`status`, `routing_trace jsonb`, `specialist_status jsonb`, `report jsonb`,
`error`, `created_at`, `updated_at`. `filing_upload_jobs` (same shape, for
`/filings/upload`): `job_id`, `ticker`, `company`, `fiscal_year`, `filename`,
`status`, `chunks_done`, `chunks_total`, `chunks`, `error`, timestamps. Both
schemas are created on startup.

## The filings upload feature (`app/filings.py`)

Reuses `mcp_servers/filings_rag_mcp/ingest.py`'s pipeline as-is
(`chunking.iter_pdf_chunks` → `embeddings.embed_documents` →
`db.insert_chunk_batch`/`record_ingestion`) — that module's `ingest_file()` now
takes explicit `ticker`/`company`/`fiscal_year` instead of deriving them from a
filename convention, since an upload's filename is arbitrary. The seeded
corpus's CLI path is unchanged (still derives from `TICKER_AR_YYYY-YY.pdf`).

The upload is saved to `data/uploads/<TICKER>_UPLOAD_<job_id>.pdf` (gitignored)
— the job id in the name guarantees uniqueness, since `ingest_file`'s DB
identity key is the filename. Validation (`filings.validate_upload`): PDF only,
≤40MB, a plausible ticker shape. The blocking pipeline runs via
`asyncio.to_thread` so it doesn't stall the event loop.

Once ingestion finishes, `agents.filings_agent.invalidate_ticker_cache()` is
called so the new company is routable on the very next query — the Planner's
`ingested_tickers()` check is DB-backed with only a 30s TTL cache, but a demo
shouldn't have to wait that out. `GET /companies`' `full_coverage` list picks
it up the same way.

**Known gap**: an interrupted upload (daily embedding quota hit mid-file) does
not resume — re-uploading the same file restarts it from scratch, same as the
seeded corpus's CLI ingestion (see that module's docstring). Fine for a single
ad-hoc file; would need incremental resume for something larger.

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
