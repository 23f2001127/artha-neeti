# shared/

Cross-cutting infrastructure used by more than one ArthaNeeti component. Not tied
to any single MCP server or agent.

Currently one module:

## `gemini_rate_limiter.py` — one quota, many processes

### The problem

`research_mcp` (sentiment via `generate_content`) and `filings_rag_mcp`
(embeddings via `embed_content`) call Gemini with the **same API key**. The
LangGraph agents will too. So there is **one account-wide quota**, but each
process was policing only its own usage with an in-memory limiter. Run the
filings ingestion and a couple of sentiment-calling agents at once and they
collectively sail past the limits — 429s, backoff storms, and (worst) the
**1,000 embeddings/day** cap burned before ingestion finishes.

### The design: a local SQLite ledger

Every Gemini request reserves a row `(bucket, timestamp, tokens, requests)` in a
small SQLite database. `acquire()` opens that DB in an `IMMEDIATE` transaction —
a real **cross-process write lock** — evaluates the sliding per-minute and
per-day windows against the ledger, and either records the reservation and
returns, or drops the lock and sleeps until the window frees.

```
process A ─┐
process B ─┼─►  .gemini_rate_limiter.db  ◄─── one IMMEDIATE txn at a time
process C ─┘        (bucket, ts, tokens, requests)
                    sliding 60s window + since-midnight-PT day window
```

### Why SQLite and not something else

| option | why not (for a local, single-machine, solo project) |
|---|---|
| **in-memory** (status quo) | can't see other processes — the entire problem |
| **Postgres** (we hold a connection) | it's a **remote** Supabase instance: ~50–150 ms per rate check, and it drags a DB dependency into `research_mcp`, which otherwise needs none. A rate check should be local and ~free. |
| **a "Gemini gateway" daemon** all callers proxy through | genuinely correct, and how you'd scale it. But it adds a long-running process to supervise, startup-ordering concerns, and an IPC layer — too much machinery for one laptop. Revisit if this ever runs distributed. |
| **JSON file + advisory locks** (`fcntl`/`msvcrt`/`filelock`) | SQLite already does atomic cross-process read-modify-write, portably, with WAL. Hand-rolling it is more code and more bugs. |

SQLite in **WAL mode on a local disk** gives true multi-process coordination,
sub-millisecond checks, survives restarts (the daily counter persists), and adds
**zero dependencies** (`sqlite3` is stdlib). The one requirement: the DB file
must be on a local filesystem, not a network share. Fine for a dev machine.

The concurrent test (`test_gemini_rate_limiter.py`) spins up 3 real subprocesses
hammering the limiter and asserts no sliding window is ever exceeded and the
daily cap stops **exactly** at the limit across processes — proving it
coordinates, not just self-limits.

### Limits (observed on the free tier, 2026-09 — re-verify, Google's quotas drift)

| bucket | per minute | per day |
|---|---|---|
| `embed` (`gemini-embedding-001`) | 100 req / 30,000 tokens | **1,000 req** ← the hard wall |
| `generate` (`gemini-3-flash-preview`) | ~5 req | not hit |
| `generate` (`gemini-flash-latest`) | — | ~20 req |

- **Each text in an `embed_content` batch is one request** against both the
  per-minute and per-day request caps. A 90-text batch spends 90.
- `embed` and `generate` are **separate quota buckets** — a big ingestion does
  not directly starve sentiment (but they compete for your attention and for the
  per-minute wall-clock).
- The default `generate` bucket is conservative. `research_mcp` passes
  `request_type="generate:<model>"` so each model in its fallback chain gets its
  own window.

Override any limit with env vars: `GEMINI_RL_<FAMILY>_RPM` / `_TPM` / `_RPD`
(family = the part before `:`). On a **paid key**, `GEMINI_RL_EMBED_RPD=100000`
effectively removes the daily wall.

DB location: `<repo>/.gemini_rate_limiter.db` (gitignored), override with
`GEMINI_RATE_LIMITER_DB`.

### Interface

```python
from shared import gemini_rate_limiter as grl

# retry-loop style (each attempt accounted for)
rid = grl.acquire(estimated_tokens=1200, request_type="embed", count=90)  # blocks
try:
    resp = client.models.embed_content(...)
except RateLimited:            # a 429 didn't spend quota
    grl.refund(rid, "embed")
    ... backoff, then re-acquire ...

# single-attempt style
with grl.reserve(est_tokens, "generate:gemini-3-flash-preview"):
    resp = client.models.generate_content(...)   # auto-refunds if the block raises

grl.snapshot()   # {bucket: {last_min_requests, last_min_tokens, today_requests, day_remaining, limits}}
grl.reset()      # wipe the ledger (tests, or "I know quota actually reset")
```

`acquire()` raises `QuotaExceededError` when the **daily** cap for the bucket is
already spent (waiting hours is not "blocking appropriately") or when `timeout`
seconds elapse waiting on the **per-minute** window. Callers turn that into their
own domain error: `research_mcp` → `{"error": ...}`, `filings_rag_mcp` →
`EmbeddingQuotaError` (so ingestion checkpoints and stops).

### What was migrated

- `filings_rag_mcp/embeddings.py` — deleted its local `_TokenRateLimiter`; the
  token/request throttle is now `grl.acquire(..., "embed", count=len(batch))`.
- `research_mcp/research.py` — `_gemini_json` now calls
  `grl.acquire(..., f"generate:{model}")` before **every** HTTP attempt (it had
  only *reactive* 429 handling before; now it's proactive too), refunding on 429.
- `filings_rag_mcp/config.py` — dropped `EMBED_TPM` / `EMBED_RPM`; those live in
  the limiter now (`GEMINI_RL_EMBED_*`). `EMBED_BATCH_TOKENS` stays (it's a
  batching concern, not a rate concern).

No local rate-limiting logic remains in either server — there is one system now.

### Testing

```bash
python shared/test_gemini_rate_limiter.py
```

Spawns real subprocesses against a throwaway ledger with tiny fake limits. No
Gemini API calls, no quota cost. ~15 s. Checks: per-minute coordination across 3
processes, the daily cap enforced across 2 processes, and single-process
`acquire`/`refund`/`snapshot`/`reserve` behaviour.
