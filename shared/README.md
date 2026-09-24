# shared

Infrastructure used by more than one component.

## `llm_rate_limiter.py`

Each LLM provider is used with a single API key, so the API process, the three
MCP server subprocesses and the ingestion script all draw on one account quota
per provider. The limiter gives them a shared view of that quota.

### How it works

Every request reserves a row `(bucket, timestamp, tokens, requests)` in a local
SQLite database in WAL mode. `acquire()` opens an `IMMEDIATE` transaction, which
serializes the check across processes, evaluates the sliding per-minute window
and the per-day window, and either records the reservation or waits until the
window has room.

```
API process ─────┐
MCP servers ─────┼──►  .llm_rate_limiter.db   (one IMMEDIATE transaction at a time)
ingestion job ───┘
```

SQLite keeps each check local and sub-millisecond, persists daily counts across
restarts and needs no extra dependency. A remote database would add a network
round trip to every LLM call. The file must be on a local disk.

### Default limits

| Bucket | Per minute | Per day | Used by |
| --- | --- | --- | --- |
| `embed` | 100 requests, 30k tokens | 1,000 requests | Annual-report indexing and retrieval |
| `generate:<model>` | 6 requests | 20 requests | News sentiment (Gemini) |
| `groq` | 27 requests, 5k tokens | 950 requests, 350k tokens | Agent reasoning |

- Gemini models each have their own window (`generate:<model>`), so falling
  back to another model adds headroom.
- Groq limits by account, so one `groq` bucket covers every model in the chain.
  Its sustained rate is set below the advertised 8k tokens per minute because
  higher rates still draw 429s. The daily token wall is an estimate of an
  undocumented limit.
- Each text in an embedding batch counts as one request: pass `count=len(batch)`.

Override any limit with `LLM_RL_<FAMILY>_RPM`, `_TPM`, `_RPD` or `_TPD` (family
is the part before `:`). On paid keys, `LLM_RL_GROQ_TPD=0` removes the daily
token wall. The ledger lives at `<repo>/.llm_rate_limiter.db`, or at
`LLM_RATE_LIMITER_DB`.

### Interface

```python
from shared import llm_rate_limiter as rl

rid = rl.acquire(estimated_tokens=1200, request_type="embed", count=90)  # blocks
try:
    response = client.models.embed_content(...)
except RateLimitError:
    rl.refund(rid, "embed")        # a rejected call spent no quota

with rl.reserve(est_tokens, "generate:gemini-3-flash-preview"):
    response = client.models.generate_content(...)   # refunded if this raises

rl.snapshot()   # usage and remaining allowance per bucket (served at GET /status)
```

`acquire()` raises `QuotaExceededError` when a bucket's daily allowance is spent
or the wait for the per-minute window exceeds `timeout`. Callers translate it:
research-mcp returns `{"error": ...}`, indexing raises `EmbeddingQuotaError` and
stops at a checkpoint, and agents report the source as unavailable.

### Tests

`tests/unit/test_llm_rate_limiter.py` runs real worker processes against a
temporary ledger with small limits and a shortened window. It checks that the
per-minute window holds across processes and that the daily cap stops at the
exact limit. No provider calls are made.
