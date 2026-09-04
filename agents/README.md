# agents/

LangGraph specialist agents. Each wraps **one** MCP server and answers questions
in its domain. Built to run standalone now; each will become a node in the
Planner's graph later.

## Which LLM does what (a deliberate split)

| layer | provider / model | why |
|---|---|---|
| **Agent reasoning** — ReAct tool-selection loop + result synthesis | **Groq** — `openai/gpt-oss-120b`, fallbacks `qwen/qwen3.8-27b`, `openai/gpt-oss-20b` | Each agent query burns 3–5 LLM calls, and there will be several agents. Gemini's free-tier *generate* quota is **~20 requests/day/model** — it dried up during a single afternoon of development. Groq's free tier is **~1,000 requests/day/model** (its ~8k tokens/min cap is the real limit, and the shared limiter paces for it). Fast, too: ~1 s/call. |
| **News sentiment** (`research_mcp.get_sentiment`) | **Gemini** — `gemini-3-flash-preview` chain | Structured-output classification over short text; low call volume (1–2 per `get_sentiment`). Gemini's ~20/day is tolerable here, and its structured-output mode is convenient. Not worth moving. |
| **Filing embeddings** (`filings_rag_mcp`) | **Gemini** — `gemini-embedding-001` (768-dim) | Groq does not offer an embedding API. This has to be Gemini (or a local model, which was deliberately rejected — see that server's README). |

`llama-3.3-70b-versatile` — the obvious "big open model on Groq" — **was retired**
from this account's model list (Groq's lineup rotates). `openai/gpt-oss-120b` is
the current large general reasoner; verified tool-calling works.

**All three go through `shared/llm_rate_limiter.py`** — one cross-process SQLite
ledger, separate buckets per provider+model (`groq:openai/gpt-oss-120b`,
`generate:gemini-3-flash-preview`, `embed`). Nothing in the codebase calls a
hosted LLM outside the limiter's awareness. Quota profiles it enforces
(free tier, 2026-09, re-verify — these drift):

| bucket | per minute | per day |
|---|---|---|
| `groq:*` | ~27 req / **~7.5k tokens** (binding) | ~950 req |
| `generate:*` (Gemini) | ~5 req | **~20 req** (binding) |
| `embed` (Gemini) | 100 req / 30k tokens | **1,000 req** (binding) |

## `market_data_agent.py` — Market Data Agent

Given a natural-language question about a listed Indian company's market data, it
decides which of `market-data-mcp`'s 4 tools to call (often more than one), calls
them, and returns a structured result for a future Synthesis Agent plus a
human-readable summary.

### How it's wired (the architecture rules, followed on purpose)

| concern | choice |
|---|---|
| **MCP** | Spawns `mcp_servers/market_data_mcp/server.py` as a subprocess and talks to it as an **MCP stdio client** (`mcp.client.Client` + `StdioServerParameters`). It does **not** import `market_data.py`. The Planner will connect the same way. |
| **MCP → LangChain** | `client.list_tools()` → each MCP tool's JSON `input_schema` is handed straight to a `StructuredTool` (`langchain-core` 1.6 accepts a schema dict), whose coroutine calls `client.call_tool(...)` and returns the structured content. No hand-written pydantic models, no `langchain-mcp-adapters` (not in requirements, and it predates `mcp` 2.x). |
| **LLM** | Groq via `langchain-groq`, subclassed as `_RateLimitedChatGroq` so **every** call (the ReAct tool-selection loop *and* the final synthesis call) first clears `shared/llm_rate_limiter.py`. |
| **Model resilience** | The subclass runs a fallback chain (`openai/gpt-oss-120b` → `qwen/qwen3.8-27b` → `openai/gpt-oss-20b`), each its own quota bucket; when one model's shared budget trips or it 429s, it swaps `model_name` in place and retries the next — transparent to `create_react_agent`. `GROQ_AGENT_MODEL` overrides the primary. |
| **Agent graph** | `langgraph.prebuilt.create_react_agent(model, tools, prompt=...)` — the ReAct loop. A system prompt encodes the tool-selection rules ("valued vs fundamentals" → fundamentals **and** ratios; "compare X, Y, Z" → one `get_peer_comparison`, never per-peer). |
| **Provenance** | `as_of` / `fiscal_year` / `roe_source` / `last_fiscal_year_end` / `computed` / `missing` from every tool response are lifted into a top-level `provenance` block, and the full response is kept in `raw_data`. The synthesis prompt requires findings to carry that provenance inline. The agent never silently drops it. |

### Output shape

```python
{
  "query": "...",
  "ticker": "TCS.NS", "company": "Tata Consultancy Services Limited",
  "findings": ["TCS ROE is 47.74% (source: get_ratios, as_of 2026-09-04...)", ...],
  "summary": "2-4 sentence human-readable summary",
  "tools_called": ["get_fundamentals", "get_ratios"],
  "tool_calls":  [{"tool": "...", "args": {...}}, ...],
  "provenance":  {"get_ratios": {"as_of": "...", "fiscal_year": null, "computed": [], ...}},
  "raw_data":    {"get_ratios": { <full MCP response> }, ...},
  "reasoning_trace": [{"step": "tool_call", ...}, {"step": "tool_result", ...}, {"step": "agent_answer", ...}],
  "model": "openai/gpt-oss-120b"
}
```
On failure: `{"query": ..., "error": "...", "tools_called": [...], "partial_raw_data": {...}}`
(anyio/MCP `ExceptionGroup`s are unwrapped to the real leaf error).

### Use

```python
from agents.market_data_agent import run_sync, run
result = run_sync("how is TCS valued compared to its fundamentals?")
# or, inside an event loop / the Planner graph:
result = await run("compare Reliance, TCS and M&M")
```

### Test

```bash
python agents/test_market_data_agent.py
```

Drives the agent against three reasoning patterns and prints the reasoning trace
+ full structured output for each, then asserts the right tools were chosen:

| query | expected tools | verified on Groq |
|---|---|---|
| "what's Reliance's current stock price?" | `get_fundamentals` (or `get_price_history`), **not** peer comparison | ✅ |
| "how is TCS valued compared to its fundamentals?" | `get_fundamentals` **and** `get_ratios` | ✅ |
| "compare Reliance, TCS, and M&M" | exactly `get_peer_comparison`, **no** per-company tools | ✅ |

Tool-selection quality did not regress moving Gemini → Groq — the full
3-pattern run used **13 Groq requests total** and passed all 12 checks. Costs
~3–5 Groq calls per query; the script's docstring notes the token-per-minute
pacing.
