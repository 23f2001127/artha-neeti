"""PDF parsing + chunking for annual-report filings.

Strategy (see README for the reasoning):
- Extract text **page by page** with pypdf; every chunk keeps its page number so
  retrieval results cite a precise page.
- One chunk per page when the page fits ``CHUNK_TARGET_TOKENS``; longer pages are
  split into overlapping windows on paragraph/sentence boundaries.
- Each chunk carries a ``numeric_density`` and a ``may_contain_tabular_data`` flag
  - raw PDF text extraction collapses table columns into number soup, and this
  heuristic lets a consumer know a chunk is probably a mangled table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pypdf
import tiktoken

from . import config

_ENC = tiktoken.get_encoding("cl100k_base")

# a "number token": 12  1,234  3.5  (12.3)  45%  2024-25
_NUMBER_RE = re.compile(r"\(?-?\d[\d,]*\.?\d*\)?%?")
_WORD_RE = re.compile(r"\S+")


@dataclass
class Chunk:
    ticker: str
    company: str
    filename: str
    fiscal_year: str | None
    page_number: int
    chunk_index: int
    text: str
    token_count: int
    numeric_density: float
    may_contain_tabular_data: bool


def _n_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def _clean_page_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _numeric_density(text: str) -> float:
    """Fraction of whitespace-separated tokens that look like numbers."""
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    numeric = sum(1 for w in words if _NUMBER_RE.fullmatch(w))
    return round(numeric / len(words), 4)


def _looks_tabular(text: str, density: float) -> bool:
    """Heuristic: dense with numbers, or many number tokens crammed together.

    Deliberately conservative - a false positive just adds a warning flag; a false
    negative means a mangled table looks like prose. See README.
    """
    if density >= 0.18:
        return True
    # runs of >=4 number-ish tokens separated only by spaces (a collapsed row)
    if re.search(r"(?:\(?-?\d[\d,]*\.?\d*\)?%?\s+){4,}", text):
        return True
    return False


def _split_long_page(text: str, target: int, overlap: int) -> list[str]:
    """Split one page's text into overlapping windows on paragraph/line breaks."""
    # units = paragraphs, then lines, then whitespace - whichever keeps units small
    units = [u for u in re.split(r"\n\n+", text) if u.strip()]
    if any(_n_tokens(u) > target for u in units):
        units = [u for u in re.split(r"\n", text) if u.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in units:
        ut = _n_tokens(unit)
        if current and current_tokens + ut > target:
            chunks.append("\n".join(current))
            # carry the tail of the previous chunk as overlap
            carry: list[str] = []
            carry_tokens = 0
            for prev in reversed(current):
                pt = _n_tokens(prev)
                if carry_tokens + pt > overlap:
                    break
                carry.insert(0, prev)
                carry_tokens += pt
            current = carry
            current_tokens = carry_tokens
        current.append(unit)
        current_tokens += ut
    if current:
        chunks.append("\n".join(current))

    # a single unit bigger than target (rare: one giant run-on line) -> hard split
    final: list[str] = []
    for c in chunks:
        if _n_tokens(c) <= target * 1.5:
            final.append(c)
            continue
        toks = _ENC.encode(c)
        step = target - overlap
        for start in range(0, len(toks), step):
            final.append(_ENC.decode(toks[start : start + target]))
    return final


def iter_pdf_chunks(pdf_path: Path) -> Iterator[Chunk]:
    filename = pdf_path.name
    ticker = config.ticker_from_filename(filename)
    company = config.company_name(ticker)
    fiscal_year = config.fiscal_year_from_filename(filename)

    reader = pypdf.PdfReader(str(pdf_path))
    chunk_index = 0
    for page_idx, page in enumerate(reader.pages):
        page_number = page_idx + 1
        try:
            text = _clean_page_text(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a bad page shouldn't kill the run
            text = ""
        if _n_tokens(text) < config.CHUNK_MIN_TOKENS:
            continue

        if _n_tokens(text) <= config.CHUNK_TARGET_TOKENS:
            pieces = [text]
        else:
            pieces = _split_long_page(
                text, config.CHUNK_TARGET_TOKENS, config.CHUNK_OVERLAP_TOKENS
            )

        for piece in pieces:
            piece = piece.strip()
            if _n_tokens(piece) < config.CHUNK_MIN_TOKENS:
                continue
            density = _numeric_density(piece)
            yield Chunk(
                ticker=ticker,
                company=company,
                filename=filename,
                fiscal_year=fiscal_year,
                page_number=page_number,
                chunk_index=chunk_index,
                text=piece,
                token_count=_n_tokens(piece),
                numeric_density=density,
                may_contain_tabular_data=_looks_tabular(piece, density),
            )
            chunk_index += 1


def chunk_stats(chunks: list[Chunk]) -> dict:
    if not chunks:
        return {"chunks": 0, "pages": 0, "tabular_chunks": 0, "tokens": 0}
    return {
        "chunks": len(chunks),
        "pages": len({c.page_number for c in chunks}),
        "tabular_chunks": sum(1 for c in chunks if c.may_contain_tabular_data),
        "tokens": sum(c.token_count for c in chunks),
    }
