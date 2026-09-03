# market-data-mcp

An MCP server that wraps [yfinance](https://github.com/ranaroussi/yfinance) to serve
live market data for companies listed on Indian exchanges (NSE / BSE). It is the
tool layer the **Market Data Agent** in ArthaNeeti calls.

Transport: **stdio** (for now).

## Tools

| Tool | Signature | What it returns |
|------|-----------|-----------------|
| `get_price_history` | `(ticker: str, period: str = "1mo")` | Daily OHLCV rows over a trailing window. `period` ∈ `1d, 5d, 1mo, 3mo, 6mo, 1y, 5y`. |
| `get_fundamentals` | `(ticker: str)` | Name, sector, industry, current price, market cap, P/E, forward P/E, EPS (TTM), dividend yield (%), 52-week high/low, plus `as_of` and `last_fiscal_year_end`. |
| `get_ratios` | `(ticker: str)` | ROE, ROA, debt-to-equity, current ratio, quick ratio, and profit / gross / operating / EBITDA margins, plus `computed`, `fiscal_year`, `as_of`. |
| `get_peer_comparison` | `(tickers: list[str])` | One row per ticker — market cap, P/E, ROE (+ `roe_source`, `fiscal_year`), dividend yield — sorted by market cap, largest first. |

Every tool returns structured JSON. On a bad ticker, missing data, or an invalid
argument it returns `{"error": "<human readable message>"}` instead of raising,
so the calling agent gets a clear signal it can surface to the user.

### Ticker format

- NSE symbols: `RELIANCE.NS`, `TCS.NS`, `M&M.NS`
- BSE symbols: `RELIANCE.BO`
- A bare symbol (`INFY`) is treated as NSE → `INFY.NS`
- Ampersands are preserved: `M&M.NS` resolves correctly to Mahindra & Mahindra.

### Notes on the data

- `dividend_yield_pct` is a **percentage** (`2.74` means 2.74%).
- `roe`, `roa`, and the `*_margin` fields are **fractions** (`0.15` means 15%).
- `debt_to_equity` is a **percentage** (`36.65` ≈ 0.37×), matching yfinance's scale.
- `market_cap` is in the listing currency (INR for `.NS` symbols).

#### How `get_ratios` fills gaps

yfinance's summary (`.info`) does not expose ROE / ROA / current ratio /
debt-to-equity for every company (common for large Indian names, where the
consolidated statements carry big minority interests). When `.info` omits one,
`get_ratios` computes it from the two most recent annual statements, using
conventions chosen to stay comparable with yfinance's own values:

| Ratio | Formula when computed |
|-------|-----------------------|
| ROE | net income *to owners of the parent* ÷ **average** shareholders' equity (parent) |
| ROA | net income *to owners of the parent* ÷ **average** total assets |
| debt-to-equity | total debt ÷ **total equity incl. minority interest**, period-end, ×100 |
| current ratio | current assets ÷ current liabilities, period-end |

- `"computed"` lists which fields came from statements rather than `.info`.
- `"fiscal_year"` is the statement period behind those computed fields.
- Anything still unavailable is `null` and listed under `"missing"`.
- In `get_peer_comparison`, each row carries `roe_source` (`"yfinance"` or
  `"computed"`) and `fiscal_year` so a consumer can see when two rows are not on
  the identical basis. Spot-checked against screener.in: RELIANCE 9.2% (screener
  8.9%), TCS 47.7% (screener ~52%), M&M 20.1% (screener 20.3%) — all within the
  noise between ending- vs average-equity and adjusted-vs-raw definitions.

#### Provenance / data vintage — a known cross-agent constraint

Market data (price, market cap) updates continuously; company statements update
once a year. Every response carries an `as_of` timestamp, and `get_fundamentals`
/ `get_ratios` also carry `last_fiscal_year_end` / `fiscal_year`. These are **not
forced to align** and should not be:

- yfinance currently serves **FY2026** (year ended 31 Mar 2026) statements.
- The annual-report PDFs in `data/filings/` are **FY2024-25** (TCS is 2025-26).

So for most tickers the Market Data Agent and the Filings Agent will be one
fiscal year apart. That is a real property of the data, not a bug. The
**Synthesis Agent** (when built) must read `fiscal_year` / `last_fiscal_year_end`
off market-data outputs and reconcile them against the filing period rather than
assuming the two describe the same year.

## Running the server

```bash
# from the repo root, with the project venv active
python mcp_servers/market_data_mcp/server.py
```

or as a module:

```bash
python -m mcp_servers.market_data_mcp.server
```

The server speaks MCP over stdio, so it is normally launched by an MCP client
(the LangGraph agent) rather than run by hand. Example client config:

```json
{
  "mcpServers": {
    "market-data": {
      "command": "python",
      "args": ["mcp_servers/market_data_mcp/server.py"]
    }
  }
}
```

## Testing

`test_market_data.py` is a **standalone smoke test** (not pytest yet). It hits the
live yfinance API, so it needs network access.

```bash
python mcp_servers/market_data_mcp/test_market_data.py
```

It does three things:

1. **Exercises all 4 tools** against `RELIANCE.NS`, `TCS.NS`, and `M&M.NS`, printing
   the full JSON so you can eyeball correctness.
2. **Focused check on `M&M.NS`** — verifies the ampersand symbol is not mangled by
   normalisation and that it resolves to Mahindra & Mahindra with a valid market
   cap and price history.
3. **Failure handling** — confirms an invalid ticker, an invalid period, an empty
   peer list, and a partially-invalid peer list all return clean errors instead of
   crashing.

Exit code is `0` if every check passes, `1` otherwise. A run ends with either
`all checks passed` or a list of the failed checks.

To verify the MCP stdio transport itself end to end, the file layout is:

```
mcp_servers/market_data_mcp/
├── __init__.py
├── server.py            # MCP server: tool definitions + stdio entrypoint
├── market_data.py       # framework-agnostic yfinance logic (the real work)
├── test_market_data.py  # standalone smoke test
└── README.md
```

`server.py` is a thin wrapper: each tool calls the matching function in
`market_data.py`. Test or reuse the data logic by importing `market_data`
directly — no MCP client needed.
