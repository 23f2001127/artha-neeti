# mcp_servers

Three [Model Context Protocol](https://modelcontextprotocol.io) servers that give
the agents their data. Each runs over stdio. The agents start them as
subprocesses, and any MCP client can use them the same way.

| Server | Tools | Data | Details |
| --- | --- | --- | --- |
| `market_data_mcp` | `get_price_history`, `get_fundamentals`, `get_ratios`, `get_peer_comparison` | yfinance | [README](market_data_mcp/README.md) |
| `research_mcp` | `search_news`, `get_company_news`, `get_sentiment`, `get_corporate_announcements` | Tavily, Gemini | [README](research_mcp/README.md) |
| `filings_rag_mcp` | `search_filing`, `get_financial_statement_section`, `compare_yoy_metrics` | Annual reports in Postgres + pgvector | [README](filings_rag_mcp/README.md) |

## Conventions

- **Layout.** The logic lives in plain Python modules (`market_data.py`,
  `research.py`, `retrieval.py`). `server.py` only registers them as tools.
- **Errors.** Expected failures return `{"error": "<message>"}` rather than
  raising, so agents can report them.
- **Timestamps.** Successful responses include an `as_of` UTC timestamp.
- **Tickers.** Bare symbols are NSE (`.NS`). BSE (`.BO`) and symbols with `&`
  (`M&M`) are accepted as given.
- **Independence.** Each server keeps its own small ticker and name maps
  rather than importing from another server.
- **Rate limits.** Every LLM and embedding call goes through
  `shared/llm_rate_limiter.py`.
- **Tool descriptions.** The docstrings of the tool functions in `server.py`
  are what the agents read to choose tools, so edit them with that in mind.

## Using a server from another client

```json
{
  "mcpServers": {
    "artha-market-data": { "command": "python", "args": ["-m", "mcp_servers.market_data_mcp.server"] },
    "artha-research":    { "command": "python", "args": ["-m", "mcp_servers.research_mcp.server"] },
    "artha-filings":     { "command": "python", "args": ["-m", "mcp_servers.filings_rag_mcp.server"] }
  }
}
```

Run from the repository root with `.env` in place.
