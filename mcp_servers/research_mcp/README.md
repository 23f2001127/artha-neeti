# research-mcp

An MCP server (stdio) for news, sentiment and corporate announcements on Indian
listed companies. The news and sentiment agent is its client.

| Service | Key | Use |
| --- | --- | --- |
| [Tavily](https://tavily.com) | `TAVILY_API_KEY` | Web and news search |
| [Gemini](https://ai.google.dev) | `GEMINI_API_KEY` | Sentiment classification |

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_news` | `query`, `max_results` (1 to 20) | Topic news search |
| `get_company_news` | `ticker_or_name`, `days_back` (1 to 365) | Company news; each item flagged `mentions_company`, with `on_company_count` |
| `get_sentiment` | `text_or_ticker` | Sentiment label, score and rationale for a text, or aggregate sentiment for a company |
| `get_corporate_announcements` | `ticker`, `days_back` | Announcement-like coverage (results, dividends, board meetings, M&A), likely announcements first |

Result items are `{title, url, published_date, source_score, snippet}`, where
`source_score` is Tavily's relevance score. Failures return `{"error": ...}`;
successes carry `as_of`.

### Sentiment modes

`get_sentiment` chooses a mode from its input:

- **Aggregate**: a ticker or short name (`RELIANCE.NS`, `Infosys`). About ten
  recent articles are classified in one call, returning `overall`, `breakdown`
  (all articles), `breakdown_on_company` (articles about the company) and the
  scored articles.
- **Text**: a longer string, such as a headline or a quote, classified
  directly.

Inputs of 48 characters or fewer, five words or fewer, or with an exchange
suffix or a known ticker, are treated as companies. A short headline without
punctuation can be misread as a company name.

### Company matching

The company-scoped tools flag each result `mentions_company` using a strict
alias list:
- `M&M` matches "Mahindra & Mahindra" and "M&M" but not "Tech Mahindra";
- `RELIANCE` matches "Reliance Industries" and "RIL" but not "Reliance Power".

Group-company regexes are removed from the text before matching. Results are
flagged, not dropped. Announcements are also sorted by the flag, and
`breakdown_on_company` is the sentiment figure to rely on. The alias map
covers the indexed companies and common peers; other tickers fall back to
looser name matching.

## Models and quota

Sentiment uses `gemini-3-flash-preview`, then `gemini-flash-lite-latest` and
`gemini-flash-latest`, each with its own free-tier quota (about 5 requests a
minute and 20 a day). Every attempt goes through the shared rate limiter.
Retries back off on 429 and 5xx responses using the server's retry delay.
`GEMINI_MODEL` overrides the first model. When all models are exhausted,
`get_sentiment` returns an error, and callers treat the sentiment as
unavailable rather than neutral.

## Limitations

**Sentiment**
- `score` is the model's self-reported confidence, not a calibrated
  probability.
- Results can vary between runs, and headline framing influences labels.
- Aggregate sentiment reflects the articles search returned, which can include
  syndicated duplicates.

**Announcements**
- These are news coverage about announcements, not the NSE or BSE filing feed.
  Every response carries a disclaimer to that effect.
- Dates are article dates.
- Keyword matching also catches previews ("what to expect from Q2 results").

**Search**
- Recall, freshness and date quality depend on Tavily. Repeated queries can
  return different sets.
- Queries are anchored as `"<name>" stock news`: longer keyword queries
  drifted to unrelated companies.

## Running

```bash
python -m mcp_servers.research_mcp.server
```

## Tests

- `tests/unit/test_research_entity_matching.py`: alias and group-company
  matching, offline.
- `tests/integration/test_research_mcp.py` (`--live`): all four tools, sentiment
  mode detection and error handling against the real services. Sentiment calls
  are spaced by `GEMINI_TEST_SPACING_S` (14 seconds by default).
