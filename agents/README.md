# agents/

The specialist agents. The first three each wrap **one** MCP server and answer
questions in its domain; the fourth (Synthesis) takes the other three's outputs
and merges them. Built to run standalone now; each becomes a node in the Planner's
graph later.

| agent | input | file |
|---|---|---|
| Market Data Agent | `market-data-mcp` | `market_data_agent.py` |
| News & Sentiment Agent | `research-mcp` | `news_sentiment_agent.py` |
| Filings Agent | `filings-rag-mcp` | `filings_agent.py` |
| Synthesis Agent | the three agents' output dicts | `synthesis_agent.py` |

The shared machinery — MCP stdio client, the Groq-backed `create_react_agent`
through `shared/llm_rate_limiter.py`, the model-fallback chain, MCP→LangChain tool
bridging, trace extraction, and the `run_agent` driver — lives in **`agents/_base.py`**.
An MCP agent module is just: a server path, a system prompt, a synthesis step
(structured-output schema + instructions), and a provenance extractor. Two
opt-in `run_agent` knobs exist for heavier domains: `compact_tool_result(tool,
payload)` shrinks what the ReAct loop sees per tool call (the full payload still
feeds `raw_data`/provenance), and `recursion_limit` caps the tool-call budget.
The Filings Agent uses both. The Synthesis Agent reuses only `make_model`,
`flatten_exc` and the structured-output pattern — not `run_agent` (see its section).

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

## `news_sentiment_agent.py` — News & Sentiment Agent

Answers questions about recent news, market sentiment, and corporate
announcements for an Indian-listed company by picking the right `research-mcp`
tool(s). Same wiring as above (`_base`). The hard part isn't tool selection —
it's that research-mcp's tools carry real caveats that a naive agent would
smooth into false confidence. This agent's system + synthesis prompts force it
to respect them:

| research-mcp tool | the caveat | what this agent does |
|---|---|---|
| `get_sentiment` | dual-mode (text vs aggregate); the raw `breakdown` counts off-entity articles and is inflated | passes a **ticker** so aggregate mode runs; reports `overall.label` + **`breakdown_on_company`** over `on_company_count` as *the* number, and notes when raw `breakdown` differs. `score` is stated as "self-reported confidence, not calibrated". Matches research-mcp's own README distinction. |
| `get_corporate_announcements` | a keyword-scoped Tavily news search, **NOT** the NSE/BSE feed; `mentions_company` / `likely_announcement` flags; group-company bleed-through | findings **lead with `likely_announcement=true`** items; any unflagged item cited is tagged `"(lower confidence: not flagged on-company / no announcement keyword)"`; the `disclaimer` (keeping the "NOT the NSE/BSE official feed" phrase) and the entity-disambiguation risk (naming the actual noise, e.g. Tech Mahindra for M&M) go into a dedicated **`caveats`** list |
| `get_company_news` | items flagged `mentions_company=false` may be a group company / peer | noted when relied on |

Output adds a top-level **`caveats: list[str]`** to the usual
`{ticker, company, findings, summary, tools_called, provenance, raw_data,
reasoning_trace}` — non-empty whenever a tool carried a disclaimer. `provenance`
lifts the caveat-bearing fields (`disclaimer`, `breakdown` vs
`breakdown_on_company`, `likely_announcement_count`, per-item flag breakdowns)
into structured form so the Synthesis Agent gets them without re-parsing prose.

```python
from agents.news_sentiment_agent import run_sync
result = run_sync("what's the market sentiment on TCS right now")
```

### Test

```bash
python agents/test_news_sentiment_agent.py
```

Three patterns, asserting tool choice **and** caveat fidelity (not just prose):

| query | expected | caveat check |
|---|---|---|
| "what's the latest news on Reliance" | `search_news` / `get_company_news`, not sentiment/announcements | — |
| "what's the market sentiment on TCS right now" | `get_sentiment` in `mode == "aggregate"` | output surfaces `breakdown_on_company` as the number; states score isn't calibrated |
| "any recent dividend or earnings announcements from M&M" | `get_corporate_announcements` | `caveats` says "NOT the NSE/BSE feed" **and** names the group-company (Tech Mahindra) disambiguation risk; unflagged items tagged lower-confidence |

Verified: in the announcements run the agent listed the 6 flagged M&M items first,
tagged each Tech Mahindra item `"(lower confidence: ...)"`, and its summary itself
said *"...Tech Mahindra ... a different Mahindra Group company and not on-company
for M&M"*. The `get_company_news` payload (9 full articles) is trimmed before the
synthesis call — the un-trimmed blob confused the smaller fallback models into an
empty synthesis. Queries are paced ~45 s apart (`GROQ_TEST_GAP_S`) for the ~8k
tokens/min Groq cap.

## `filings_agent.py` — Filings Agent

Answers questions about what a company disclosed in its **own** annual report,
grounded in cited pages, by picking one `filings-rag-mcp` tool. Same wiring as
above (`_base`). The retrieval payload is large (multiple ~1,100-token chunks per
call), so the trimming lesson from the News Agent is applied **from the start**,
not retrofitted:

- `_compact` caps the chunk list to 4 and each chunk's text to ~450 chars
  *before* it reaches the reasoning loop **and** the synthesis call, via the
  `compact_tool_result` hook. Full chunk text is untouched in `raw_data` for
  citation/verification.
- `recursion_limit=10` + a strict "make **exactly one** tool call" system prompt
  (a 2nd call only if the 1st errored or hit the wrong section). Without this the
  ReAct loop fired 3–5 `search_filing` calls per question with reworded queries,
  blowing Groq's ~8k-tokens/min cap on the growing message history.

Caveats it is forced to respect (matching `filings-rag-mcp`'s own README):

| the caveat | what this agent does |
|---|---|
| **page citations are the point** | every finding drawn from the filing cites company + fiscal year + page, e.g. `(Reliance Industries, FY2024-25, p.142)`. An un-cited finding is only allowed when it states something was *not* found. |
| **`may_contain_tabular_data`** — flagged chunk = a statement table PDF-flattened into run-on text | figures from a flagged chunk are hedged (`"approximately"`, `"as read from the flattened table on p.X"`), never restated with false precision; provenance carries a `tabular_warning` naming the exact pages |
| **`compare_yoy_metrics` is single-filing scope** — the one report's own current + prior-year columns, not a trend across filings | the tool's `limitation` string is carried verbatim into `provenance`; a `caveats` entry keeps *"NOT a cross-filing multi-year comparison — one annual report per company"*; if the query implied wanting a trend, the summary says only this one YoY step is available |
| **standalone vs consolidated** — `get_financial_statement_section` can return both | `statement_basis` field (`standalone` / `consolidated` / `mixed` / `n/a`) records which the cited figures are on; findings say which, or flag it as unclear from the retrieved text |

Output adds `fiscal_year` and `statement_basis` to the usual
`{ticker, company, findings, summary, caveats, tools_called, provenance,
raw_data, reasoning_trace}`.

```python
from agents.filings_agent import run_sync
result = run_sync("what are Reliance's key disclosed risks")
```

### Test

```bash
python agents/test_filings_agent.py
```

Three patterns against `RELIANCE` / `TCS` / `M&M` (all ingested), asserting tool
choice **and** caveat fidelity:

| query | expected tool | caveat check |
|---|---|---|
| "what are Reliance's key disclosed risks" | `search_filing` only | every finding cites a page; provenance carries the page list |
| "what was TCS's revenue and profit for the year, from the income statement" | `get_financial_statement_section` (`income_statement`) | figures hedged; `standalone`/`consolidated` flagged; a caveat says search-based / table-flattened |
| "how has M&M's EBITDA changed year over year" | `compare_yoy_metrics` | provenance carries `basis` + `limitation`; a caveat states this is **not** a cross-filing multi-year trend |

Verified (per-query, 2026-09-04): Q1 produced 5 page-cited risk findings
(`p.15`, `p.88`, `p.128`, …) with a tabular caveat naming pages 88/89/128; Q2
hedged TCS revenue as *"approximately ₹267,021 crore (…FY2025-26, p.167)"* with
`statement_basis: consolidated`; Q3 correctly reported that M&M's filing does not
break out "EBITDA" as a line item rather than inventing a figure, while carrying
the single-filing `limitation`. Queries paced ~90 s apart (`GROQ_TEST_GAP_S`);
each retrieval is one shared-quota Gemini embedding call.

## `synthesis_agent.py` — Synthesis Agent

The fourth agent, and the odd one out: **no MCP server, no ReAct loop.** It is
handed the finished output dicts of the other three and reconciles them into the
report a user actually reads.

```python
from agents.synthesis_agent import synthesize_sync
report = synthesize_sync(query, {
    "market_data":   market_data_agent.run_sync(...),
    "news_sentiment": news_sentiment_agent.run_sync(...),
    "filings":        filings_agent.run_sync(...),
})
```

The interface — `synthesize(query, specialist_outputs: dict[str, dict])` — takes
**already-gathered** outputs and nothing else. Deciding *what* to fetch is the
Planner's job; Synthesis only reconciles and reports.

### How much of `_base.py` applies

`run_agent` is an MCP-plus-ReAct driver — subprocess, tool bridge, `create_react_agent`,
`extract_trace`. None of that applies here. What's reused directly: `make_model`
(the rate-limited Groq + fallback chain), `flatten_exc` + `rl.QuotaExceededError`
classification, and the `with_structured_output(...) + one retry-guard` pattern
every other agent's `_synthesize` already uses. So the module is `make_model` +
one structured call + a thin driver of its own — no duplicated LLM/limiter code.

### What it owns

| concern | behaviour |
|---|---|
| **conflicting signals** | strong fundamentals vs negative sentiment, a filing risk news is/isn't echoing, a metric two specialists state differently — go into `conflicts_flagged` as `{topic, specialist_a/position_a, specialist_b/position_b, assessment}`, where `assessment` must judge *real contradiction vs different lenses* (trailing vs recent, different fiscal years, sample vs whole). Never averaged into a bland middle. |
| **fiscal-year vintage** | market_data (yfinance, ~FY2026) and filings (one fixed AR, FY2024-25 / TCS FY2025-26) are different years — the prompt forces this into `overall_caveats` / `conflicts_flagged`, never a silent merge. |
| **caveat carry-through** | every claim in `sources_by_claim` carries the **strongest upstream hedge** that applied to it (filings table-flattening, filings single-year, news "not the NSE/BSE feed", news "self-reported score", market_data `roe_source` / `as_of`). A hedged finding is never laundered into a confident one. |
| **attribution** | `sources_by_claim[claim] = {sources: [...], caveat: ...}` — per claim, names the specialist(s) and a specific article/date or filing page where it rests on one. |
| **partial input** | `_classify` → ok / failed / missing. Missing or errored specialists get an explicit `missing_data` entry and a `"Not available - …"` section even if the model forgets. `synthesize` on an empty set returns an `error`, not a fake report. |

### Output

```python
{
  "query": "...",
  "companies": ["Tata Consultancy Services"],
  "executive_summary": "... leads with the main tension ...",
  "sections": {"market_data": "...", "news_sentiment": "...", "filings": "..."},
  "conflicts_flagged": [{"topic": ..., "specialist_a": ..., "assessment": ...}],
  "overall_caveats": [...],
  "missing_data": [...],
  "sources_by_claim": {"<claim>": {"sources": [...], "caveat": "..."}},
  "specialists_used": [...], "reasoning_trace": [...], "model": "openai/gpt-oss-120b"
}
```
On empty/failed input: `{"query", "error", "inputs_received"|"missing_data"}`.

### Test

```bash
python agents/test_synthesis_agent.py
```

Runs all three specialists **for real** on TCS (data-complete; Indian IT is the
case most likely to show a fundamentals-vs-sentiment split), then feeds the real
outputs in. Case 1 = all three; Case 2 = filings dropped, reusing case 1's fetched
outputs (partial-failure handling, no extra API calls).

Verified 2026-09-08 (27/27 checks): market_data gave ROE 47.74% / P/E 16.73
("strong fundamentals"); news_sentiment gave 9-of-10 negative articles over a
chairman departure + AI-revenue downgrades; the report's `conflicts_flagged`
entry assessed it *"different lenses… not a factual contradiction but a tension
between quantitative health and qualitative sentiment"*, `overall_caveats` named
the FY2026-vs-FY2025-26 vintage gap, and all 5 claims carried their upstream
hedge (roe_source, "self-reported… not exhaustive", "similarity-based… single
annual report"). Case 2 marked filings *"Not available"* and did not invent
filings-sourced claims. Paced `SYNTH_TEST_GAP_S` (45 s) apart.

