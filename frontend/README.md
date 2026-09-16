# frontend/

React + Vite UI for ArthaNeeti. A landing page pitches the system, then three
app views over the FastAPI backend (`POST /research`, `GET /research/{job_id}`,
`GET /companies`): ask a question, watch the Planner route and run it live, read
the cited report.

No routing library, no state manager — a query takes 1–20+ minutes and produces
one job, so `App.jsx` is a small state machine (`landing → query → progress →
report`) driven by `useJobPolling`, with the job id mirrored into `?job=` so a
run is shareable/refreshable (a direct job link skips straight past the landing
page).

## Stack

React 19 + Vite, Tailwind v4 (via `@tailwindcss/vite`, no PostCSS config needed),
Framer Motion for the animation throughout (entrance choreography, the live
agent-graph, animated status transitions, scroll reveals on the landing page).
No UI kit — the design is custom (see below). `fetch` directly (`src/lib/api.js`);
no axios, no query-caching library — polling a single job doesn't need one.

## Views

- **Landing** (`components/landing/`) — the pitch: an animated hero with a
  live-looking agent-pipeline diagram (`HeroDiagram`, self-cycling), count-up
  stats pulled from the real corpus (10 companies, 3,980 cited excerpts, 3
  specialists, 11 tools), a 4-step "how it works" tied to the actual Planner
  graph (route → gather → synthesize → compare), and a feature grid naming the
  real differentiators (selective routing, conflict surfacing, filings
  grounding, live transparency) — everything on this page is a true claim about
  what the system does, not marketing filler.
- **Query** (`components/query/`) — the input, example-query chips, and a
  coverage strip from `GET /companies` distinguishing full coverage (all three
  specialists) from partial (market data + news only). A best-effort client-side
  check (`lib/coverage.js`) flags, without blocking, when the typed query doesn't
  seem to name a fully-covered company.
- **Progress** (`components/progress/`) — polls every 2.5 s and renders the
  Planner's actual intermediate state. `AgentGraph` (`components/common/`) is
  the centerpiece for a single-company run: the same Planner→specialists
  diagram as the landing page, but wired to real `specialist_status` — nodes
  animate from idle to running (pulsing ring) to done/error/skipped as the run
  actually progresses. Below it, `RoutingPanel` (selected vs. skipped
  specialists, with reasons — the routing transparency is the point, not an
  afterthought) and `SpecialistGrid` (a company × specialist matrix, each cell
  spring-animating `pending → ok/error`) cover the multi-company case the
  diagram doesn't try to.
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

A research terminal, not a generic SaaS dashboard: near-black by default with a
vivid emerald for interactive elements and gold reserved for the mark and rare
emphasis — no gradient blobs, no glassmorphism. **Dark is the default theme**;
light is a full, equally-designed second palette (deep pine on warm paper), not
an afterthought — `ThemeToggle` switches instantly with no flash on load (the
choice is applied before first paint via an inline script in `index.html`, then
persisted to `localStorage`).

Every color is a runtime CSS custom property (`src/index.css`, `:root` for dark,
`:root[data-theme="light"]` for the overrides), deliberately kept *outside*
Tailwind's `@theme` block — `@theme` tokens are static/build-time, and these need
to change live when the toggle fires. Components reference them through
arbitrary-value utilities (`bg-[var(--color-brand)]`), so a component never
special-cases the theme; flipping the one attribute on `<html>` re-themes
everything. Status colors mean one specific thing each and nothing else: amber =
in progress, green = done, red = failed, slate = deliberately skipped (routing
decisions are not failures and shouldn't look like them). Conflicts get their
own warmer, higher-contrast treatment than caveats — a flagged tension is more
load-bearing than a footnote. Inter for UI text, IBM Plex Mono for
tickers/figures/job ids (tabular numerals) so financial data lines up.

Motion is Framer Motion throughout, not incidental CSS transitions: staggered
entrance choreography on the landing page and each app view, scroll-triggered
reveals and count-up stats, spring-eased status badges, and the live agent-graph
(pulsing ring on the active node, animated dashed "data flow" along its active
edges). All of it is tied to real state — the graph in the progress view is not
a decorative loop, it reflects the actual `specialist_status` coming back from
the poll.

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
