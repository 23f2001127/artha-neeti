# frontend/

React + Vite UI for ArthaNeeti. Three views over the FastAPI backend
(`POST /research`, `GET /research/{job_id}`, `GET /companies`): ask a question,
watch the Planner route and run it live, read the cited report.

No routing library, no state manager — a query takes 1–20+ minutes and produces
one job, so `App.jsx` is a small state machine (`query → progress → report`)
driven by `useJobPolling`, with the job id mirrored into `?job=` so a run is
shareable/refreshable.

## Stack

React 19 + Vite, Tailwind v4 (via `@tailwindcss/vite`, no PostCSS config needed).
No UI kit — the design is custom (see below). `fetch` directly (`src/lib/api.js`);
no axios, no query-caching library — polling a single job doesn't need one.

## Views

- **Query** (`components/query/`) — the input, example-query chips, and a
  coverage strip from `GET /companies` distinguishing full coverage (all three
  specialists) from partial (market data + news only). A best-effort client-side
  check (`lib/coverage.js`) flags, without blocking, when the typed query doesn't
  seem to name a fully-covered company.
- **Progress** (`components/progress/`) — polls every 2.5 s and renders the
  Planner's actual intermediate state: `RoutingPanel` (which specialists were
  selected vs. skipped, and why — the routing transparency is the point, not an
  afterthought) and `SpecialistGrid` (a company × specialist matrix stepping
  `pending → ok/error` live).
- **Report** (`components/report/`) — executive summary, per-specialist
  sections, `ConflictsPanel` (cross-specialist tensions, reconciled, given equal
  visual weight to the summary rather than buried), `SourcesPanel` (a
  references-style list from `sources_by_claim`), `CaveatsPanel` (collapsed by
  default so it's present but doesn't compete with the findings), and for
  multi-company queries, `ComparisonView` (verdict + a dimension table).

## A gap in the live API, worked around client-side

`GET /research/{job_id}` only exposes the Planner's raw `routing_trace` log
lines while a job is running — the *structured* routing decision
(`specialists_selected` / `specialists_skipped` with reasons / `rationale`) only
appears inside `report.routing` once the job is `done` (see `app/jobs.py`'s
progress writer, which currently forwards `routing_trace` but drops the richer
`routing` fragment the Planner already emits). `lib/parseRoutingTrace.js`
reconstructs the same structure by parsing the trace lines' stable, documented
format from `agents/planner.py`, so the routing panel can show it live either
way. Anything that doesn't match a known line shape is preserved verbatim in the
trace instead of dropped — "Show full trace" always renders the untouched lines.

**This is a workaround, not the ideal fix.** Adding `routing` alongside
`routing_trace` to the job row and the poll response would be a small, additive
change to `app/` and let this component drop the parser entirely. Not made here
per the instruction not to touch the backend without asking.

## Design direction

A research tool, not a SaaS demo: warm paper background (`#F7F6F2`), one
restrained brand color (deep pine `#12332C`), a gold accent used only for the
mark and rare emphasis — no gradients, no glassmorphism. Status colors mean one
specific thing each and nothing else: amber = in progress, green = done, red =
failed, slate = deliberately skipped (routing decisions are not failures and
shouldn't look like them). Conflicts get their own warmer, higher-contrast
treatment than caveats, deliberately — a flagged tension is more load-bearing
than a footnote. Inter for UI text, IBM Plex Mono for tickers/figures/job ids
(tabular numerals) so financial data lines up.

## Running

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api/* to the FastAPI backend
```

Needs the backend running (`uvicorn app.main:app` from the repo root — see
`app/README.md`). `.env.example` documents `VITE_API_BASE` (dev proxy target)
and `VITE_API_BASE_DIRECT` (production build, no proxy).

```bash
npm run build       # production bundle to dist/
npm run preview     # serve that bundle locally
```
