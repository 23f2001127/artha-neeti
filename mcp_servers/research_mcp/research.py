"""Core research functions: news search, LLM sentiment, corporate announcements.

Framework-agnostic, exactly like ``market_data.py`` next door: plain arguments in,
plain JSON-serialisable dicts out. A function never raises for an expected failure
(missing key, rate limit, empty results, API error) - it returns
``{"error": "<human readable message>"}`` instead. Every successful response
carries an ``as_of`` UTC timestamp.

External services
-----------------
- **Tavily** (``TAVILY_API_KEY``) - web / news search.
- **Gemini** (``GEMINI_API_KEY``) - LLM used for sentiment classification. We use
  the LLM directly rather than hosting a fine-tuned sentiment model, to keep the
  dependency footprint small. Default model ``gemini-flash-latest``; override with
  ``GEMINI_MODEL``.

Both keys are read from the project ``.env`` (real environment variables win over
the file). See ``README.md`` for the honest list of what these approximations do
and do not guarantee.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load the project .env deterministically (this file is mcp_servers/research_mcp/research.py,
# so the repo root is two levels up). override=False -> a real env var still wins.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)

# gemini-2.5-flash is now 404 for new API keys; gemini-flash-latest is the alias
# but gets overloaded (503) at times, so we try a small chain.
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
# Fallbacks live in different free-tier quota buckets, so a 429 on one is not a
# 429 on the next. gemini-flash-latest's *daily* free quota is small (~20/day) -
# keep it last.
_GEMINI_FALLBACK_MODELS = ("gemini-flash-lite-latest", "gemini-flash-latest")

# keywords that mark a result as announcement-like (used to rank / flag, not filter)
_ANNOUNCEMENT_KEYWORDS = (
    "result", "earnings", "dividend", "board meeting", "record date", "buyback",
    "bonus", "rights issue", "stock split", "agm", "egm", "acquisition", "merger",
    "demerger", "investor presentation", "filing", "board approved", "board approves",
    "profit", "revenue", "guidance", "order win", "contract win", "fundraise",
    "preferential", "qip", "credit rating",
)

# Ticker -> full company name, for building good search queries. Covers the 10
# companies whose filings are in data/filings/ plus a few obvious peers. Anything
# not listed falls back to the raw string the caller passed.
_KNOWN_NAMES: dict[str, str] = {
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
    "SBIN": "State Bank of India",
    "ITC": "ITC Limited",
    "WIPRO": "Wipro",
}

# Ticker -> lowercased strings that mean "this article is about THIS company".
# Deliberately specific: bare "mahindra" matches Tech Mahindra / Mahindra Finance,
# so M&M needs the full form. Used to tell on-entity announcements apart from
# same-theme news about group companies or peers.
_KNOWN_ALIASES: dict[str, tuple[str, ...]] = {
    "RELIANCE": ("reliance industries", "reliance ind", "ril"),
    "TCS": ("tata consultancy", "tcs"),
    "M&M": ("mahindra & mahindra", "mahindra and mahindra", "m&m", "m & m"),
    "HDFCBANK": ("hdfc bank", "hdfcbank"),
    "ICICIBANK": ("icici bank", "icicibank"),
    "INFY": ("infosys",),
    "LT": ("larsen & toubro", "larsen and toubro", "l&t"),
    "BHARTIARTL": ("bharti airtel", "airtel"),
    "HINDUNILVR": ("hindustan unilever", "hul"),
    "SUNPHARMA": ("sun pharma", "sun pharmaceutical"),
    "SBIN": ("state bank of india", "sbi"),
    "ITC": ("itc",),
    "WIPRO": ("wipro",),
}

# Separately-listed group companies whose names contain a parent alias. If a
# result is ONLY about one of these, an alias match is a false positive. Regexes,
# matched against title+snippet (lowercased).
_GROUP_COMPANY_PATTERNS: dict[str, tuple[str, ...]] = {
    "M&M": (
        r"mahindra\s*(?:&|and)\s*mahindra\s+financial",
        r"m&m\s+financial",
        r"mahindra\s+financial\s+services",
        r"mahindra\s+finance\b",
        r"\bmmfsl\b",
        r"tech\s+mahindra",
        r"mahindra\s+lifespace",
        r"mahindra\s+logistics",
        r"mahindra\s+holidays",
        r"club\s+mahindra",
        r"sml\s+mahindra",
    ),
    "LT": (r"lt\s*foods", r"l&t\s+finance", r"lt\s+technology", r"ltimindtree"),
    "RELIANCE": (r"reliance\s+power", r"reliance\s+infra", r"reliance\s+capital",
                 r"reliance\s+communications", r"reliance,?\s+inc", r"reliance\s+worldwide"),
}

_SENTIMENT_LABELS = ("positive", "neutral", "negative")


class ResearchError(Exception):
    """Raised internally for an expected failure; caught at the tool boundary."""


# --------------------------------------------------------------------------- #
# lazy clients
# --------------------------------------------------------------------------- #
_tavily_client: Any = None
_gemini_client: Any = None


def _tavily():
    global _tavily_client
    if _tavily_client is None:
        key = os.environ.get("TAVILY_API_KEY")
        if not key:
            raise ResearchError(
                "TAVILY_API_KEY is not set (checked the environment and the project .env)."
            )
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover
            raise ResearchError(f"tavily-python is not installed: {exc}") from exc
        _tavily_client = TavilyClient(api_key=key)
    return _tavily_client


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ResearchError(
                "GEMINI_API_KEY is not set (checked the environment and the project .env)."
            )
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise ResearchError(f"google-genai is not installed: {exc}") from exc
        _gemini_client = genai.Client(api_key=key)
    return _gemini_client


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_symbol(ticker_or_name: str) -> str:
    """Strip an NSE/BSE suffix and surrounding whitespace; keep the rest verbatim."""
    s = str(ticker_or_name or "").strip()
    for suffix in (".NS", ".BO", ".ns", ".bo"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.strip()


def _resolve_name(ticker_or_name: str) -> str:
    """Best-effort ticker -> company name using the small built-in map."""
    cleaned = _clean_symbol(ticker_or_name)
    return _KNOWN_NAMES.get(cleaned.upper(), cleaned)


def _snippet(text: Any, limit: int = 300) -> str | None:
    if not text:
        return None
    collapsed = " ".join(str(text).split())
    return collapsed[:limit] + ("..." if len(collapsed) > limit else "")


def _clamp(value: int, low: int, high: int, default: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _format_results(raw_results: list[dict]) -> list[dict]:
    out = []
    for r in raw_results or []:
        out.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "published_date": r.get("published_date"),
                "source_score": round(r["score"], 4) if isinstance(r.get("score"), (int, float)) else None,
                "snippet": _snippet(r.get("content")),
            }
        )
    return out


def _tavily_search(
    query: str, *, max_results: int, days: int | None = None, topic: str = "news"
) -> list[dict]:
    """Run one Tavily search, translating its errors into ResearchError."""
    try:
        import tavily.errors as tv_errors
    except ImportError:  # pragma: no cover
        tv_errors = None

    client = _tavily()
    kwargs: dict[str, Any] = {
        "query": query,
        "topic": topic,
        "max_results": max_results,
        "search_depth": "basic",
        "country": "india",  # bias toward Indian sources; Tavily ignores it on some tiers
    }
    if days is not None and topic == "news":
        kwargs["days"] = days

    try:
        resp = client.search(**kwargs)
    except Exception as exc:  # noqa: BLE001 - normalise every failure to ResearchError
        name = type(exc).__name__
        if tv_errors is not None:
            if isinstance(exc, (tv_errors.UsageLimitExceededError, tv_errors.TavilyKeylessLimitError)):
                raise ResearchError(f"Tavily rate / usage limit reached: {exc}") from exc
            if isinstance(exc, (tv_errors.InvalidAPIKeyError, tv_errors.MissingAPIKeyError)):
                raise ResearchError("Tavily rejected or is missing the API key.") from exc
            if isinstance(exc, tv_errors.TimeoutError):
                raise ResearchError("Tavily request timed out.") from exc
            if isinstance(exc, tv_errors.BadRequestError):
                raise ResearchError(f"Tavily rejected the query: {exc}") from exc
        raise ResearchError(f"Tavily search failed ({name}): {exc}") from exc

    return resp.get("results", []) if isinstance(resp, dict) else []


def _retry_delay_seconds(err: Exception, default: float) -> float:
    """Pull the server-suggested retry delay out of a Gemini error, capped."""
    match = re.search(r"retry(?:Delay|\s+in)['\":\s]+([0-9.]+)s", str(err))
    if match:
        try:
            return min(float(match.group(1)), 30.0)
        except ValueError:
            pass
    return default


def _gemini_json(prompt: str, schema: type, *, max_attempts: int = 2) -> tuple[Any, str]:
    """One structured-output Gemini call.

    Retries transient 5xx and 429 (rate-limit / quota) errors with a bounded
    backoff, and falls through a small chain of models so a per-model quota does
    not sink the call. A 429 on the LAST model is retried once after the
    server-suggested delay.
    """
    try:
        from google.genai import errors as genai_errors
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise ResearchError(f"google-genai is not installed: {exc}") from exc

    client = _gemini()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.0,
        # we only want structured JSON back, never tool calls - disabling this also
        # silences google-genai's "direct use of AFC is not recommended" banner
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    primary = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    models_to_try = [primary] + [m for m in _GEMINI_FALLBACK_MODELS if m != primary]

    last_err: Exception | None = None
    for model_idx, model in enumerate(models_to_try):
        is_last_model = model_idx == len(models_to_try) - 1
        for attempt in range(max_attempts):
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=config)
                parsed = getattr(resp, "parsed", None)
                if parsed is None:
                    parsed = schema.model_validate_json(resp.text)
                return parsed, model
            except genai_errors.ServerError as exc:  # 5xx - transient
                last_err = exc
                if attempt < max_attempts - 1:
                    time.sleep(2.0 * (attempt + 1))
            except genai_errors.ClientError as exc:  # 4xx
                last_err = exc
                text = str(exc)
                if "RESOURCE_EXHAUSTED" in text or " 429" in text:
                    # quota / rate limit: try the next model right away; only wait
                    # (once) if this was the last model we have.
                    if is_last_model and attempt < max_attempts - 1:
                        time.sleep(_retry_delay_seconds(exc, 15.0))
                        continue
                    break
                if "NOT_FOUND" in text or "not found" in text.lower():
                    break  # bad model id - fall through to the next one
                raise ResearchError(f"Gemini rejected the request: {exc}") from exc
            except (json.JSONDecodeError, ValueError) as exc:  # unparseable output
                last_err = exc
                time.sleep(1.0)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(1.0)

    raise ResearchError(
        f"Gemini call failed (tried {', '.join(models_to_try)}): {last_err}"
    )


def _normalise_label(label: Any) -> str:
    text = str(label or "").strip().lower()
    for candidate in _SENTIMENT_LABELS:
        if candidate in text:
            return candidate
    return "neutral"


def _clamp_score(score: Any) -> float | None:
    try:
        return round(max(0.0, min(1.0, float(score))), 3)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# tool implementations
# --------------------------------------------------------------------------- #
def search_news(query: str, max_results: int = 10) -> dict:
    """General news search via Tavily for a company or topic."""
    if not query or not str(query).strip():
        return {"error": "query is empty."}
    n = _clamp(max_results, 1, 20, 10)

    try:
        raw = _tavily_search(str(query).strip(), max_results=n)
    except ResearchError as exc:
        return {"error": str(exc)}

    results = _format_results(raw)
    return {
        "query": str(query).strip(),
        "count": len(results),
        "results": results,
        "as_of": _now_utc_iso(),
        "note": None
        if results
        else "Tavily returned no results for this query (not an error - try broadening it).",
    }


def get_company_news(ticker_or_name: str, days_back: int = 30) -> dict:
    """News scoped to one company over a recent window (built on search_news)."""
    if not ticker_or_name or not str(ticker_or_name).strip():
        return {"error": "ticker_or_name is empty."}
    days = _clamp(days_back, 1, 365, 30)
    name = _resolve_name(ticker_or_name)
    resolved_from_map = _clean_symbol(ticker_or_name).upper() in _KNOWN_NAMES

    # Quoted name + 2 plain keywords. A long "(a OR b OR c ...)" query makes
    # Tavily's semantic news search drift to same-theme stories about OTHER
    # companies (verified: it returned ReNew / Praj / Alfa Ica for a Reliance query).
    query = f'"{name}" stock news'
    try:
        raw = _tavily_search(query, max_results=15, days=days)
    except ResearchError as exc:
        return {"error": str(exc)}

    results = _format_results(raw)
    on_company = _annotate_company(results, _company_aliases(ticker_or_name, name))
    return {
        "input": str(ticker_or_name).strip(),
        "company": name,
        "name_resolved_from_ticker_map": resolved_from_map,
        "days_back": days,
        "query": query,
        "count": len(results),
        "on_company_count": on_company,
        "results": results,
        "as_of": _now_utc_iso(),
        "note": (
            f"No news found for '{name}' in the last {days} days."
            if not results
            else f"{on_company}/{len(results)} results mention the company by name "
            f"(mentions_company); the rest may be about a group company or peer - "
            f"results are NOT dropped, only flagged."
        ),
    }


def get_sentiment(text_or_ticker: str) -> dict:
    """Sentiment classification via the Gemini LLM.

    Dual-mode (see README for the rationale):
    - If the input looks like a ticker or short company name, recent news for that
      company is fetched and scored in aggregate (overall + per-article).
    - Otherwise the input is treated as a piece of text and scored directly.
    """
    if not text_or_ticker or not str(text_or_ticker).strip():
        return {"error": "text_or_ticker is empty."}

    raw_input = str(text_or_ticker).strip()
    if _looks_like_ticker_or_name(raw_input):
        return _sentiment_for_company(raw_input)
    return _sentiment_for_text(raw_input)


def get_corporate_announcements(ticker: str, days_back: int = 30) -> dict:
    """Recent corporate-announcement-style news for a company.

    IMPORTANT: this is a Tavily news search scoped with announcement keywords, NOT
    a direct feed from the NSE/BSE official corporate-announcements system. It is a
    pragmatic v1 approximation - see the 'disclaimer' field and the README.
    """
    if not ticker or not str(ticker).strip():
        return {"error": "ticker is empty."}
    days = _clamp(days_back, 1, 365, 30)
    name = _resolve_name(ticker)

    # "<name> stock news" is the entity anchor that keeps Tavily on-company (a
    # bare "<name> results earnings dividend" query drifted to Reliance Worldwide /
    # Strathcona / Rain Industries on one run); the trailing keywords lean it
    # toward announcements. Announcement filtering is done below, not in the query.
    query = f'"{name}" stock news results earnings dividend'
    try:
        raw = _tavily_search(query, max_results=20, days=days)
    except ResearchError as exc:
        return {"error": str(exc)}

    results = _format_results(raw)
    on_company = _annotate_company(results, _company_aliases(ticker, name))
    for item in results:
        matched = _announcement_keywords_in(item)
        item["matched_keywords"] = matched
        # "likely an announcement BY this company" needs both signals
        item["likely_announcement"] = bool(matched) and item["mentions_company"]
    # on-entity announcements first, then on-entity anything, then by relevance
    results.sort(
        key=lambda r: (
            r["likely_announcement"],
            r["mentions_company"],
            bool(r["matched_keywords"]),
            r.get("source_score") or 0.0,
        ),
        reverse=True,
    )
    likely = [r for r in results if r["likely_announcement"]]

    return {
        "input": str(ticker).strip(),
        "company": name,
        "days_back": days,
        "query": query,
        "count": len(results),
        "likely_announcement_count": len(likely),
        "on_company_count": on_company,
        "announcements": results,
        "as_of": _now_utc_iso(),
        "disclaimer": (
            "Search-based approximation. These items come from Tavily news coverage. "
            "Each is flagged 'mentions_company' (an alias of the company appears in "
            "the text) and 'matched_keywords' (announcement vocabulary); "
            "'likely_announcement' is true only when BOTH hold, and those sort "
            "first. This is NOT the NSE/BSE official corporate-announcement feed - "
            "expect missed filings, peer/group-company bleed-through in the "
            "un-flagged tail, and 'published_date' being the news publication date, "
            "not the exchange filing timestamp."
        ),
        "note": None if results else f"No announcement-style news for '{name}' in the last {days} days.",
    }


def _announcement_keywords_in(item: dict) -> list[str]:
    """Which announcement keywords appear in a result's title + snippet."""
    haystack = f"{item.get('title') or ''} {item.get('snippet') or ''}".lower()
    return [kw for kw in _ANNOUNCEMENT_KEYWORDS if kw in haystack]


def _company_aliases(ticker_or_name: str, resolved_name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(aliases, group_company_patterns)`` for entity matching.

    ``aliases`` are lowercased strings that indicate an article is about this
    company; ``group_company_patterns`` are regexes for separately-listed group
    companies whose names contain an alias (a match there is a false positive
    unless the parent is *also* named).
    """
    key = _clean_symbol(ticker_or_name).upper()
    if key in _KNOWN_ALIASES:
        return _KNOWN_ALIASES[key], _GROUP_COMPANY_PATTERNS.get(key, ())
    # Fallback for unmapped names: the full name and its first two words.
    name = resolved_name.lower().strip()
    parts = name.split()
    candidates = {name}
    if len(parts) >= 2:
        candidates.add(" ".join(parts[:2]))
    return tuple(c for c in candidates if len(c) >= 4), ()


def _mentions_company(item: dict, aliases: tuple[tuple[str, ...], tuple[str, ...]]) -> bool:
    """True if the company (not just a same-named group company) is named in the text.

    Strategy: blank out any separately-listed group-company names first, then look
    for an alias in what remains. So "Tech Mahindra Q4 results" -> False for M&M,
    but "M&M and Tech Mahindra both reported" -> True. The word-boundary check
    stops "ril" matching "april" while still allowing "m&m", "l&t", "hul".
    """
    alias_list, group_patterns = aliases
    haystack = f"{item.get('title') or ''} {item.get('snippet') or ''}".lower()
    for pat in group_patterns:
        haystack = re.sub(pat, " ~~ ", haystack)
    for alias in alias_list:
        a = alias.strip()
        if a and re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", haystack):
            return True
    return False


def _annotate_company(
    results: list[dict], aliases: tuple[tuple[str, ...], tuple[str, ...]]
) -> int:
    """Add a ``mentions_company`` bool to each result; return how many are on-entity.

    Shared by every company-scoped tool so an agent that calls all three gets the
    same signal. NOTE: this only *flags* - results are not dropped. A tight alias
    check means e.g. "Tech Mahindra" / "Mahindra Finance" news comes back
    ``mentions_company: false`` for an M&M query. The flag is best-effort: a story
    that discusses the company only in its body (not the title/snippet) is missed.
    """
    on_company = 0
    for item in results:
        hit = _mentions_company(item, aliases)
        item["mentions_company"] = hit
        on_company += hit
    return on_company


# --------------------------------------------------------------------------- #
# sentiment internals
# --------------------------------------------------------------------------- #
def _looks_like_ticker_or_name(text: str) -> bool:
    """Heuristic: short, punctuation-free strings are treated as a ticker / name."""
    s = text.strip()
    if s.lower().endswith((".ns", ".bo")):
        return True
    if _clean_symbol(s).upper() in _KNOWN_NAMES:
        return True
    if len(s) > 48:
        return False
    if any(p in s for p in (".", "!", "?", "\n", ":", ";")):
        return False
    return len(s.split()) <= 5


def _sentiment_for_text(text: str) -> dict:
    from pydantic import BaseModel

    class _TextSentiment(BaseModel):
        label: str
        score: float
        rationale: str

    prompt = (
        "You are a financial-news sentiment classifier for an equity investor.\n"
        "Classify the sentiment the following text expresses toward the company / "
        "asset it is about. Respond as JSON.\n"
        "- label: exactly one of positive, neutral, negative\n"
        "- score: your confidence from 0.0 to 1.0\n"
        "- rationale: at most two sentences, concrete\n\n"
        f"TEXT:\n{text[:6000]}"
    )
    try:
        parsed, model = _gemini_json(prompt, _TextSentiment)
    except ResearchError as exc:
        return {"error": str(exc)}

    return {
        "mode": "text",
        "input_kind": "free_text",
        "label": _normalise_label(parsed.label),
        "score": _clamp_score(parsed.score),
        "rationale": parsed.rationale,
        "model": model,
        "as_of": _now_utc_iso(),
        "note": "score is the model's self-reported confidence, not a calibrated probability.",
    }


def _sentiment_for_company(ticker_or_name: str) -> dict:
    from pydantic import BaseModel

    name = _resolve_name(ticker_or_name)
    query = f'"{name}" stock news'  # see get_company_news for why not an OR-list
    try:
        raw = _tavily_search(query, max_results=10, days=30)
    except ResearchError as exc:
        return {"error": str(exc)}

    articles = _format_results(raw)
    if not articles:
        return {
            "error": f"No recent news found for '{name}' to score sentiment over "
            f"(searched the last 30 days)."
        }

    on_company = _annotate_company(articles, _company_aliases(ticker_or_name, name))

    class _ArticleSentiment(BaseModel):
        index: int
        label: str
        score: float

    class _AggregateSentiment(BaseModel):
        overall_label: str
        overall_score: float
        rationale: str
        articles: list[_ArticleSentiment]

    off_entity_tag = f" (about a related group company, not {name} itself)"
    listing = "\n".join(
        f"[{i}]{'' if a['mentions_company'] else off_entity_tag} "
        f"{a['title']} - {a.get('snippet') or ''}"[:540]
        for i, a in enumerate(articles)
    )
    prompt = (
        "You are a financial-news sentiment classifier for an equity investor "
        f"analysing {name}.\n"
        "For EACH numbered article below, give a sentiment (positive/neutral/negative) "
        "and a 0.0-1.0 confidence. Then give an overall assessment.\n"
        "Weight material, company-specific news (results, guidance, regulatory action, "
        "large deals) above generic market-movement chatter. Articles marked "
        f"'(about a related group company, not {name} itself)' should be noted but "
        "must NOT drive the overall label. Respond as JSON matching the schema: "
        "overall_label, overall_score, rationale (<= 3 sentences), and articles "
        "(one {index,label,score} per article).\n\n"
        f"ARTICLES:\n{listing}"
    )
    try:
        parsed, model = _gemini_json(prompt, _AggregateSentiment)
    except ResearchError as exc:
        return {"error": str(exc)}

    by_index = {a.index: a for a in parsed.articles}
    scored_articles = []
    breakdown = {"positive": 0, "neutral": 0, "negative": 0}
    breakdown_on_company = {"positive": 0, "neutral": 0, "negative": 0}
    for i, art in enumerate(articles):
        a = by_index.get(i)
        label = _normalise_label(a.label) if a else "neutral"
        breakdown[label] += 1
        if art["mentions_company"]:
            breakdown_on_company[label] += 1
        scored_articles.append(
            {
                "index": i,
                "title": art["title"],
                "url": art["url"],
                "published_date": art["published_date"],
                "mentions_company": art["mentions_company"],
                "label": label,
                "score": _clamp_score(a.score) if a else None,
            }
        )

    return {
        "mode": "aggregate",
        "input_kind": "ticker_or_name",
        "company": name,
        "query": query,
        "article_count": len(articles),
        "on_company_count": on_company,
        "overall": {
            "label": _normalise_label(parsed.overall_label),
            "score": _clamp_score(parsed.overall_score),
            "rationale": parsed.rationale,
        },
        "breakdown": breakdown,
        "breakdown_on_company": breakdown_on_company,
        "articles": scored_articles,
        "model": model,
        "as_of": _now_utc_iso(),
        "note": "Aggregate sentiment over the recent-news sample above; scores are "
        "the model's self-reported confidence, not calibrated probabilities. The "
        "sample is whatever Tavily surfaced, not exhaustive. 'breakdown' counts all "
        f"articles; 'breakdown_on_company' counts only the {on_company} that mention "
        f"{name} by name - off-entity items were flagged to the model so they would "
        "not drive the overall label.",
    }
