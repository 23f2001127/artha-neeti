# ArthaNeeti

A multi-agent AI system for Indian equity research. Given a query about an NSE/BSE-listed company, ArthaNeeti orchestrates specialist agents to pull live market data, recent news and sentiment, and grounded insights from company filings — then synthesizes everything into a structured research report with citations.

**Status:** In active development.

## Why this exists

Most "AI stock analyzer" projects are a single LLM call wrapped around an API. ArthaNeeti is an exercise in building the orchestration, tooling, and retrieval infrastructure a real research system needs: multiple cooperating agents, custom MCP servers as the tool layer, and a RAG pipeline grounded in actual financial filings rather than model memory.

## Architecture

**Agents (LangGraph):**
- **Planner / Orchestrator** — decomposes the user's query, routes to the relevant specialist agents, and replans if a specialist's findings change the picture. Supports both single-company deep dives and multi-company comparisons.
- **Market Data Agent** — price history, fundamentals, valuation ratios, peer comparison.
- **News & Sentiment Agent** — recent news, earnings commentary, sentiment scoring over time.
- **Filings Agent** — retrieval-augmented answers grounded in actual annual reports via a pgvector-backed RAG pipeline.
- **Synthesis Agent** — merges specialist outputs into a final report, explicitly flags where signals disagree, and cites sources for every claim.

**MCP Servers (custom-built tool layer):**
- `market-data-mcp` — wraps yfinance for price/fundamentals/ratios/peer data.
- `research-mcp` — news search and sentiment via Tavily, plus corporate announcements.
- `filings-rag-mcp` — ingestion, embedding, and retrieval over real annual report PDFs.

**Serving & storage:**
- FastAPI backend
- PostgreSQL + pgvector for filings retrieval
- Streamlit frontend with live agent-trace visualization and PDF report export

## Tech stack

Python · LangGraph · LangChain · Model Context Protocol (MCP) · FastAPI · PostgreSQL/pgvector · yfinance · Gemini + Groq (LLM inference) · Tavily (search) · sentence-transformers (embeddings) · Streamlit · Docker

## Setup

_Coming soon — instructions will be added once the core pipeline is functional._

## Roadmap

- [ ] `market-data-mcp` server
- [ ] `research-mcp` server
- [ ] `filings-rag-mcp` server + ingestion pipeline
- [ ] Agent orchestration (single-company mode)
- [ ] Agent orchestration (multi-company comparison mode)
- [ ] Synthesis agent + citation tracing
- [ ] Streamlit dashboard with live agent trace
- [ ] Deployment
