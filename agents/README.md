# agents/

LangGraph specialist agents. Each wraps **one** MCP server and answers questions
in its domain. Built to run standalone now; each will become a node in the
Planner's graph later.

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
| **LLM** | Gemini via `langchain-google-genai`, subclassed as `_RateLimitedChatGoogle` so **every** call (the ReAct tool-selection loop *and* the final synthesis call) first clears `shared/gemini_rate_limiter.py`. Nothing here touches Gemini outside its awareness. |
| **Model resilience** | Free-tier flash models have ~20 requests/day each. The model runs a fallback chain (`gemini-3-flash-preview` → `gemini-flash-lite-latest` → `gemini-flash-latest`); when one model's shared budget trips or it 429s, the subclass rotates to the next transparently. `GEMINI_AGENT_MODEL` overrides the primary. |
| **Agent graph** | `langgraph.prebuilt.create_react_agent(model, tools, prompt=...)` — the ReAct loop. A system prompt tells it the tool-selection rules ("valued vs fundamentals" → fundamentals **and** ratios; "compare X, Y, Z" → one `get_peer_comparison`, never per-peer). |
| **Provenance** | `as_of` / `fiscal_year` / `roe_source` / `last_fiscal_year_end` / `computed` / `missing` from every tool response are lifted into a top-level `provenance` block, and the full response is kept in `raw_data`. The synthesis prompt requires findings to carry that provenance inline. The agent never silently drops it. |

### Output shape

```python
{
  "query": "...",
  "ticker": "TCS.NS", "company": "Tata Consultancy Services Limited",
  "findings": ["TCS ROE is 47.74% (source: get_ratios, as of 2026-09-04...)", ...],
  "summary": "2-4 sentence human-readable summary",
  "tools_called": ["get_fundamentals", "get_ratios"],
  "tool_calls":  [{"tool": "...", "args": {...}}, ...],
  "provenance":  {"get_ratios": {"as_of": "...", "fiscal_year": null, "computed": [], ...}},
  "raw_data":    {"get_ratios": { <full MCP response> }, ...},
  "reasoning_trace": [{"step": "tool_call", ...}, {"step": "tool_result", ...}, {"step": "agent_answer", ...}],
  "model": "gemini-3-flash-preview"
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

| query | expected tools |
|---|---|
| "what's Reliance's current stock price?" | `get_fundamentals` (or `get_price_history`), **not** peer comparison |
| "how is TCS valued compared to its fundamentals?" | `get_fundamentals` **and** `get_ratios` |
| "compare Reliance, TCS, and M&M" | exactly `get_peer_comparison`, **no** per-company tools |

Costs ~3–4 Gemini calls per query — see the script's docstring for the free-tier
quota env overrides.
