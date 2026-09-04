"""Shared configuration for filings-rag-mcp: env loading, ticker maps, constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# This file is mcp_servers/filings_rag_mcp/config.py -> repo root is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=False)

FILINGS_DIR = REPO_ROOT / "data" / "filings"

# --- embeddings ---------------------------------------------------------------
# gemini-embedding-001 is the current stable model (text-embedding-004 is retired,
# gemini-embedding-2 mis-batches). 768 dims: pgvector's HNSW index tops out at 2000
# dims, and Gemini's Matryoshka training keeps 768 strong. Vectors are L2-normalised
# in code (Gemini only pre-normalises the full 3072-dim output).
EMBED_MODEL = os.environ.get("FILINGS_EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.environ.get("FILINGS_EMBED_DIM", "768"))

# Rate limiting (per-minute tokens/requests + the 1,000/day embedding cap) is
# owned by shared/llm_rate_limiter.py - a CROSS-PROCESS limiter, so ingestion,
# the live server, and future agents share one view of the account quota. Tune it
# via LLM_RL_EMBED_RPM / _TPM / _RPD (see that module's docstring).
#
# EMBED_BATCH_TOKENS only controls how many chunk texts go in one embed_content
# HTTP call; keep it <= the limiter's per-minute token budget (default 30k).
EMBED_BATCH_TOKENS = int(os.environ.get("FILINGS_EMBED_BATCH_TOKENS", "22000"))

# --- chunking ----------------------------------------------------------------
# One chunk per page when the page fits; longer pages split into overlapping
# windows. Keeps every chunk citable to a single page.
CHUNK_TARGET_TOKENS = int(os.environ.get("FILINGS_CHUNK_TOKENS", "1100"))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("FILINGS_CHUNK_OVERLAP", "150"))
CHUNK_MIN_TOKENS = 24  # skip near-empty pages / fragments

# --- database ---------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
CHUNKS_TABLE = "filing_chunks"
INGESTIONS_TABLE = "filing_ingestions"

# --- ticker / company mapping ----------------------------------------------
# Mirrors research_mcp's convention (kept local so the servers stay independent).
# Key = ticker as used across the project (NSE style); value = display name.
COMPANY_NAMES: dict[str, str] = {
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
    "M&M": "Mahindra & Mahindra",
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "INFY": "Infosys",
    "LT": "Larsen & Toubro",
    "BHARTIARTL": "Bharti Airtel",
    "HINDUNILVR": "Hindustan Unilever",
    "SUNPHARMA": "Sun Pharmaceutical Industries",
}

# Filename prefixes that don't match the project ticker (e.g. "MM_AR_..." on disk
# but the project uses "M&M").
_FILENAME_TICKER_OVERRIDES: dict[str, str] = {
    "MM": "M&M",
}


def ticker_from_filename(filename: str) -> str:
    """RELIANCE_AR_2024-25.pdf -> RELIANCE ; MM_AR_2024-25.pdf -> M&M."""
    prefix = Path(filename).stem.split("_", 1)[0].upper()
    return _FILENAME_TICKER_OVERRIDES.get(prefix, prefix)


def fiscal_year_from_filename(filename: str) -> str | None:
    """RELIANCE_AR_2024-25.pdf -> '2024-25'."""
    stem = Path(filename).stem
    parts = stem.split("_")
    for part in reversed(parts):
        if part[:4].isdigit() and "-" in part:
            return part
    return None


def company_name(ticker: str) -> str:
    return COMPANY_NAMES.get(ticker.upper(), ticker)
