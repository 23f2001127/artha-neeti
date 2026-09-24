# agents

The research pipeline: a LangGraph planner, three specialist agents that each
work through one MCP server, and two single-call agents that write the report
and answer follow-up questions.

| Module | Role | Works from |
| --- | --- | --- |
| `planner.py` | Routes a question and runs the whole pipeline | The user's question |
| `market_data_agent.py` | Prices, valuation, ratios, peers | market-data-mcp |
| `news_sentiment_agent.py` | Recent news, sentiment, announcements | research-mcp |
| `filings_agent.py` | Annual-report disclosures with page citations | filings-rag-mcp |
| `synthesis_agent.py` | Merges specialist findings into one report | Specialist outputs |
| `followup_agent.py` | Answers follow-up questions about a report | A finished report |
| `_base.py` | Shared model, MCP bridge and agent driver | |

## Models

| Work | Model | Why |
| --- | --- | --- |
| Agent reasoning and report writing | Groq `openai/gpt-oss-120b`, then `qwen/qwen3.8-27b`, `openai/gpt-oss-20b`, `openai/gpt-oss-safeguard-20b` | Fast, with a daily free allowance large enough for the 3 to 5 calls each agent makes |
| News sentiment (in research-mcp) | Gemini `gemini-3-flash-preview` chain | Structured classification at low volume |
| Annual-report embeddings (in filings-rag-mcp) | Gemini `gemini-embedding-001` | Groq has no embedding API |

Every model in the Groq chain must support tool calling. `GROQ_AGENT_MODEL`
overrides the primary. All LLM calls go through the shared rate limiter
([`shared/`](../shared/README.md)); Groq limits by account, so one bucket
covers the whole chain.

## Shared machinery (`_base.py`)

A specialist module supplies a server path, a system prompt, a structured
synthesis step and a provenance extractor. `_base.py` provides the rest:

- **`RateLimitedChatGroq`**: every call reserves quota first. Before sending,
  requests are fitted under Groq's per-request limit (8,000 tokens of input plus
  output, the same for every model) by shortening the largest tool results.
  Failures are handled by kind:
  - rate limit: move to the next model;
  - request too large: refit once with a tighter budget, then fail with
    `RequestTooLargeError`;
  - malformed tool call: retry once, then move to the next model.
- **`load_mcp_tools`**: turns each MCP tool's JSON schema into a LangChain
  `StructuredTool` that calls the server over stdio.
- **`run_agent`**: spawns the server, runs `create_react_agent`, writes the
  structured result and extracts a reasoning trace. `compact_tool_result`
  shrinks what the model sees per tool call while `raw_data` keeps the full
  payload; `on_stage` reports progress ("calling get_ratios…") to the planner.
- **`describe_error`**: labels failures as a rate limit, an oversized request
  or another error, so reports can explain a missing source accurately.

## Specialist agents

Each exposes `run(query)` (async) and `run_sync(query)` and returns:

```python
{
  "query": "...", "ticker": "TCS.NS", "company": "Tata Consultancy Services Limited",
  "findings": ["..."], "summary": "...", "caveats": ["..."],
  "tools_called": ["get_fundamentals", "get_ratios"],
  "provenance": {"get_ratios": {"as_of": "...", "fiscal_year": 2026, ...}},
  "raw_data": {"get_ratios": {...}},
  "reasoning_trace": [...], "model": "openai/gpt-oss-120b",
}
```

A failure returns `{"query", "error", "tools_called", "partial_raw_data"}`.

**Market data.** Chooses among four tools; valuation questions call both
fundamentals and ratios, and comparisons use one peer-comparison call. Price
histories are summarized (range, change, sampled closes) before the model sees
them.

**News and sentiment.**
- Company sentiment uses aggregate mode and reports `breakdown_on_company`, the
  articles actually about the company. The score is presented as the
  classifier's confidence, not as a probability.
- Announcement results say they come from news search, not the exchange feed.
- Articles about group companies (Tech Mahindra for M&M) are marked lower
  confidence.

**Annual report.** One retrieval call per question.
- At most four chunks of 450 characters reach the model; full text stays in
  `raw_data` for citation.
- Every finding cites company, fiscal year and page.
- Figures from chunks flagged `may_contain_tabular_data` are hedged.
- `statement_basis` records whether figures are standalone or consolidated.
- Year-on-year comparisons use one report's own current and prior-year columns.

## Synthesis (`synthesis_agent.py`)

No tools and no ReAct loop: one structured call over the specialists' findings.

```python
report = await synthesize(query, {"market_data": md, "news_sentiment": news, "filings": filings})
```

- `conflicts_flagged`: each disagreement between sources, with an assessment of
  whether it is a contradiction or a difference of lens (trailing figures
  against a recent event, different fiscal years).
- `sources_by_claim`: each key claim with its sources and the strongest
  upstream caveat.
- `unavailable`: sources that failed, with a reader-facing reason, and those not
  routed for this question.
- Market data (latest fiscal year) and the annual report (a fixed earlier year)
  are never merged without stating the period gap.

## Follow-ups (`followup_agent.py`)

One structured call over a finished report and up to eight prior turns. It
either answers from the report, keeping the relevant caveat, or returns
`sufficient_data: false` with a reason and a `standalone_query` whose
references ("its", "that company") are resolved, ready to start a new run. It
sees only the finished report, not raw tool output.

## Planner (`planner.py`)

```
START → route → gather → synthesize → [compare | portfolio] → finalize → END
```

| Node | Work |
| --- | --- |
| route | One LLM call resolves companies to NSE tickers, picks single, comparison or portfolio mode, and selects specialists per company with a reason for each skip. Unknown tickers get a lightweight yfinance existence check. Annual-report analysis is only routed for companies whose report is indexed. |
| gather | Runs the selected (company, specialist) pairs with bounded concurrency. A failing specialist becomes an error cell, not a crash. |
| synthesize | One synthesis call per company. |
| compare | Comparisons: verdict, dimension-by-dimension assessment and caveats over the finished reports. |
| portfolio | Portfolios: weights are resolved during routing (given weights normalized to 100, otherwise equal weights, always stated). Weighted P/E, ROE, dividend yield and sector allocation are computed in code; one LLM call writes the narrative, diversification, concentration risks and caveats. It is a composition review, not a correlation or volatility model. |
| finalize | Assembles the report, routing rationale and sentiment signals for charts. |

Each company gets a complete report before any cross-company step, so its
conflicts and caveats stay attributed to it. Concurrency defaults to 2 for one
company and 1 for several (`PLANNER_MAX_CONCURRENCY` overrides).

`plan(query, on_progress=...)` pushes routing to the caller as soon as it is
decided and updates `specialist_status` as each specialist moves. The result:

```python
{
  "query": "...", "mode": "single" | "multi" | "none",
  "companies": [...],
  "routing": {"companies_identified": [{"ticker", "specialists": [{"specialist", "selected", "reason"}], ...}],
              "rationale": "...", "is_portfolio": False, "weights_note": None, ...},
  "routing_trace": ["..."],
  "reports": {"TCS": {...}},
  "comparison": {...} | None,
  "portfolio": {...} | None,
  "signals": {"TCS": {"sentiment": {...}}},
  "specialist_status": {"TCS": {"market_data": "ok", ...}},
}
```

## Usage

```python
from agents.planner import plan_sync
report = plan_sync("compare TCS and Infosys on fundamentals and risk")

from agents.market_data_agent import run_sync
result = run_sync("how is TCS valued compared to its fundamentals?")
```

## Tests

Offline unit tests cover request fitting, failure classification, tool-result
compaction and attribution (`tests/unit/`). Each agent and the planner also
have live integration tests in `tests/integration/` that check tool choice and
caveat handling against the real providers:

```bash
pytest tests/integration/test_planner.py --live
```
