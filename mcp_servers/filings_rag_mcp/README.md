# filings-rag-mcp

A retrieval-augmented pipeline over the **actual annual-report PDFs** of ~10 large
Indian companies (in `data/filings/`, one filing each — FY2024‑25, TCS is
FY2025‑26). Ingestion parses, chunks, embeds and stores; the MCP server answers
grounded questions with cited pages. Tool layer for the **Filings Agent**.

Same conventions as `market_data_mcp` / `research_mcp`: framework-agnostic core
(`retrieval.py`), thin MCP wrapper (`server.py`), dict returns with
`{"error": "..."}` on failure (never raises), `as_of` on success, standalone test.

## Infrastructure

| Piece | What |
|---|---|
| `DATABASE_URL` | Supabase Postgres 17 + **pgvector 0.8.2** |
| `GEMINI_API_KEY` | Gemini embedding API (`gemini-embedding-001`) |

Both read from the project `.env` (real env vars win). Tables (`filing_chunks`,
`filing_ingestions`) and indexes are created automatically by `ingest.py` /
`init_schema()`.

## Embeddings

- **Model**: `gemini-embedding-001` — the current stable model. `text-embedding-004`
  is retired; `gemini-embedding-2` mis-batches (returned 1 vector for 3 inputs in
  testing). Override with `FILINGS_EMBED_MODEL`.
- **Dimensions**: **768** (`output_dimensionality=768`, override `FILINGS_EMBED_DIM`).
  The full model is 3072-dim but pgvector's HNSW index tops out at 2000 dims;
  Gemini's Matryoshka training keeps 768 strong. Reduced-dim vectors are **not**
  pre-normalised by Gemini, so `embeddings.py` L2-normalises every vector before
  storage — required for cosine similarity to behave.
- **Task types**: `RETRIEVAL_DOCUMENT` for chunks, `RETRIEVAL_QUERY` for queries.

### Quota — free tier has BOTH a per-minute and a per-DAY wall, shared with research-mcp

Observed limits for `gemini-embedding-001` on the free tier (Sept 2026, will drift):

| limit | value | notes |
|---|---|---|
| tokens / minute | ~30,000 | binds first at ~1,000 tokens/chunk (~25–30 chunks/min) |
| requests / minute | ~100 | each text in a batch = 1 request |
| **requests / DAY** | **1,000** | `EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier` — the hard wall |

**The 1,000/day cap is the real constraint.** Each chunk = 1 request, so the free
tier embeds **~1,000 chunks/day** → the full ~4,200-chunk corpus takes
**~4–5 days** of resumed runs (or a paid key, or coarser chunks). `ingest.py`
stops cleanly on the daily wall and prints a resume hint; re-run it after the
quota resets (~midnight US-Pacific).

Rate limiting is delegated to **`shared/gemini_rate_limiter.py`** — a
**cross-process** limiter (SQLite ledger) so ingestion, the live server, and the
LangGraph agents share one view of the account-wide Gemini quota, not three blind
local ones. `embeddings.py` calls `grl.acquire(tokens, "embed", count=len(batch))`
before each `embed_content` call and refunds on 429; `EMBED_BATCH_TOKENS` (default
22,000) still controls how many texts go in one HTTP call. Tune limits via
`GEMINI_RL_EMBED_RPM` / `_TPM` / `_RPD` — see that module's README.

This is the **same Gemini quota research-mcp's `get_sentiment` uses**, which is
exactly why the limiter is shared — a big ingestion and the sentiment tool now
coordinate through one ledger instead of racing.

## Ingestion (`ingest.py`)

Run once / on demand — **not** part of the live MCP tools.

```bash
python -m mcp_servers.filings_rag_mcp.ingest            # all 10, skip done
python -m mcp_servers.filings_rag_mcp.ingest --only RELIANCE TCS
python -m mcp_servers.filings_rag_mcp.ingest --force    # re-ingest everything
python -m mcp_servers.filings_rag_mcp.ingest --status   # print progress, exit
```

### Chunking strategy

- **Parse page by page** with `pypdf`. Every chunk records `page_number` +
  `filename` so retrieval cites a precise page.
- **One chunk per page** when the page is ≤ `CHUNK_TARGET_TOKENS` (default 1,100).
  Longer pages are split into **overlapping windows** (`CHUNK_OVERLAP_TOKENS`
  default 150) on paragraph → line boundaries, so a chunk never straddles two
  pages and mid-page context isn't lost at a boundary. Near-empty pages
  (< 24 tokens) are skipped.
- Why not fixed-character splitting: it cuts sentences and table rows mid-token
  and loses the page anchor. Why not section-based: annual-report section
  structure is not reliably machine-detectable across 10 different companies'
  layouts, and page-anchored chunks are what makes a citation trustworthy.

### Table handling — a known, unsolved limitation (stated honestly)

Raw PDF text extraction **mangles tables**: columns collapse into run-on text, so
a balance sheet reads as `Statutory Reserve As per last Balance Sheet 445 445
Transferred from Retained Earnings 158 - 603 445 ...`. Perfect table parsing is a
hard, separate problem and **out of scope**. Instead each chunk is scored:

- `numeric_density` — fraction of whitespace tokens that look like numbers;
- `may_contain_tabular_data` — `true` when `numeric_density ≥ 0.18` **or** the
  text has a run of ≥ 4 number-ish tokens in a row (a collapsed row).

This is a **flag, not a fix.** A `true` chunk is probably a flattened table — the
numbers are likely intact but their row/column labels may be scrambled; cite the
page and have a human/agent verify. A `false` chunk is probably prose. Expect
false positives (a paragraph full of figures) and false negatives (a sparse
table). ~40–50% of chunks flag `true` in practice — financial reports are
number-dense.

Also: PDF font glyphs for `₹` extract inconsistently as `C` or `J`
(`₹ 25,211 crore` → `C 25,211 crore`), and apostrophes as `?` (`Employees?
Stock Option Scheme`). Retrieval is semantic enough to tolerate this; downstream
display should be aware.

### Entity boundary

Simple, unlike research-mcp's group-company problem: each PDF **is** one company's
own filing. Ticker is derived from the filename prefix
(`RELIANCE_AR_2024-25.pdf` → `RELIANCE`), with one override (`MM` → `M&M` to match
the project's NSE-style ticker). The ticker→name map mirrors `research_mcp`'s
convention (kept local so the servers stay independent). Every chunk is tagged
with its ticker; retrieval filters on it — no cross-company bleed is possible.

### Resumability

- A filename in `filing_ingestions` = fully done → skipped (unless `--force`).
- Chunks present but no `filing_ingestions` row = a run died mid-file → those
  chunks are deleted and the file redone from scratch.
- Inserts commit per group (default 60 chunks), so a crash costs at most one
  group, never the whole run. On an `EmbeddingQuotaError` the run stops and prints
  a resume hint; just run the command again.

### Ingestion cost / scale

10 filings, **3,291 PDF pages total** → roughly **~4,200 chunks** (≈ 1.3
chunks/page; ~3.3M input tokens; each chunk = one 768-dim vector = one embedding
API request). Two limits stack:

- **per-minute**: the ~27k tok/min throttle → ~25 chunks/min → a 300-chunk filing
  takes ~12–15 min of wall time (mostly waiting on the token budget).
- **per-day**: 1,000 embedding requests → **~1,000 chunks/day**, so the full
  corpus is a **~4–5 day** job of resumed runs on the free tier.

Test companies (`RELIANCE`, `TCS`, `M&M`) are queued first so a partial run still
demos. Live numbers: `ingest.py --status`.

## MCP tools (`server.py`)

Run: `python mcp_servers/filings_rag_mcp/server.py` (stdio). Requires ingestion to
have run first.

### `search_filing(query, ticker, top_k=5)`

Embed the query, cosine-similarity search over that ticker's chunks. Returns
`{page_number, similarity (0–1), may_contain_tabular_data, numeric_density,
fiscal_year, text}` per hit, best first. The general-purpose tool for grounded
questions about a company's disclosures.

### `get_financial_statement_section(ticker, statement_type)`

`statement_type` ∈ `balance_sheet`, `income_statement`, `cash_flow`,
`equity_changes` (aliases like `"profit and loss"`, `"p&l"` accepted).

Approach: a hand-written semantic query per statement type **plus a keyword
boost** — chunks whose text contains an actual statement header
(`"consolidated statement of profit and loss"`, `"standalone balance sheet"`,
`"statement of cash flows"`, …) are pulled in via `ILIKE` and ranked ahead of the
purely-semantic hits, de-duplicated on `(page, chunk_index)`. Keyword matches are
restricted to `page_number > 8` — the table of contents lists every statement
header and would otherwise always match.

Tuning that mattered (found while testing): the bare phrase
`"statement of profit and loss"` matches every *note* that references the P&L, so
the keyword list uses the fuller `"consolidated/standalone statement of profit and
loss"` headers instead. With that, RELIANCE/TCS land the real statement page in
the top 1–3 hits for balance sheet, cash flow, and income statement.

**No hard page-range assumption.** Annual-report structure is only *roughly*
predictable (statements sit in the back third; standalone before consolidated),
and it varies enough across companies that a fixed page window would miss as often
as it helps. So the tool finds the statement by meaning + header text and
**reports the pages it landed on** (`pages_returned`) for the caller to
sanity-check.

Limits: it returns chunks, not a parsed statement — numbers may be
column-flattened; standalone and consolidated versions both match (by design — the
caller sees both); the auditor's report and section dividers, which sit right next
to the statements and name them, sometimes appear in the results.

### `compare_yoy_metrics(ticker, metric)` — scoped honestly to ONE filing

**We chose to scope this to the filing's own year-over-year disclosure, not fake a
multi-year comparison.** ArthaNeeti holds exactly one annual report per company,
so a real cross-filing trend is impossible here. What annual reports *do* contain
is their own YoY commentary — MD&A / Board's Report lines like *"Revenue grew 7.2%
Y‑o‑Y"* and financial statements with current + prior-year columns. This tool
retrieves *that*: a semantic query for the metric's year-on-year change plus a
keyword boost for `"Y-o-Y"`, `"year-on-year"`, `"compared to the previous year"`,
etc.

The response spells out the scope in two fields:

- `basis`: *"single filing's own reported year-over-year figures (FY… vs the prior
  year, as stated in the document)"*
- `limitation`: *"NOT a cross-filing multi-year comparison — ArthaNeeti has one
  annual report per company."*

To do true multi-year trend analysis you'd ingest prior years' reports — a
deliberate v2, out of scope now.

## Testing

`test_retrieval.py` — standalone (not pytest). Prints the **actual retrieved chunk
text + page numbers** so retrieval quality is judged by eye, then a few
structural assertions.

```bash
python mcp_servers/filings_rag_mcp/test_retrieval.py
```

Needs ingestion done for at least `RELIANCE`, `TCS`, `M&M`. Makes ~1 Gemini
embedding call per query (small: query text only).

## Ingestion run

Cold run started 2026‑09‑03. RELIANCE and TCS completed; the free-tier
**1,000 embeddings/day** cap was then hit and ingestion stopped cleanly
(checkpointed). M&M and the remaining 7 filings resume on the next run after the
quota resets — `python -m mcp_servers.filings_rag_mcp.ingest` (idempotent, skips
what's done).

| ticker | pages | chunks | tabular chunks | status |
|---|---:|---:|---:|---|
| RELIANCE | 146 | 310 | 167 (54%) | ✅ ingested |
| TCS | 360 | 381 | 224 (59%) | ✅ ingested |
| M&M | 247 | ~470 | ~192 | ⏳ pending quota |
| BHARTIARTL | 286 | ~483 | ~328 | ⏳ pending quota |
| HDFCBANK | 583 | ~598 | ~153 | ⏳ pending quota |
| HINDUNILVR, ICICIBANK, INFY, LT, SUNPHARMA | | ~1,900 combined | | ⏳ pending quota |
| **total (projected)** | **3,291** | **~4,200** | **~45–55%** | 691 done |

Per-minute throughput observed: ~60 chunks per ~2‑minute commit group
(≈ 25k tok/min). RELIANCE 310 chunks took ~15 min, TCS 381 took ~14 min.

## File layout

```
mcp_servers/filings_rag_mcp/
├── __init__.py
├── config.py         # env loading, ticker maps, tunables
├── db.py             # psycopg2 + pgvector: schema, insert, similarity search
├── chunking.py       # pypdf parse -> page-anchored overlapping chunks + table flag
├── embeddings.py     # Gemini embedding, L2-normalise; rate limiting -> shared/
├── ingest.py         # the pipeline CLI (resumable)
├── retrieval.py      # framework-agnostic logic behind the 3 tools
├── server.py         # MCP server: 3 tools + stdio entrypoint
├── test_retrieval.py # standalone retrieval-quality test
└── README.md
```
