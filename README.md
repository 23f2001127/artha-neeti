# ArthaNeeti

A multi-agent AI system for Indian equity research. Given a natural-language question about NSE-listed companies, a **LangGraph planner** decides which company (or companies) the query is about, which of three specialist agents can actually answer it, and runs them — each one grounded in real tools rather than model memory: live market data from yfinance, news and sentiment from a search API, and retrieval over the actual text of company annual reports. A synthesis step reconciles the specialists' outputs, flags where they disagree, and returns a structured report where **every claim carries its source and its caveat**.

The name is Sanskrit — *artha* (wealth, meaning) + *nīti* (policy, method).

---

## What it does

Ask it something like *"give me a complete research view on TCS"* or *"compare TCS and Infosys on fundamentals, sentiment and risk profile"* and it will:

1. **Route** — resolve the company names to NSE tickers (confirming each one exists), decide single-company vs. comparison mode, and select only the specialists the question needs. *"What's Reliance's current stock price"* calls one agent; *"complete research view"* calls all three. Every skip is recorded with a reason.
2. **Gather** — run the selected specialist agents. Each is a ReAct agent that chooses which of its MCP server's tools to call.
3. **Synthesize** — merge each company's specialist outputs into one report: an executive summary, per-section detail, explicitly flagged conflicts (*"strong fundamentals vs. negative recent sentiment — not a contradiction, different time horizons"*), a per-claim source-and-caveat map, and an honest list of what's missing.
4. **Compare** — for multi-company queries, a final pass over the finished reports produces a dimension-by-dimension comparison (profitability, valuation, leverage, risk profile…) without manufacturing a winner where the data doesn't support one.

The output includes the full **routing trace** and **provenance** — not just the answer, but which specialists ran, why the others didn't, and where every number came from.

---

## Architecture

```mermaid
flowchart TD
    Q[User query] --> R

    subgraph P["Planner · LangGraph StateGraph"]
        direction TB
        R["<b>route</b><br/>resolve companies → NSE tickers,<br/>pick which specialists the query needs"]
        R --> G["<b>gather</b><br/>bounded-concurrency fan-out<br/>to the selected specialists"]
        G --> SY["<b>synthesize</b><br/>reconcile each company's outputs<br/>into one cited report"]
        SY --> CM["<b>compare</b><br/>cross-company dimensions<br/>(multi-company queries only)"]
    end

    G --> MDA["Market Data Agent"] --> M1[["market-data-mcp<br/>4 tools"]] --> YF(("yfinance"))
    G --> NSA["News + Sentiment Agent"] --> M2[["research-mcp<br/>4 tools"]] --> TV(("Tavily + Gemini"))
    G --> FA["Filings Agent"] --> M3[["filings-rag-mcp<br/>3 tools"]] --> PG[("Postgres + pgvector<br/>3,980 chunks / 10 reports")]

    SY --> OUT["Structured research report<br/>plus routing + provenance trace"]
    CM --> OUT
```

**The layers, and why they're separate:**

| Layer | What | Why it's its own thing |
|---|---|---|
| **Planner** (`agents/planner.py`) | A LangGraph `StateGraph`: `route → gather → synthesize → [compare] → finalize`, with a typed state and conditional edges. | Orchestration is a distinct concern from any single agent. The planner decides *what to fetch*; specialists decide *how*. |
| **Specialist agents** (`agents/*_agent.py`) | Market Data, News & Sentiment, Filings. Each is a Groq-backed ReAct agent wrapping exactly one MCP server, with a structured-output synthesis step and a provenance extractor. | Each domain has its own tools, caveats, and failure modes. A shared `_base.py` (~300 lines) holds everything that doesn't change between them. |
| **MCP servers** (`mcp_servers/*/`) | 11 tools across 3 stdio servers. Framework-agnostic core logic, thin MCP wrapper, `{"error": "..."}` on failure (never raises), `as_of` timestamps on success. | The tool layer is reusable and independently testable. Agents connect as real MCP clients over stdio — the same way any MCP host would. |
| **Shared infra** (`shared/`) | A cross-process rate limiter over the account-wide Gemini and Groq quotas. | Multiple agent processes and MCP servers share one API key per provider. The limiter is the only thing that sees the whole picture. |

---

## What makes this a real system, not a demo

**A cross-process rate limiter that actually coordinates concurrent work.** Every hosted-LLM call in the codebase — Groq reasoning, Gemini sentiment classification, Gemini embeddings — goes through `shared/llm_rate_limiter.py`, a SQLite ledger using WAL mode and `BEGIN IMMEDIATE` as a cross-process write lock. It enforces per-minute *and* per-day limits on requests *and* tokens, with a shared bucket for Groq's model-fallback chain (Groq rate-limits account-wide, so per-model buckets would admit calls the API then rejects). It blocks and paces rather than failing, and raises a clean `QuotaExceededError` with a "resets in ~Nh" message when a wall is genuinely hit. The free-tier per-minute token ceiling was measured, not taken from the headers — the docs advertise ~8k tokens/min for these models; sustained multi-agent load 429s at ~5k.

**A RAG pipeline over real filings with page-level citation.** 10 actual annual-report PDFs (Reliance, TCS, M&M, HDFC Bank, Infosys, L&T, and four more — FY2024-25, TCS FY2025-26), **3,291 pages → 3,980 chunks**, embedded with Gemini at 768 dimensions (Matryoshka-truncated and L2-normalized, because pgvector's HNSW index caps at 2,000 dims) into Supabase Postgres + pgvector. Chunking is page-anchored — one chunk per page, split only when a page exceeds ~1,100 tokens — so every retrieved passage cites a real page number. **41% of chunks are flagged `may_contain_tabular_data`** (via a numeric-density heuristic), and the Filings Agent hedges any figure that comes from a flagged chunk instead of stating a PDF-flattened table value with false precision. Ingestion ran on the free tier (~1,000 embeddings/day) over five resumable daily passes, coordinated by a Windows scheduled task.

**Entity disambiguation for Indian conglomerate structures.** "Mahindra" matches Tech Mahindra and Mahindra Finance; "Tata" matches a dozen listed entities; a naive news search for M&M returns Tech Mahindra earnings. `research-mcp` carries `_KNOWN_ALIASES` plus `_GROUP_COMPANY_PATTERNS` — regexes that blank out group-company names *before* the alias match — so "Tech Mahindra Q4 results" resolves to `mentions_company: false` for M&M. Aggregate sentiment reports `breakdown_on_company` (only articles that actually name the target) as the trustworthy number, separately from the raw, entity-contaminated count.

**Provenance that survives the whole pipeline.** `as_of` dates, `fiscal_year`, `roe_source` (reported vs. computed), the "NOT the NSE/BSE official feed" disclaimer, the single-filing-year limitation — these are lifted from raw MCP tool output into a structured `provenance` block by each agent, carried into the synthesis prompt, and re-emitted in the final report's `sources_by_claim` map: `{claim → {sources: [...], caveat: "..."}}`. The synthesis step is instructed and tested to attach the *strongest* upstream hedge to any claim it repeats — a carefully qualified finding never gets laundered into a confident one. It also reconciles the fiscal-year gap between yfinance (latest FY) and the filings (a fixed prior year) rather than silently merging them.

---

## Tech stack

**Orchestration & agents** — LangGraph 1.2 (`StateGraph`), LangChain 1.3, Model Context Protocol (`mcp` 2.1, stdio transport)
**LLMs** — Groq (`openai/gpt-oss-120b` + fallback chain) for agent reasoning; Google Gemini (`gemini-3-flash-preview`) for sentiment classification; `gemini-embedding-001` for filings embeddings
**Data & retrieval** — PostgreSQL + pgvector (Supabase), `psycopg2`, `pypdf`
**External data** — yfinance (market data), Tavily (news search)
**Backend / frontend** — FastAPI (planned), a web frontend (planned)
**Language** — Python 3.11

The Groq-for-reasoning / Gemini-for-classification-and-embeddings split is deliberate: Groq's free tier gives ~950 requests/day per model and is fast (~1s/call), which suits the 3–5 calls each agent query burns; Gemini's structured-output mode and embedding API cover what Groq doesn't offer.

---

## Current status

**The backend is functionally complete and verified.**

| Component | Status |
|---|---|
| `market-data-mcp` · `research-mcp` · `filings-rag-mcp` | ✅ built, tested, committed |
| Filings RAG ingestion | ✅ complete — all 10 reports, 3,980 chunks in pgvector |
| `shared/llm_rate_limiter.py` | ✅ built, concurrent-scenario tested |
| Market Data · News & Sentiment · Filings · Synthesis agents | ✅ built, each with a standalone test asserting tool choice *and* caveat fidelity |
| LangGraph Planner | ✅ built; all four routing/execution patterns verified end-to-end (single-tool, full single-company, corpus-miss graceful skip, multi-company comparison) |
| FastAPI service layer | ⬜ not started |
| Web frontend (agent-trace view, report export) | ⬜ not started |

Each component has its own README with the design decisions, test evidence, and known limitations (`mcp_servers/*/README.md`, `agents/README.md`, `shared/README.md`). The agent tests are runnable scripts that print full reasoning traces and structured output, not just pass/fail.

Honest caveats, stated plainly: everything runs on **free API tiers**, so a full multi-company query takes ~15–20 minutes (the rate limiter paces it) and can partially degrade if a heavy agent hits a quota wall mid-run — the planner is built to produce a coherent report from whatever subset succeeded and say what's missing. The filings corpus is a single year per company. Sentiment scores are the classifier's self-reported confidence, not calibrated probabilities. None of this is hidden; it's surfaced in the output.

---

## Running it locally

**Prerequisites:** Python 3.11, a PostgreSQL database with the `vector` extension (a free Supabase project works), and API keys for Groq, Google Gemini, and Tavily (all have free tiers).

```bash
git clone https://github.com/23f2001127/artha-neeti.git
cd artha-neeti
python -m venv venv
venv\Scripts\activate            # Windows;  source venv/bin/activate on Unix
pip install -r requirements.txt
```

Create `.env` in the repo root:

```env
GROQ_API_KEY=...
GEMINI_API_KEY=...
TAVILY_API_KEY=...
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

**Ingest the filings** (one-time; place the annual-report PDFs in `data/filings/` as `TICKER_AR_YYYY-YY.pdf`). Idempotent and resumable — on the free embedding tier it stops cleanly at the daily cap and continues on the next run:

```bash
python -m mcp_servers.filings_rag_mcp.ingest            # all filings
python -m mcp_servers.filings_rag_mcp.ingest --status   # progress
```

**Run the Planner** on a query:

```bash
python agents/planner.py "give me a complete research view on TCS"
```

Or use it as a library:

```python
from agents.planner import plan_sync
report = plan_sync("compare TCS and Infosys on fundamentals and risk profile")
```

**Run any component's tests** (each is a standalone script, not pytest):

```bash
python agents/test_planner.py routing        # routing decisions only — fast, ~4 LLM calls
python agents/test_planner.py 2              # one full end-to-end case
python agents/test_market_data_agent.py
python mcp_servers/filings_rag_mcp/test_retrieval.py
python shared/test_llm_rate_limiter.py
```

---

## Roadmap

- [x] `market-data-mcp` — yfinance tools with average-basis ratio fallback + provenance
- [x] `research-mcp` — Tavily news/sentiment with entity-aware filtering + Gemini classification
- [x] `filings-rag-mcp` — ingestion, page-anchored chunking, pgvector retrieval with cited pages
- [x] Filings RAG ingestion — 10 annual reports, 3,980 chunks
- [x] `shared/llm_rate_limiter.py` — cross-process quota coordination
- [x] Market Data Agent
- [x] News & Sentiment Agent
- [x] Filings Agent
- [x] Synthesis Agent — conflict flagging + per-claim provenance
- [x] LangGraph Planner — selective routing, single-company + multi-company comparison
- [ ] FastAPI service layer
- [ ] Web frontend — live agent-trace view, report export
- [ ] Deployment

---

*Built as a portfolio project. The engineering decisions — and their trade-offs — are documented in the component READMEs; that discussion is the point.*
