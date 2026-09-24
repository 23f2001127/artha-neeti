"""Finds and downloads a company's annual-report PDF from web search results.

Used by ``POST /filings/fetch`` as an alternative to uploading; the downloaded
bytes go through the same ``ingest_file()`` pipeline as an upload.

- Only search results whose URL is itself a PDF are considered. Investor
  relations index pages are skipped rather than scraped.
- Candidates are ranked by title and URL, then each download is checked for the
  company's own name and corporate suffix on its first pages, which rejects
  subsidiaries' reports.
- When nothing qualifies, ``FetchError`` is raised and the client is told to
  upload the report instead.

Uses its own small Tavily client so the MCP servers stay independent.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any

import pypdf
import requests
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)

MAX_SEARCH_RESULTS = 8
DOWNLOAD_TIMEOUT = 30
VERIFY_PAGES = 3  # how many leading pages to check for the company's name/ticker
_PDF_MAGIC = b"%PDF-"
_USER_AGENT = "Mozilla/5.0 (compatible; ArthaNeetiBot/0.1; +https://github.com)"

# Real annual-report searches turn up plenty of PDFs that are NOT the annual
# report - quarterly results, a demerged subsidiary's own filing, an unrelated
# corporate announcement. These heuristics are a first pass; _verify_company_
# match() below (checks the downloaded PDF's own text) is the real safety net,
# since title/URL keywords alone can't catch a wrong-company match like
# "ITC Hotels" surfacing for a search for "ITC".
_GOOD_KEYWORDS = ("annual report", "report and accounts", "integrated annual report")
_BAD_KEYWORDS = (
    "quarterly", "quarter ended", "half yearly", "half-yearly", "unaudited",
    "q1fy", "q2fy", "q3fy", "q4fy", "financial statement",
)


class FetchError(RuntimeError):
    """Could not find or download a filing PDF - an expected best-effort miss,
    not a bug. The caller should offer manual upload as the fallback."""


# --------------------------------------------------------------------------- #
_tavily_client: Any = None


def _tavily():
    global _tavily_client
    if _tavily_client is None:
        key = os.environ.get("TAVILY_API_KEY")
        if not key:
            raise FetchError("TAVILY_API_KEY is not set (checked the environment and the project .env).")
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover
            raise FetchError(f"tavily-python is not installed: {exc}") from exc
        _tavily_client = TavilyClient(api_key=key)
    return _tavily_client


def _looks_like_pdf_url(url: str) -> bool:
    return url.lower().split("?")[0].split("#")[0].endswith(".pdf")


def _search_candidates(company: str, fiscal_year: str | None) -> list[dict]:
    """Two query phrasings (not Tavily's pricier 'advanced' depth, to keep this
    on the free tier's basic-search budget), de-duplicated by URL, in the order
    Tavily ranked them."""
    fy = (fiscal_year or "").strip()
    queries = [
        f"{company} annual report {fy} pdf".strip(),
        f"{company} annual report investor relations pdf",
    ]
    client = _tavily()
    seen: set[str] = set()
    candidates: list[dict] = []
    for q in queries:
        try:
            resp = client.search(
                query=q, topic="general", max_results=MAX_SEARCH_RESULTS,
                search_depth="basic", country="india",
            )
        except Exception as exc:  # noqa: BLE001 - normalise every failure to FetchError
            raise FetchError(f"web search failed ({type(exc).__name__}): {exc}") from exc
        for r in (resp.get("results", []) if isinstance(resp, dict) else []):
            url = r.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                candidates.append({"url": url, "title": r.get("title"), "query": q})
    return candidates


def _fiscal_year_tokens(fiscal_year: str | None) -> list[str]:
    """'2024-25' -> ['2024-25', '2024-2025'] so a title/URL spelling either
    way still matches."""
    fy = (fiscal_year or "").strip()
    if not fy or "-" not in fy:
        return [fy] if fy else []
    start, end = fy.split("-", 1)
    tokens = [fy]
    if len(end) == 2 and start[:2].isdigit():
        tokens.append(f"{start}-{start[:2]}{end}")
    return tokens


def _score(candidate: dict, fiscal_year: str | None) -> int:
    text = f"{candidate.get('title') or ''} {candidate['url']}".lower()
    score = 0
    if any(kw in text for kw in _GOOD_KEYWORDS):
        score += 3
    if any(kw in text for kw in _BAD_KEYWORDS):
        score -= 5
    if any(tok.lower() in text for tok in _fiscal_year_tokens(fiscal_year)):
        score += 2
    return score


def _ranked_candidates(company: str, fiscal_year: str | None) -> list[dict]:
    """Direct-PDF search hits, best guess first (see _score) - not just search
    rank, since plenty of direct-PDF hits for a real company are quarterly
    results or a same-family subsidiary's own report, ranked ahead of the
    actual annual report on relevance alone."""
    if not company or not company.strip():
        raise FetchError("company/ticker is empty.")
    candidates = _search_candidates(company.strip(), fiscal_year)
    direct = [c for c in candidates if _looks_like_pdf_url(c["url"])]
    if not direct:
        raise FetchError(
            f"couldn't find a directly-downloadable PDF for {company!r} in the top "
            f"web search results (checked {len(candidates)} page(s), none was a "
            f"direct .pdf link). Try the manual upload instead."
        )
    direct.sort(key=lambda c: _score(c, fiscal_year), reverse=True)
    return direct


def find_filing_pdf_url(company: str, fiscal_year: str | None = None) -> dict:
    """The single best-guess candidate, unverified (no download) - see
    fetch_filing_pdf() for the verified, ingestion-ready path."""
    return _ranked_candidates(company, fiscal_year)[0]


def _normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


_SUFFIXES = ("private limited", "pvt limited", "pvt ltd", "limited", "ltd")


def _core_and_suffix(company: str) -> tuple[str, bool]:
    """'ITC Limited' -> ('itc', True); 'Tata Motors' -> ('tata motors', False).
    The bool says whether the query itself named a corporate suffix."""
    norm = _normalize_name(company)
    for suf in _SUFFIXES:
        if norm.endswith(" " + suf) or norm == suf:
            return norm[: -len(suf)].strip(), True
    return norm, False


def verify_company_match(pdf_bytes: bytes, company: str) -> bool:
    """Best-effort check that the downloaded PDF is actually about ``company``,
    not a same-family entity with an overlapping name - the real trap here is
    a demerged subsidiary like "ITC Hotels Limited" surfacing for a search for
    "ITC": independent-word matching would wrongly pass it (the text contains
    both "itc" and "limited"), so this instead requires the company's core
    name and its corporate suffix to appear as a CONTIGUOUS phrase - "itc
    limited"/"itc ltd" - which "itc hotels limited" does not contain (the
    matched core word is not directly followed by the suffix).

    If the query itself didn't include a suffix (e.g. "Tata Motors"), falls
    back to requiring the core name as a contiguous multi-word phrase - a
    weaker check, since there's no suffix to anchor against, but still rules
    out a completely unrelated document."""
    core, had_suffix = _core_and_suffix(company)
    if not core:
        return True  # nothing meaningful to check against - don't block on it
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = " ".join(
            (reader.pages[i].extract_text() or "") for i in range(min(VERIFY_PAGES, len(reader.pages)))
        )
    except Exception:  # noqa: BLE001 - can't verify -> don't block on it either
        return True
    haystack = _normalize_name(text)
    if not had_suffix:
        return core in haystack
    return any(f"{core} {suf}" in haystack for suf in ("limited", "ltd"))


def download_pdf(url: str, *, max_bytes: int) -> bytes:
    try:
        resp = requests.get(
            url, timeout=DOWNLOAD_TIMEOUT, stream=True, headers={"User-Agent": _USER_AGENT}
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(f"could not download {url}: {exc}") from exc

    content_type = resp.headers.get("content-type", "")
    if "pdf" not in content_type.lower() and not _looks_like_pdf_url(url):
        raise FetchError(f"that URL did not return a PDF (content-type: {content_type or 'unknown'}).")

    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=1 << 16):
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f"file exceeds the {max_bytes / 1e6:.0f}MB limit.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content.startswith(_PDF_MAGIC):
        raise FetchError("the downloaded file is not a valid PDF (missing %PDF header).")
    return content


MAX_VERIFY_ATTEMPTS = 3  # how many ranked candidates to download+check before giving up


def fetch_filing_pdf(company: str, fiscal_year: str | None, *, max_bytes: int) -> tuple[bytes, dict]:
    """Search the web for a downloadable annual-report PDF, download it, and
    verify it's actually about ``company`` before returning it - tries up to
    MAX_VERIFY_ATTEMPTS ranked candidates in order, since the top-ranked one
    can still turn out to be a wrong-company match (see verify_company_match).

    Returns ``(content_bytes, meta)`` where ``meta`` is the winning search hit
    (``url``/``title``/``query``) - kept for transparency (stored as
    ``filing_upload_jobs.source_url``, so a user can see exactly where an
    auto-fetched filing came from).
    """
    candidates = _ranked_candidates(company, fiscal_year)
    last_err: FetchError | None = None
    for hit in candidates[:MAX_VERIFY_ATTEMPTS]:
        try:
            content = download_pdf(hit["url"], max_bytes=max_bytes)
        except FetchError as exc:
            last_err = exc
            continue
        if verify_company_match(content, company):
            return content, hit
        last_err = FetchError(
            f"downloaded a PDF ({hit['url']}) but it doesn't appear to mention "
            f"{company!r} - likely the wrong document. Try the manual upload instead."
        )
    raise last_err or FetchError(f"couldn't find a verified PDF for {company!r}.")
