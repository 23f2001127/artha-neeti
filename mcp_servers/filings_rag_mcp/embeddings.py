"""Gemini embedding wrapper for filings-rag-mcp.

- Model: ``gemini-embedding-001`` (see config for why).
- Output truncated to ``EMBED_DIM`` and **L2-normalised** in code (Gemini only
  pre-normalises the full 3072-dim vector; reduced dims must be normalised for
  cosine similarity to behave).
- Rate limiting is delegated to ``shared.gemini_rate_limiter`` - a cross-process
  limiter over the account-wide Gemini quota (per-minute tokens + requests, and
  the 1,000/day embedding cap). Each text in a batch is one quota request.
- 429 is retried with the server-suggested delay and the reservation is refunded;
  a sustained wall surfaces as ``EmbeddingQuotaError`` so ingestion checkpoints.
"""

from __future__ import annotations

import math
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Sequence

import tiktoken

from . import config

# Make the top-level ``shared`` package importable regardless of how this module
# is entered (``python -m ...ingest``, the MCP server, a test).
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from shared import gemini_rate_limiter as grl  # noqa: E402

_DOC_TASK = "RETRIEVAL_DOCUMENT"
_QUERY_TASK = "RETRIEVAL_QUERY"
_ENC = tiktoken.get_encoding("cl100k_base")


class EmbeddingError(RuntimeError):
    pass


class EmbeddingQuotaError(EmbeddingError):
    """Raised when the shared limiter reports the quota wall (checkpoint & stop)."""


# --------------------------------------------------------------------------- #
_client = None
_client_lock = threading.Lock()


def _genai_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                key = os.environ.get("GEMINI_API_KEY")
                if not key:
                    raise EmbeddingError(
                        "GEMINI_API_KEY is not set (checked the environment and the project .env)."
                    )
                from google import genai

                _client = genai.Client(api_key=key)
    return _client


# --------------------------------------------------------------------------- #
def _normalise(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else list(vec)


def _retry_delay(err: Exception, default: float) -> float:
    m = re.search(r"retry(?:Delay)?['\":\s]+([0-9.]+)s", str(err))
    if m:
        try:
            return min(float(m.group(1)) + 1.0, 55.0)
        except ValueError:
            pass
    return default


def _token_batches(texts: list[str], budget: int) -> list[tuple[list[str], list[int], int]]:
    """Split texts into batches under `budget` tokens and 100 items."""
    batches: list[tuple[list[str], list[int], int]] = []
    cur: list[str] = []
    cur_tok: list[int] = []
    cur_total = 0
    for t in texts:
        n = len(_ENC.encode(t))
        if cur and (cur_total + n > budget or len(cur) >= 100):
            batches.append((cur, cur_tok, cur_total))
            cur, cur_tok, cur_total = [], [], 0
        cur.append(t)
        cur_tok.append(n)
        cur_total += n
    if cur:
        batches.append((cur, cur_tok, cur_total))
    return batches


def _embed_call(texts: list[str], token_total: int, task_type: str) -> list[list[float]]:
    from google.genai import errors as genai_errors
    from google.genai import types

    client = _genai_client()
    cfg = types.EmbedContentConfig(task_type=task_type, output_dimensionality=config.EMBED_DIM)

    attempts = 6
    last: Exception | None = None
    for attempt in range(attempts):
        # each text in the batch is one quota request; wait generously - ingestion
        # is a long job and it's fine to sit on the per-minute window.
        try:
            rid = grl.acquire(token_total, "embed", count=len(texts), timeout=900.0)
        except grl.QuotaExceededError as exc:
            raise EmbeddingQuotaError(str(exc)) from exc

        try:
            resp = client.models.embed_content(model=config.EMBED_MODEL, contents=texts, config=cfg)
            out = [list(e.values) for e in resp.embeddings]
            if len(out) != len(texts):
                raise EmbeddingError(f"Gemini returned {len(out)} embeddings for {len(texts)} inputs.")
            return [_normalise(v) for v in out]
        except genai_errors.ClientError as exc:
            last = exc
            grl.refund(rid, "embed")  # a rejected request did not consume quota
            if "RESOURCE_EXHAUSTED" in str(exc) or " 429" in str(exc):
                time.sleep(_retry_delay(exc, 25.0 * (attempt + 1)))
                continue
            raise EmbeddingError(f"Gemini rejected the embed request: {exc}") from exc
        except genai_errors.ServerError as exc:
            last = exc
            grl.refund(rid, "embed")
            time.sleep(3.0 * (attempt + 1))
        except EmbeddingError:
            grl.refund(rid, "embed")
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            grl.refund(rid, "embed")
            time.sleep(2.0)

    raise EmbeddingQuotaError(
        f"Embedding failed after {attempts} attempts (rate/quota wall): {last}"
    )


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed chunk texts, batched under the per-minute token budget."""
    out: list[list[float]] = []
    for batch, _tok, total in _token_batches(texts, config.EMBED_BATCH_TOKENS):
        out.extend(_embed_call(batch, total, _DOC_TASK))
    return out


def embed_query(text: str) -> list[float]:
    n = len(_ENC.encode(text))
    return _embed_call([text], n, _QUERY_TASK)[0]
