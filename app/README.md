# app

The FastAPI service. Research runs take minutes, so the API is job-based: a
request creates a job and returns its id, the planner runs in the background,
and clients poll for progress and the result.

| Module | Role |
| --- | --- |
| `main.py` | Routes, CORS and request limits |
| `jobs.py` | Runs a planner job, streams progress to Postgres, builds chart data |
| `db.py` | Postgres tables and queries |
| `visuals.py` | Chart data per company and across companies, from market data |
| `report_pdf.py` | PDF export |
| `followups.py` | Follow-up questions on a finished report |
| `filings.py` | Upload and web-fetch jobs that index annual reports |

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /research` `{query}` | Queue a research job; returns `{job_id, status}` |
| `GET /research/{id}` | Status, routing, per-specialist progress, estimated duration, and the report once done |
| `GET /research/{id}/report` | The finished report (409 until it exists) |
| `GET /research/{id}/visuals` | Chart data for the report, built on first request for older reports |
| `GET /research/{id}/report.pdf` | The report as a PDF, charts included |
| `POST /research/{id}/followups` `{query}` | Answer a follow-up question from the report, synchronously |
| `GET /research/{id}/followups` | The conversation's follow-up turns |
| `POST /research/{id}/followups/escalate` `{standalone_query}` | Start a new research job that continues the conversation |
| `GET /companies` | Companies with an indexed annual report, and what other companies get |
| `POST /filings/upload` | Index an uploaded annual-report PDF (multipart: `file`, `ticker`, optional `company`, `fiscal_year`) |
| `POST /filings/fetch` `{ticker, company?, fiscal_year?}` | Find a company's annual report on the web and index it |
| `GET /filings/jobs/{id}` | Progress of an upload or fetch job |
| `GET /status` | Usage of each rate-limited LLM bucket |

Interactive documentation is served at `/docs`.

## Research jobs

- **Starting a job.** `POST /research` stores a `queued` row and starts
  `jobs.run_job` as an asyncio task. Job state lives in Postgres, not in the
  request.
- **Live progress.** The planner calls a progress callback that writes to the
  job row:
  - `routing` as soon as the plan is decided (the structured decision) and
    `routing_trace` (the same decision as text lines);
  - `specialist_status` as each specialist moves through its steps
    (`"calling get_ratios..."`, then `ok` or `error`);
  - `estimated_duration_seconds`, the average duration of past completed jobs
    of the same kind (single company, multi-company), with a sample count, or
    null without history.
- **Completion.** When the report is ready, chart data is built from market data
  (no LLM calls) and stored with it.
- **Restarts.** A running job refreshes `updated_at` every minute. A job that
  stops heartbeating for three minutes is marked as interrupted, both at
  startup and when it is polled, so clients never wait on a job that no longer
  exists.
- **Errors.** A failed run stores a user-facing message; the details go to the
  log.

## Follow-ups

`POST /research/{id}/followups` answers from the finished report in one LLM
call (`agents/followup_agent.py`) and returns:

```json
{"sufficient_data": true, "answer": "...", "caveat": "..."}
{"sufficient_data": false, "missing_reason": "...", "standalone_query": "..."}
```

When the report can't answer, the client can send `standalone_query` to
`.../followups/escalate` after the user confirms, which starts a full research
run. Escalated jobs share the original `conversation_id` and record
`parent_job_id`; follow-up turns are stored in `followup_turns`.

## Charts and PDF

`visuals.build(report)` fetches, per company:
- KPIs;
- a one-year price history and returns over 1, 3, 6 and 12 months;
- four fiscal years of revenue, profit and margins;
- the latest margin profile;
- the sentiment breakdown from the news specialist.

Multi-company reports add rebased relative performance and side-by-side
metrics. Companies are fetched in parallel, taking a few seconds per report.

`report_pdf.render_report_pdf(report)` builds an A4 document with reportlab:

- a branded first page with running headers and "Page X of Y" footers;
- a KPI grid and vector charts matching the dashboard;
- the analysis, conflicts, numbered findings with sources, limitations and a
  disclaimer.

Inter and Source Serif 4 are embedded from `assets/fonts` so the rupee sign and
typographic punctuation render correctly. Reader-facing text is normalized, so
internal identifiers and timestamps in model output appear as plain words and
dates.

## Annual-report jobs

Upload and fetch share one pipeline, `ingest_file` from filings-rag-mcp
(chunk, embed, store), run in a worker thread with progress on the job row:

- **Upload** accepts a PDF up to 40 MB, saved under `data/uploads/`.
- **Fetch** searches for a direct PDF link, ranks candidates, and checks
  that the document names the company before accepting it; the source URL is
  recorded on the job. When nothing qualifies, the job ends with a message
  suggesting an upload.

A new company can be routed for annual-report analysis as soon as its job
finishes. An interrupted indexing job restarts from the beginning when retried.

## Limits for public deployments

| Variable | Effect |
| --- | --- |
| `MAX_DAILY_JOBS` | New research jobs allowed per 24 hours across all visitors (0 disables). Global because it protects a shared LLM quota. |
| `IP_THROTTLE_PER_MINUTE` | Requests per client IP per minute on job-creating endpoints (default 6). In memory, per process. |
| `CORS_ALLOWED_ORIGINS` | Browser origins allowed besides localhost, comma-separated. |

Behind a proxy, run Uvicorn with `--proxy-headers` so client addresses come
from `X-Forwarded-For`; the Docker image does this.

## Data model

Tables are created or migrated in place on startup.

| Table | Contents |
| --- | --- |
| `research_jobs` | Query, status, routing, specialist status, duration estimate, report (jsonb), error, conversation and parent ids, timestamps |
| `followup_turns` | Question, answer, sufficiency, caveat, missing reason, standalone query |
| `filing_upload_jobs` | Ticker, company, fiscal year, source, source URL, phase, chunk progress, error |

## Running

```bash
uvicorn app.main:app --reload
```

Requires `GROQ_API_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY` and `DATABASE_URL`
(see `.env.example`). Offline tests for the request limits and the PDF are in
`tests/unit/`; `tests/integration/test_api.py` runs a real job through the API
with `--live`.
