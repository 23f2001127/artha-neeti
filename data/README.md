# data

Local files for annual-report indexing. The contents are not committed.

| Folder | Contents |
| --- | --- |
| `filings/` | Annual-report PDFs for bulk indexing, named `TICKER_AR_YYYY-YY.pdf` (for example `TCS_AR_2025-26.pdf`) |
| `uploads/` | PDFs received through the upload and web-fetch jobs, named `<TICKER>_<UPLOAD|FETCH>_<job id>.pdf` |

Index the files in `filings/` with:

```bash
python -m mcp_servers.filings_rag_mcp.ingest
```

The index itself lives in Postgres, so these files are only needed while
indexing. The Docker image leaves out `filings/`, and uploads go to a volume.
