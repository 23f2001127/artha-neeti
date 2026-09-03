"""Gemini embedding wrapper for filings-rag-mcp.

- Model: ``gemini-embedding-001`` (see config for why).
- Output truncated to ``EMBED_DIM`` and **L2-normalised** in code (Gemini only
  pre-normalises the full 3072-dim vector; reduced dims must be normalised for
  cosine similarity to behave).
- The binding free-tier limit is **input tokens per minute** (~30k for
  ``gemini-embedding-001``), not request count. A process-wide sliding-window
  limiter keeps us under it; ingestion batches are built to a token budget, not a
  fixed item count. This quota is **shared with research-mcp's Gemini calls**.
- 429 (RESOURCE_EXHAUSTED) is retried with the server-suggested delay; a sustained
  429 surfaces as ``EmbeddingQuotaError`` so ingestion can checkpoint and stop.
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import deque
from typing import Sequence

import tiktoken

from . import config

_DOC_TASK = "RETRIEVAL_DOCUMENT"
_QUERY_TASK = "RETRIEVAL_QUERY"
_ENC = tiktoken.get_encoding("cl100k_base")


class EmbeddingError(RuntimeError):
    pass


class EmbeddingQuotaError(EmbeddingError):
    """Raised when the rate-limit retries are exhausted (likely a daily cap)."""


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
class _TokenRateLimiter:
    """Sliding 60s window over token spend; also caps requests/min."""

    def __init__(self, tokens_per_min: int, requests_per_min: int):
        self.tpm = max(1, tokens_per_min)
        self.rpm = max(1, requests_per_min)
        self._events: deque[tuple[float, int]] = deque()  # (timestamp, tokens)
        self._lock = threading.Lock()

    def acquire(self, tokens: int) -> None:
        tokens = max(1, min(tokens, self.tpm))  # a single batch can't exceed the budget
        while True:
            with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0][0] > 60.0:
                    self._events.popleft()
                used = sum(t for _, t in self._events)
                if used + tokens <= self.tpm and len(self._events) + 1 <= self.rpm:
                    self._events.append((now, tokens))
                    return
                oldest = self._events[0][0] if self._events else now
                wait = 60.0 - (now - oldest) + 0.5
            time.sleep(max(wait, 1.0))


_limiter = _TokenRateLimiter(config.EMBED_TPM, config.EMBED_RPM)


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
        _limiter.acquire(token_total)
        try:
            resp = client.models.embed_content(model=config.EMBED_MODEL, contents=texts, config=cfg)
            out = [list(e.values) for e in resp.embeddings]
            if len(out) != len(texts):
                raise EmbeddingError(f"Gemini returned {len(out)} embeddings for {len(texts)} inputs.")
            return [_normalise(v) for v in out]
        except genai_errors.ClientError as exc:
            last = exc
            if "RESOURCE_EXHAUSTED" in str(exc) or " 429" in str(exc):
                time.sleep(_retry_delay(exc, 25.0 * (attempt + 1)))
                continue
            raise EmbeddingError(f"Gemini rejected the embed request: {exc}") from exc
        except genai_errors.ServerError as exc:
            last = exc
            time.sleep(3.0 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last = exc
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
