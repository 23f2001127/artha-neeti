# frontend

The ArthaNeeti web app: React 19, Vite, Tailwind CSS 4 and Recharts.

## Screens

The app is a small state machine in `src/app/App.jsx` rather than a router. The
current job id is mirrored to `?job=` so any report or run in progress can be
shared and reloaded.

| Screen | Folder | Contents |
| --- | --- | --- |
| Landing | `features/landing` | Hero with the animated pipeline, live stats, how it works, capabilities, example reports |
| Research | `features/query` | Question input, examples, coverage list, **Add a company** (upload or find an annual report) |
| Progress | `features/progress` | Research plan, pipeline diagram with flowing activity, per-specialist status, elapsed and estimated time |
| Report | `features/report` | Dashboard per company (KPIs, charts, analysis, conflicts, sources, caveats), comparison or portfolio overview, share and PDF download |
| Follow-up | `features/followup` | Chat drawer on the report for follow-up questions |

## Structure

```
src/
  app/            App shell, theme provider
  features/       One folder per screen (above)
  components/
    layout/       Header, footer, logo, theme toggle
    agent-graph/  Pipeline diagram and the mapping from job state to it
    charts/       Chart cards, price, returns, financials, sentiment, comparison
    ui/           Icons
  hooks/          Job polling, reduced-motion preference
  lib/            API client, formatting, labels, report text normalization
  styles/         Design tokens and global styles
```

## Design system

Colours, radii and shadows are CSS custom properties in `styles/index.css`, with
dark (default) and light themes switched by `data-theme` on `<html>`. The
palette follows the logo: gold for primary actions, sage green as the
secondary accent, navy surfaces.

Chart colours are a fixed categorical sequence (`--chart-cat-1` to `-6`),
assigned by position and never cycled. They are checked for contrast against
both themes' surfaces. Series labels are drawn in text colours, never in the
series colour. Every chart has a hover tooltip, and charts with more than one
series have a legend.

Animations are entrance-only or CSS-driven and respect
`prefers-reduced-motion`. `AnimatePresence` exit animations are not used: with
this framer-motion and React 19 pairing they can leave views stacked.

## API

`lib/api.js` calls `/api/...`. The Vite dev server proxies that to
`VITE_API_BASE` (default `http://127.0.0.1:8000`), and the Docker image's nginx
proxies it to the backend container. For a static host such as Vercel, set
`VITE_API_BASE_DIRECT` at build time to the API's URL. Jobs are polled every
2.5 seconds until they finish.

## Brand assets

Icons, the favicon set, the social preview image and the header logo in
`public/brand/` are generated from `assets/brand/logo.png` by
`scripts/build_brand_assets.py`. Edit the source and rerun the script rather
than editing the outputs.

## Development

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production build in dist/
npm run lint       # oxlint
```
