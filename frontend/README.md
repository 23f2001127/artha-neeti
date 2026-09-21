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
  graph (route → gather → synthesize → compare), a feature grid naming the
  real differentiators (selective routing, conflict surfacing, filings
  grounding, live transparency), and `ExampleGallery` — two real completed
  reports (a full single-company view with a genuine cross-specialist
  conflict, and a portfolio analysis) a visitor can open without typing
  anything. Curated by hand (`FEATURED` in `ExampleGallery.jsx` — two
  `job_id`s + a tagline written for presentation), not a database "featured"
  flag — deliberately the simplest thing that works for two entries; each
  card fetches its real job via the same public `GET /research/{job_id}`
  everything else uses, with a skeleton while loading and quiet
  self-removal if a fetch ever fails. "View full report" reuses the exact
  `?job=` deep-link mechanism a shared link already uses — `App.jsx`'s
  `onViewJob` is the same `setJobId` transition `onEscalate` uses elsewhere.
  Everything on this page is a true claim about what the system does, not
  marketing filler.
- **Query** (`components/query/`) — the input, example-query chips, and a
  coverage strip from `GET /companies` distinguishing full coverage (all three
  specialists) from partial (market data + news only). A best-effort client-side
  check (`lib/coverage.js`) flags, without blocking, when the typed query doesn't
  seem to name a fully-covered company. `UploadFilingPanel` closes that gap
  directly from the coverage strip: upload the annual-report PDF yourself
  (`POST /filings/upload`), or let the system try to find and verify one
  automatically (`POST /filings/fetch`) — a mode toggle switches between the
  two, with live progress polled from `GET /filings/jobs/{job_id}` and an
  automatic coverage-list refresh once ingestion finishes.
- **Progress** (`components/progress/`) — polls every 2.5 s and renders the
  Planner's actual intermediate state, including a real ETA: `estimated_duration_seconds`
  is a historical average from past completed runs of the same shape (computed
  server-side the moment routing lands, see `app/README.md`), counted down
  client-side against elapsed time measured from the job's own `created_at`
  (not page-load time, so a refreshed or shared job link still shows the right
  elapsed/remaining). With no history yet, it says so plainly instead of
  guessing. `AgentGraph` (`components/common/`) is the centerpiece for a
  single-company run: the same Planner→specialists diagram as the landing
  page, but wired to real `specialist_status` — nodes animate from idle to
  running (pulsing ring) to done/error/skipped as the run actually progresses.
  Below it, `RoutingPanel` (selected vs. skipped specialists, with reasons —
  the routing transparency is the point, not an afterthought) and
  `SpecialistGrid` (a company × specialist matrix) cover the multi-company case
  the diagram doesn't try to. Each `SpecialistGrid` cell doesn't just flip
  `pending → ok/error` anymore — while a specialist is running, `StatusBadge`
  shows the actual live stage text the backend pushes per tool call
  ("calling get_quote...", "thinking...", "writing summary..."), so a 1-2
  minute specialist call reads as visible progress instead of a static spinner.
- **Report** (`components/report/`) — executive summary, per-specialist
  sections, `ConflictsPanel` (cross-specialist tensions, reconciled, given equal
  visual weight to the summary rather than buried), `SourcesPanel` (a
  references-style list from `sources_by_claim`), `CaveatsPanel` (collapsed by
  default so it's present but doesn't compete with the findings), for
  multi-company queries either `ComparisonView` (verdict + a dimension table,
  when the query asked "which is better") or `PortfolioView` (when it framed
  the companies as holdings — `report.portfolio` vs `report.comparison` are
  mutually exclusive, and each component no-ops on the field it doesn't get):
  a weight-allocation bar and a sector-allocation bar (both fixed-order
  categorical color, direct-labeled — validated with the `dataviz` skill's
  palette checker against both themes, see `index.css`'s `--chart-cat-*`
  tokens), three weighted-metric stat tiles (P/E, ROE, dividend yield —
  computed server-side in plain arithmetic, never LLM-estimated), the
  diversification narrative, and `concentration_risks` in the same warmer
  tension-first treatment `ConflictsPanel` uses for cross-specialist
  conflicts. Below all of that, `FollowUpPanel` — a small chat under the
  report for asking a follow-up without re-running anything: `POST .../followups` answers synchronously
  (no polling, it's one fast LLM call) and renders as a normal Q&A bubble
  pair. When the report doesn't cover what was asked, the turn instead shows
  why (`missing_reason`) and a "Run full research on this" button
  (`POST .../followups/escalate`) that hands the pre-written
  `standalone_query` to a real Planner run — `App.jsx`'s `onEscalate` just
  calls `setJobId(newJobId)`, the exact same transition `handleSubmit` already
  does after `POST /research`, so the whole progress → report flow works
  unchanged for it. "Download PDF" (next to "Copy link") hits
  `GET /research/{job_id}/report.pdf` and saves a real generated document —
  see `app/README.md` for how that's rendered server-side.

## Brand assets (favicon, social-share preview)

`public/favicon.svg` is the source of truth for the mark (also inlined in
`Header.jsx`). Everything else derives from it and from
`scripts/og-image.svg` via `scripts/generate-brand-assets.mjs` (`sharp`, a
devDependency — pure rasterization, no build-time cost since it's not part
of `npm run build`):

```bash
node scripts/generate-brand-assets.mjs
```

Regenerates `public/og-image.png` (1200×630, the social-share card —
`index.html`'s `og:image`/`twitter:image`, referenced as a **relative**
path so it resolves correctly at whatever domain this ends up deployed at)
and the favicon PNG fallbacks (`favicon-16.png`, `favicon-32.png`,
`apple-touch-icon.png`, `icon-512.png` — the SVG favicon covers modern
browsers on its own; these are for bookmarks, mobile "add to home screen",
and `site.webmanifest`). Re-run it whenever `favicon.svg` or
`scripts/og-image.svg` changes — nothing else needs to.

## Routing renders off the structured decision, not parsed log lines

`GET /research/{job_id}` exposes the Planner's structured `routing` object
live — the moment the route node finishes, not just once the job is `done` —
with a per-company breakdown (`companies_identified[].specialists[]`: which
specialists were selected/skipped for THAT company, and why). `RoutingPanel`
renders directly off it. `routing_trace` (the same decision as flat log lines)
is kept only for an optional "show full trace" toggle.

This used to be a client-side workaround: the poll response only carried raw
`routing_trace` lines while running, and `lib/parseRoutingTrace.js`
reconstructed the structure by regex-parsing them. That gap was closed on the
backend (`agents/planner.py` now builds the per-company breakdown structurally
instead of only narrating it into trace strings; `app/jobs.py` forwards
`routing` alongside `routing_trace`) and the parser was deleted — nothing
reconstructs structure from log lines anymore.

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

A global `:focus-visible` ring (`index.css`, brand-colored, themes correctly
in both modes) makes Tab-navigation visible — it only fires for keyboard
focus, not a mouse click, so nothing changes for a mouse user.

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
