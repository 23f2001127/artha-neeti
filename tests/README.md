# tests

pytest suites in two groups.

| Folder | Scope | Needs |
| --- | --- | --- |
| `unit/` | Offline logic: request fitting and failure handling, tool-result compaction, attribution, the rate limiter across processes, ticker validation, entity matching, API limits, PDF rendering | Nothing external |
| `integration/` | Each MCP server, each agent, the planner and the API against the real providers | API keys, database, `--live` |

```bash
pip install -r requirements-dev.txt

pytest                                             # unit tests; live tests are skipped
pytest --live                                      # everything
pytest tests/integration/test_planner.py --live    # one live suite
pytest -m "live and not e2e" --live                # live tests without full pipeline runs
```

## Markers

| Marker | Meaning |
| --- | --- |
| `live` | Calls external services and spends free-tier quota. Skipped unless `--live` is passed, which also loads `.env`. |
| `e2e` | Runs the full multi-agent pipeline; the heaviest tests. |
| `pace(seconds)` | Waits after the test in live runs to stay within provider rate limits. |

Live tests assert structure and behaviour (tool choice, caveats carried into
output, routing decisions), not exact text, because model output and search
results vary between runs. Pacing can be tuned with the `*_TEST_*` variables
listed in `.env.example`.

## Layout

- `conftest.py`: the `--live` option, marker handling and pacing.
- `helpers.py`: small shared utilities (text normalization for assertions).
- `unit/rate_limiter_worker.py`: the subprocess the rate-limiter tests launch.
