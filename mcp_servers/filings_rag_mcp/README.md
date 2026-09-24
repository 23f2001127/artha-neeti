# filings-rag-mcp

Retrieval over the text of companies' annual reports, with page citations. An
indexing pipeline parses, chunks and embeds each PDF into Postgres with
pgvector; the MCP server (stdio) answers the annual-report agent's queries.

| Setting | Use |
| --- | --- |
| `DATABASE_URL` | Postgres with the `vector` extension |
| `GEMINI_API_KEY` | Embeddings (`gemini-embedding-001`) |

Tables (`filing_chunks`, `filing_ingestions`) and indexes are created
automatically.

## Corpus

Ten annual reports are indexed: Reliance, TCS, M&M, Bharti Airtel, HDFC Bank,
Hindustan Unilever, ICICI Bank, Infosys, L&T and Sun Pharma. That is 3,291
pages in 3,980 chunks; the reports are fiscal 2024-25 except TCS (fiscal
2025-26). More companies can be added through the web app or the API (upload or
web fetch).

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_filing` | `query`, `ticker`, `top_k` | Most similar chunks: page, similarity, fiscal year, table flag, text |
| `get_financial_statement_section` | `ticker`, `statement_type` (`balance_sheet`, `income_statement`, `cash_flow`, `equity_changes`) | Chunks from that statement, with `pages_returned` |
| `compare_yoy_metrics` | `ticker`, `metric` | The report's own year-on-year disclosures for a metric, with `basis` and `limitation` |

Failures return `{"error": ...}`; successes carry `as_of`.

- **Statements.** Found by meaning plus statement headers ("consolidated
  statement of profit and loss"). Header matches rank first; pages 1 to 8
  are excluded because the table of contents repeats every header. Page
  positions vary too much between companies for a fixed page range.
  Standalone and consolidated versions can both appear.
- **Year-on-year.** Each company has one report, so this tool returns the
  report's own year-on-year commentary and prior-year columns, not a
  multi-year trend. The response says so in `limitation`.

## Indexing

```bash
python -m mcp_servers.filings_rag_mcp.ingest                  # PDFs in data/filings/, skipping finished ones
python -m mcp_servers.filings_rag_mcp.ingest --only RELIANCE TCS
python -m mcp_servers.filings_rag_mcp.ingest --force          # re-index everything
python -m mcp_servers.filings_rag_mcp.ingest --status
```

Bulk files are named `TICKER_AR_YYYY-YY.pdf` (`MM_AR_...` maps to `M&M`).
`ingest_file()` indexes one PDF with an explicit ticker, company and fiscal
year; the API's upload and fetch jobs use it.

### Chunking

- Text is extracted page by page with pypdf, so every chunk cites one page.
- A page up to 1,100 tokens is one chunk. Longer pages split into windows with
  150 tokens of overlap on paragraph and line boundaries. Pages under 24 tokens
  are skipped.
- Section detection was not used because report layouts differ too much
  between companies.

### Tables

PDF extraction flattens tables into runs of numbers. Each chunk gets a
`numeric_density` and a `may_contain_tabular_data` flag: set at density 0.18 or
above, or on four consecutive numeric tokens. About 41% of chunks are flagged.
The flag warns that labels may be scrambled even where figures are intact; the
agent hedges figures from flagged chunks. Extraction also renders `₹`
inconsistently (as `C` or `J`).

### Embeddings

- 768 dimensions: pgvector's HNSW index supports up to 2,000, and the model
  holds up well when truncated.
- Vectors are L2-normalized in code, because Gemini only normalizes
  full-length output.
- Chunks are embedded as `RETRIEVAL_DOCUMENT` and queries as
  `RETRIEVAL_QUERY`.

### Quota and resuming

The free tier allows 1,000 embedding requests a day, one per chunk, plus
per-minute limits. The same account quota also serves the news sentiment calls,
so all calls go through the shared rate limiter.

- Inserts commit in groups of 60 chunks.
- A finished file is skipped on later runs.
- A partly indexed file is cleared and redone.
- When the daily quota runs out, the run stops cleanly; running it again after
  the reset (about midnight US Pacific) continues. `scripts/daily_ingest.ps1`
  automates this.

### Finding reports on the web (`fetch.py`)

Used by `POST /filings/fetch`:
1. Search Tavily and keep only results that are direct PDF links.
2. Rank them: "annual report" titles above quarterly results, with a bonus
   for the requested fiscal year.
3. Download the top candidates and accept the first whose opening pages
   contain the company's name followed by its corporate suffix ("ITC
   Limited"). This rejects a subsidiary's report ("ITC Hotels Limited").

HTML pages are not scraped. When nothing qualifies, the job fails with a
suggestion to upload the report instead.

## Running

```bash
python -m mcp_servers.filings_rag_mcp.server
```

## Tests

`tests/integration/test_filings_retrieval.py` (`--live`) prints the retrieved
text and pages for each tool against Reliance, TCS and M&M and checks their
structure. Each query makes one embedding call.
