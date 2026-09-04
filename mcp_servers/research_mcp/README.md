# research-mcp

An MCP server for **news, market sentiment, and corporate-announcement signal**
on Indian equities. It is the tool layer the **News & Sentiment Agent** in
ArthaNeeti calls.

Transport: **stdio** (for now). Same conventions as `market_data_mcp`:
framework-agnostic core in `research.py`, thin MCP wrapper in `server.py`, dict
returns with `{"error": "..."}` on failure (never raises), an `as_of` timestamp on
every success, and a standalone smoke test.

## External services

| Service | Key | Used for |
|---------|-----|----------|
| [Tavily](https://tavily.com) | `TAVILY_API_KEY` | web / news search |
| [Gemini](https://ai.google.dev) | `GEMINI_API_KEY` | LLM sentiment classification |

Keys are read from the project `.env` (real environment variables take
precedence).

**Gemini model & free-tier quota.** Default `gemini-3-flash-preview`, with
`gemini-flash-lite-latest` then `gemini-flash-latest` as automatic fallbacks
(each model has a *separate* quota bucket). `_gemini_json` retries 5xx and 429
with bounded backoff, parses the server's `retryDelay`, and — since this change —
clears the **shared cross-process rate limiter** (`shared/llm_rate_limiter.py`)
before every HTTP attempt via `rl.acquire("generate:<model>")`, so sentiment
calls coordinate with filings-rag's embeddings and other agents against one
account-wide quota. Override the primary model with `GEMINI_MODEL`; tune limits
with `LLM_RL_GENERATE_RPM` / `_TPM` / `_RPD`. Observed free-tier limits
(Sept 2026, will drift):

| model | ~requests/min | ~requests/day |
|-------|---------------|---------------|
| `gemini-3-flash-preview` | 5 | (higher) |
| `gemini-flash-latest` (→ `gemini-3.8-flash`) | — | ~20 |
| `gemini-2.5-flash` / `-flash-lite` | — | **404, retired** |

So on the free tier, **`get_sentiment` is effectively rate-limited to ~5
calls/minute** and aggregate-mode sentiment on a basket of companies will need
pacing or paid quota. When the shared limiter reports the daily wall,
`get_sentiment` returns `{"error": "Gemini call failed ..."}` — degrade
gracefully, don't treat missing sentiment as neutral. The test script spaces its
sentiment calls 14s apart (`GEMINI_TEST_SPACING_S`). Don't pin `gemini-2.5-flash`
— it 404s for keys created after its retirement.

**Why an LLM for sentiment instead of a dedicated model?** Financial-news
sentiment is a task a general LLM handles well zero-shot, and it keeps the
project's dependency footprint lean — no `transformers`/`torch` sentiment
pipeline to host, no model to fine-tune or version. The cost is the caveats in
the next section.

## Tools

| Tool | Signature | What it returns |
|------|-----------|-----------------|
| `search_news` | `(query: str, max_results: int = 10)` | General news search. `max_results` clamped 1–20. |
| `get_company_news` | `(ticker_or_name: str, days_back: int = 30)` | News scoped to one company over a window. `days_back` clamped 1–365. Each item flagged `mentions_company`; response reports `on_company_count`. |
| `get_sentiment` | `(text_or_ticker: str)` | Sentiment label + score + rationale. Dual-mode (see below). Aggregate mode flags `mentions_company` per article and reports `breakdown_on_company`. |
| `get_corporate_announcements` | `(ticker: str, days_back: int = 30)` | Announcement-style news (results / dividends / board meetings / M&A …), each flagged `mentions_company` + `matched_keywords` → `likely_announcement`, sorted flagged-first. |

Every result item is `{title, url, published_date, source_score, snippet}`.
`source_score` is Tavily's own relevance score for the result (0–1), not a
sentiment or quality judgement.

**Entity flagging is consistent across the three company-scoped tools.**
`get_company_news`, `get_sentiment` (aggregate), and `get_corporate_announcements`
all attach a `mentions_company` boolean per result via the same tight alias check
(`research.py:_annotate_company`) — `M&M` matches `"mahindra & mahindra"` / `"m&m"`
but not bare `"mahindra"` (Tech Mahindra, Mahindra Finance). Results are **flagged,
not dropped**. Only `get_corporate_announcements` additionally *sorts* by the flag
(its job is precision); the other two keep Tavily's relevance order so the
consumer decides how to weight off-entity items.

### Ticker / name handling

Pass an NSE/BSE symbol (`RELIANCE.NS`, `M&M.NS`) or a plain company name. A small
built-in map (`research.py:_KNOWN_NAMES`) turns the ~13 tickers we care about
(the 10 filing companies plus a few peers) into full names for better search
queries — `RELIANCE` → `"Reliance Industries"`. Anything not in the map is used
verbatim, so an unmapped ticker like `ADANIENT` will search for the literal
string `"ADANIENT"` and give worse results. Extend the map as the universe grows.

### `get_sentiment` — why dual-mode

The News & Sentiment Agent needs two different things at different points in its
work, so the tool detects which you want from the shape of the input:

- **Aggregate mode** — input looks like a ticker or short company name
  (`"RELIANCE.NS"`, `"Infosys"`). Fetches ~10 recent articles via Tavily and asks
  Gemini for a per-article label **and** an overall assessment in one call.
  Returns `overall {label, score, rationale}`, a `breakdown`
  (positive/neutral/negative counts), and the scored `articles`. This is the
  "how is sentiment on X right now" path.
- **Text mode** — input is a longer string (a headline, an analyst quote, an
  earnings-call paragraph). Scores *that text* directly. This is the "judge this
  specific statement" path, used when the agent already has the text in hand.

Detection heuristic: `≤ 48 chars`, `≤ 5 words`, no sentence punctuation, or an
`.NS`/`.BO` suffix, or a known ticker → aggregate mode; otherwise text mode. It
is a heuristic — a 5-word headline with no punctuation will be misread as a
company name. If you need to force a mode, pad text input past the threshold or
call `search_news` + text-mode `get_sentiment` yourself.

## Data caveats — read before trusting output

These tools are **useful signal, not a system of record.** Being specific about
what they don't guarantee (in the spirit of `market_data_mcp`'s ROE-methodology
note):

### Sentiment (Gemini)

- **`score` is not a calibrated probability.** It is the model's self-reported
  confidence. Treat `0.9` as "the model is fairly sure", not "90% of the time
  this is correct". We have not run a labelled backtest to calibrate it.
- **Not deterministic.** `temperature=0` makes runs *usually* identical but the
  API does not guarantee it; the same input can occasionally flip label or move
  the score.
- **Headline-framing sensitive.** The model scores the text it is given. A
  sensational headline about a mildly positive event can pull the label.
- **No India/finance fine-tuning.** It is a general model reading English text;
  domain nuance (regulatory context, promoter-pledge dynamics, sector base
  rates) is only as good as the model's general knowledge.
- **Aggregate mode reflects the sample, not the world.** The ~10 articles are
  whatever Tavily surfaced for the query in the last 30 days — not an exhaustive
  or de-duplicated news set, and syndicated copies of one story count multiple
  times. Off-entity articles (a group company / peer) **are** still scored, but
  they are flagged `mentions_company: false`, marked as such in the prompt so the
  model does not let them drive the overall label, and excluded from the
  `breakdown_on_company` counts (`breakdown` counts everything). In one M&M test
  run, 2–3 of 10 articles were about Mahindra Finance / M&M Financial Services;
  the overall label held (`positive`) but the raw `breakdown` was inflated —
  `breakdown_on_company` is the number to trust.
- **Free-tier rate limits will bite.** See the quota table above — back-to-back
  sentiment calls hit HTTP 429 on the free tier. `get_sentiment` returns
  `{"error": "Gemini call failed ..."}` when every fallback model is exhausted;
  the caller should degrade gracefully, not treat missing sentiment as neutral.

### `get_corporate_announcements` — this is NOT the NSE/BSE feed

There is no free, clean structured API for Indian corporate announcements, so v1
is a **Tavily news search + a two-signal post-filter**:

1. Search `"<company name>" stock news results earnings dividend`, windowed to
   `days_back`. The `stock news` part is the entity anchor — without it, a
   `"Reliance Industries" results earnings dividend` query drifted on one run to
   *Reliance Worldwide* (ASX), *Strathcona Resources*, *Rain Industries* and
   returned **zero** actual Reliance Industries items. Longer `OR`-keyword queries
   were tried and abandoned for the same reason.
2. Per result, compute two booleans:
   - `mentions_company` — a specific alias of the company appears in the
     title/snippet, bounded by non-alphanumerics. The alias list is deliberately
     tight: `M&M` matches `"mahindra & mahindra"` / `"m&m"` but **not** bare
     `"mahindra"` (which is Tech Mahindra, Mahindra Finance, …); `RELIANCE`
     matches `"reliance industries"` / `"ril"` but not `"reliance power"`.
   - `matched_keywords` — which of a ~25-word announcement vocabulary appear.
3. `likely_announcement = mentions_company AND matched_keywords`. Results sort
   likely-first; the response also reports `likely_announcement_count` and
   `on_company_count`.

Consequences, stated plainly:

- It surfaces **news coverage about** announcements, not the announcements
  themselves. An announcement with no press coverage is missed.
- `published_date` is the **article's** date, not the exchange filing timestamp,
  and `days_back` is approximate — you may see an item a bit outside the window.
- `matched_keywords` is a keyword heuristic: a "what to expect before Q2 results"
  preview trips it just like the actual results release.
- The alias list only covers the ~13 mapped tickers. An **unmapped** ticker falls
  back to matching its full name / first two words, which is looser — extend
  `_KNOWN_ALIASES` as the universe grows.
- The **un-flagged tail** of the results list still contains peer / group-company
  bleed-through (e.g. Tech Mahindra / Mahindra Finance in an M&M query). That is
  expected — the flags and sort exist precisely so the consumer can lean on the
  `likely_announcement` items and treat the rest as low-confidence. In testing,
  `RELIANCE` / `TCS` came back ~10/10 on-company; `M&M` ~5/10 (the rest were
  other Mahindra-group companies, correctly left un-flagged).
- **Tavily is non-deterministic** — the same query 20 minutes apart returns
  different sets. Expect run-to-run variation in which announcements surface and
  how many clear the `likely_announcement` bar.
- It is **not authoritative.** The `disclaimer` field says so; pass it along
  rather than presenting the list as an official record.

A later version could scrape NSE's `corporate-announcements` JSON endpoint or
integrate a paid filings feed; deliberately out of scope for v1.

## Known TODOs

- ~~Gemini call rate-limiting for agent orchestration~~ — **done.** `_gemini_json`
  now clears `shared/llm_rate_limiter.py` (a cross-process SQLite limiter)
  before every attempt, so concurrent agents + filings-rag ingestion coordinate
  against one account-wide quota. See `shared/README.md`.
- **`_KNOWN_NAMES` / `_KNOWN_ALIASES` cover ~13 tickers.** Extend both as the
  company universe grows; unmapped tickers get a weaker name-based fallback.

### News search (Tavily)

- **Recall and freshness depend on Tavily's index** and its `days` windowing,
  which is approximate — you may see an item slightly outside the window.
- **`published_date` quality varies by source**; some report date-only
  (`00:00:00 GMT`), a few report a wrong date, and some are `null`.
- **Entity ambiguity.** The company query is `"<name>" stock news` (quoted name
  + two plain words). A longer `OR`-keyword query was tried and dropped — it made
  Tavily's semantic news search drift to same-theme stories about *other*
  companies (a `RELIANCE.NS` sentiment query came back full of ReNew / Praj /
  Alfa Ica results). Even the quoted-name query occasionally lets through
  *Reliance, Inc.* (a US metals company, ticker RS), a group company, or generic
  "Reliance" pages. `get_company_news`, `get_sentiment` (aggregate), and
  `get_corporate_announcements` all attach `mentions_company` so the consumer can
  see which results are on-entity; `search_news` (topic search, no single company)
  does not. Searches send `country="india"` to bias toward Indian sources, but
  Tavily appears to ignore it on the current tier — treat it as best-effort.
- **No paywall bypass** — snippets are whatever Tavily extracted.

## Running the server

```bash
# from the repo root, with the project venv active
python mcp_servers/research_mcp/server.py
```

or as a module: `python -m mcp_servers.research_mcp.server`.

Example client config:

```json
{
  "mcpServers": {
    "research": {
      "command": "python",
      "args": ["mcp_servers/research_mcp/server.py"]
    }
  }
}
```

## Testing

`test_research.py` is a **standalone smoke test** (not pytest). It hits the live
Tavily and Gemini APIs, so it needs network access and both keys in `.env`.

```bash
python mcp_servers/research_mcp/test_research.py
```

It:

1. calls all 4 tools against `RELIANCE.NS`, `TCS.NS`, `M&M.NS` and prints the full
   JSON so you can eyeball whether the news and sentiment look reasonable;
2. checks `get_sentiment` mode detection and that obviously-positive /
   obviously-negative text gets the right label;
3. checks graceful failure — empty input, a missing `TAVILY_API_KEY`, and an
   empty result set (stubbed, since Tavily almost always returns *something*),
   which must surface as `count: 0` + a `note`, **not** an error.

Exit code `0` if every check passes, `1` otherwise. Because it calls a
non-deterministic LLM and a live news index, the exact articles and scores will
differ run to run; the assertions check structure and the clear-cut cases only.

It makes ~7 Gemini calls spaced 14s apart (free-tier rate limit), so a full run
takes roughly 3–4 minutes. Set `GEMINI_TEST_SPACING_S=0` if you have paid quota.

## File layout

```
mcp_servers/research_mcp/
├── __init__.py
├── server.py           # MCP server: 4 tool definitions + stdio entrypoint
├── research.py         # framework-agnostic Tavily + Gemini logic (the real work)
├── test_research.py    # standalone smoke test
└── README.md
```
