# market-data-mcp

An MCP server (stdio) serving market data for NSE and BSE listed companies from
[yfinance](https://github.com/ranaroussi/yfinance). The market data agent is its
client; `app/visuals.py` calls the same functions directly for charts.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `get_price_history` | `ticker`, `period` (`1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `5y`) | Daily OHLCV rows |
| `get_fundamentals` | `ticker` | Name, sector, industry, price, market cap, P/E, forward P/E, EPS, dividend yield, 52-week range, `last_fiscal_year_end` |
| `get_ratios` | `ticker` | ROE, ROA, debt to equity, current and quick ratios, gross, operating, EBITDA and profit margins, with `computed` and `fiscal_year` |
| `get_peer_comparison` | `tickers` | Market cap, P/E, ROE (with `roe_source`), dividend yield per company, largest first |

`market_data.py` also provides `get_financial_trends(ticker)`: four fiscal
years of revenue, net income, and operating and net margins. It feeds the
charts and is not exposed as a tool.

Every response carries an `as_of` timestamp. Failures (unknown ticker, no data,
invalid argument) return `{"error": "<message>"}` rather than raising.

## Conventions

- **Tickers.** `RELIANCE.NS` and `RELIANCE.BO` are used as given. A bare symbol
  gets `.NS`. `M&M.NS` is passed through unchanged.
- **Units.**
  - `dividend_yield_pct` is a percentage (`2.74` is 2.74%).
  - `roe`, `roa` and the margins are fractions (`0.15` is 15%).
  - `debt_to_equity` follows yfinance's percentage scale (`36.65` is 0.37x).
  - Market cap is in the listing currency.
- **Missing values** are `null` and listed under `missing`, so "not available"
  is never confused with zero.

### Computed ratios

yfinance's summary omits ROE, ROA, current ratio or debt to equity for many
large Indian companies. When a value is missing, `get_ratios` computes it from
the two latest annual statements, then records the field in `computed` and the
statement period in `fiscal_year`:

| Ratio | Formula |
| --- | --- |
| ROE | Net income attributable to the parent ÷ average parent equity |
| ROA | Net income attributable to the parent ÷ average total assets |
| Debt to equity | Total debt ÷ total equity including minority interest, × 100 |
| Current ratio | Current assets ÷ current liabilities |

Computed ROE is within a few percentage points of published figures (for
example Reliance 9.2% against 8.9% on screener.in), the gap coming from average
against closing equity. `get_peer_comparison` marks each row's `roe_source`, so
rows on different bases are visible.

### Data vintage

Prices update continuously; statements update yearly. yfinance currently serves
fiscal 2026 statements while most indexed annual reports are fiscal 2024-25, so
market data and filings are often a year apart. Responses carry `fiscal_year`
and `last_fiscal_year_end` so the synthesis step can state the gap instead of
merging the two.

## Running

The agent starts the server itself. To run it by hand or register it with
another MCP client:

```bash
python -m mcp_servers.market_data_mcp.server
```

```json
{
  "mcpServers": {
    "market-data": { "command": "python", "args": ["mcp_servers/market_data_mcp/server.py"] }
  }
}
```

## Tests

- `tests/unit/test_market_data_validation.py`: ticker and argument
  validation, offline.
- `tests/integration/test_market_data_mcp.py` (`--live`): every tool against
  real tickers, including `M&M.NS`, plus error handling for invalid input.
