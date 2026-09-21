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
| `GET /research/{job_id}` | The poll endpoint. `status` (`queued`/`running`/`done`/`error`), `routing` (the structured routing decision, present once the route node finishes — seconds in) + `routing_trace` (the same decision as flat log lines, for an optional "full trace" view), `specialist_status` (`{ticker: {specialist: "pending"\|"<live stage text>"\|"ok"\|"error:…"}}`, updated per tool call — not just per specialist), `estimated_duration_seconds`/`estimated_duration_samples` (a real historical-average ETA computed the moment routing lands — see below; `null` until then or if there's no history yet), `report` (the final Planner output, once done), `error`. |
| `GET /research/{job_id}/report` | Just the finished report. `409` while still `queued`/`running`. |
| `POST /research/{job_id}/followups` `{query}` | A cheap, **synchronous** follow-up on a finished report — one LLM call, answered within the request (no job/poll needed). Returns `{sufficient_data, answer?, caveat?, missing_reason?, standalone_query?}`. See "Follow-up conversations" below. |
| `GET /research/{job_id}/followups` | Past follow-up turns for this job's conversation, chronological: `{conversation_id, turns: [...]}`. |
| `POST /research/{job_id}/followups/escalate` `{standalone_query}` | When a follow-up needs fresh data: starts a real Planner run continuing the conversation (`conversation_id` inherited, `parent_job_id` set). Same dispatch as `POST /research` — returns `{job_id, status}`, poll it the same way. |
| `GET /companies` | `full_coverage` — every company with an ingested filing, seeded or since uploaded (`agents.filings_agent.ingested_tickers()`, DB-backed — not a static list), answerable by all three specialists — vs `partial_coverage` — any NSE ticker that resolves on yfinance gets market data + news; filings is skipped with a reason. |
| `POST /filings/upload` (multipart: `file`, `ticker`, `company`?, `fiscal_year`?) | Ingests an ad-hoc annual-report PDF for a company outside the seeded 10, so it's immediately in `full_coverage` and routable by the Planner. Same job pattern as `/research` — returns `{job_id}` at once; the pipeline (chunk → embed → store) is the exact one `mcp_servers/filings_rag_mcp/ingest.py`'s CLI uses, just pointed at one ad-hoc file instead of `data/filings/`. |
| `POST /filings/fetch` `{ticker, company?, fiscal_year?}` | Best-effort alternative to upload — no file needed. Searches the web for the annual report, downloads and verifies it actually names the company, then ingests it the same way. See `mcp_servers/filings_rag_mcp/fetch.py`'s docstring for exactly how and why it can (honestly) fail to find one. |
| `GET /filings/jobs/{job_id}` | Shared poll endpoint for both of the above: `status`, `source` (`upload`/`fetch`), `source_url` (set for a fetch), `detail` (a short current-phase string, e.g. `"searching the web for a PDF..."`), `chunks_done`/`chunks_total` (live), `chunks` (final count), `error`. |
| `GET /status` | Live shared LLM-quota usage per provider bucket (Groq, Gemini generate, Gemini embed) — `shared/llm_rate_limiter.py`'s `rl.snapshot()`, exposed read-only. Explains a slow run instead of leaving it a mystery. |
| `GET /` · `GET /docs` | index / OpenAPI UI |

## How live progress works

The Planner graph's nodes push state fragments through a `ContextVar`-based
`_emit()` (`planner.py`). `plan()` takes an optional `on_progress` callback;
`app/jobs.py` supplies one that writes straight to the job row. Three things
land this way, all live rather than only-once-`done`:

- **`routing` / `routing_trace`** — pushed the instant the route node finishes.
  `routing` is the structured decision (per-company specialist selections with
  reasons, `agents/README.md` has the full shape); `routing_trace` is the same
  information as flat log lines, kept only for an optional "full trace" view.
  The frontend renders directly off `routing` — nothing parses trace lines
  back into structure.
- **`specialist_status`** — used to flip once per specialist, `pending → ok/
  error`. Now flips on *every tool call* inside each specialist's ReAct loop
  (`agents/_base.py`'s `on_stage` callback → `_StageCallback`, threaded through
  `run_agent` → each specialist's `run()` → the Planner's gather node): a cell
  reads `"calling get_quote..."`, `"thinking..."`, `"writing summary..."` as
  the run actually progresses, not one static "running" for a minute or more.
- **`estimated_duration_seconds` / `estimated_duration_samples`** — computed
  once, the same moment routing lands, via `db.estimate_duration_seconds
  (mode)`: the average wall-clock duration of past **completed** jobs with the
  same routing mode (single/multi/none) — a real number from this project's
  own run history, not a hardcoded guess. Falls back to the all-modes average
  with too few same-mode samples, and to `null` (no estimate, stated honestly)
  with no history at all. The frontend counts down from it using its own
  elapsed-time clock rather than repolling the server for "now".

`asyncio.create_task`, not FastAPI `BackgroundTasks`: the run is a long-lived job
whose authoritative state is the Postgres row, not something bound to a response.
The in-memory task handle is kept only so it isn't GC'd and so a crash is logged;
`run_job` writes `status='error'` on any failure, so the poll endpoint always
reflects reality.

## Follow-up conversations (`app/followups.py`)

Every question used to be an isolated Planner run, even a trivial "what was
its ROE again?" — full 1-20+ minute cost, every time. Now a finished job can
be followed up on two ways, both reusing existing infrastructure rather than
introducing a parallel "conversation" system:

- **Cheap path (the common case)**: `POST /research/{job_id}/followups`
  answers synchronously from the report's *already-synthesized* content
  (`agents/followup_agent.py`, modeled on `synthesis_agent.py` — one
  structured-output call, no MCP, no ReAct loop). A few seconds, one Groq
  call, no job/poll needed at all.
- **Escalation (only when the cheap path can't)**: the same LLM call that
  decides "can I answer this" also produces a `standalone_query` when it
  can't — a fully self-contained rewrite with references to earlier turns
  resolved ("its" → the actual company). `POST
  /research/{job_id}/followups/escalate` hands that straight to a brand-new
  Planner run via the *exact same* `db.create_job` → `asyncio.create_task
  (jobs.run_job(...))` dispatch `POST /research` uses — nothing new to
  maintain, no partial-re-run logic. This only happens when the user
  explicitly confirms it (a button click after seeing why the report fell
  short), never silently — a full run is real cost, not something to spend
  without asking.

**Conversation state piggybacks on `research_jobs`** rather than a new
`conversations` table: a fresh top-level query is its own conversation root
(`conversation_id = job_id`); an escalated follow-up inherits the original
`conversation_id` and sets `parent_job_id` to the job it continued from. Only
the cheap chat-style turns get their own table (`followup_turns`) since they
don't fit the job/poll model at all — they're answered within one request.

**Scoped out of v1, on purpose**: escalation always re-runs the *whole*
Planner graph rather than intelligently reusing specialists that are still
valid from the prior run. Deciding what's "still valid" (is last run's news
still fresh? did the filing change?) is real complexity that didn't seem worth
taking on for the first version — a full re-run is simple, correct, and the
cost is opt-in. Worth revisiting if follow-ups turn out to escalate often.

## Persistence — `research_jobs`, `filing_upload_jobs`, `followup_turns`

`app/db.py`, same Supabase Postgres as `filings-rag-mcp`, same `connect()`
pattern (fresh connection per call). `research_jobs`: `job_id uuid`, `query`,
`status`, `routing_trace jsonb`, `routing jsonb`, `specialist_status jsonb`,
`estimated_duration_seconds real`, `estimated_duration_samples int`,
`report jsonb`, `error`, `conversation_id uuid`, `parent_job_id uuid` (FK to
`research_jobs`, null unless this row is an escalated follow-up), `created_at`,
`updated_at`. `filing_upload_jobs` (same shape, shared by `/filings/upload`
and `/filings/fetch`): `job_id`, `ticker`, `company`, `fiscal_year`,
`filename`, `source` (`upload`/`fetch`), `source_url`, `detail`, `status`,
`chunks_done`, `chunks_total`, `chunks`, `error`, timestamps. `followup_turns`:
`id bigserial`, `conversation_id`, `job_id` (which report this was asked
against), `query`, `answer`, `sufficient_data boolean`, `caveat`,
`missing_reason`, `standalone_query`, `created_at`.

All schemas are created on startup (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
for every column added after a table's first version, so an already-existing
table migrates in place). `research_jobs`' schema init also runs a one-time
`UPDATE ... SET conversation_id = job_id WHERE conversation_id IS NULL`, so
every job created before this feature is still a valid conversation root.

## The filings upload + auto-fetch features (`app/filings.py`)

Both ways of adding a company outside the seeded 10 share one tail
(`_ingest_and_finish`) that reuses `mcp_servers/filings_rag_mcp/ingest.py`'s
pipeline as-is (`chunking.iter_pdf_chunks` → `embeddings.embed_documents` →
`db.insert_chunk_batch`/`record_ingestion`) — that module's `ingest_file()`
takes explicit `ticker`/`company`/`fiscal_year` instead of deriving them from a
filename convention, since neither an upload's nor a fetch's filename follows
one. The seeded corpus's CLI path is unchanged (still derives from
`TICKER_AR_YYYY-YY.pdf`). They differ only in how the PDF bytes are obtained:

- **Upload**: the multipart file, validated (`filings.validate_upload`: PDF
  only, ≤40MB, a plausible ticker shape) and saved as
  `data/uploads/<TICKER>_UPLOAD_<job_id>.pdf`.
- **Fetch**: `mcp_servers/filings_rag_mcp/fetch.py` searches the web, ranks
  candidates, downloads, and verifies the top few before accepting one (see
  that module's README section for the full "why" — ranking by title/URL
  keywords alone isn't enough to avoid a same-family false positive). The
  winning candidate is saved as `data/uploads/<TICKER>_FETCH_<job_id>.pdf` and
  its URL recorded on the job row (`source_url`) for transparency.

Both are gitignored; the job id in the filename guarantees uniqueness, since
`ingest_file`'s DB identity key is the filename. The blocking pipeline (and,
for fetch, the blocking search/download) runs via `asyncio.to_thread` so it
doesn't stall the event loop.

Once ingestion finishes, `agents.filings_agent.invalidate_ticker_cache()` is
called so the new company is routable on the very next query — the Planner's
`ingested_tickers()` check is DB-backed with only a 30s TTL cache, but a demo
shouldn't have to wait that out. `GET /companies`' `full_coverage` list picks
it up the same way.

**Known gaps**:
- An interrupted ingestion (daily embedding quota hit mid-file) does not
  resume — retrying restarts it from scratch, same as the seeded corpus's CLI
  ingestion (see that module's docstring). Fine for a single ad-hoc file;
  would need incremental resume for something larger.
- Auto-fetch is genuinely best-effort. It can honestly fail to find/verify a
  PDF for an obscure or small-cap company, or occasionally accept a
  wrong-but-verified document if a subsidiary shares both the parent's brand
  name *and* corporate suffix (rare — the ITC/ITC-Hotels case that motivated
  the verification step has a different suffix pattern and is caught).
  Upload remains the reliable path when fetch comes up empty.

## Known limitations

- A server restart orphans in-flight jobs (their row stays `running`). A
  production build would use a real task queue, or sweep stale `running` rows on
  startup.
- No job-concurrency cap. The shared rate limiter serialises the actual LLM
  calls, but N simultaneous jobs still spawn N sets of MCP subprocesses.
- CORS is wide-open for `localhost` — **tighten before any public deploy** (see
  the comment in `main.py`).
- The progress callback does a blocking single-row `UPDATE` from inside the
  Planner's event loop. Fine at this scale — per-tool-call stage updates raised
  the write count from roughly one-per-specialist to one-per-tool-call/LLM-turn
  (still maybe a dozen-odd writes for a single-company run), each a single-row
  `UPDATE` by primary key; revisit if it ever matters.
- The ETA is a single point estimate, sliced only by routing mode (single/
  multi/none) - not by company count or which specialists ran - because with
  this project's small run history, slicing finer would leave most buckets
  with too few samples to trust. It also doesn't refine mid-run as specialists
  finish; it's set once, when routing lands, and counted down from client-side.
  Both are honest simplifications, not bugs - the number gets more meaningful
  as real usage accumulates.

## Running

```bash
uvicorn app.main:app --reload      # needs GROQ + GEMINI + TAVILY keys + DATABASE_URL
python app/test_api.py             # in-process (httpx ASGI), submits a cheap job, asserts the progression
```
