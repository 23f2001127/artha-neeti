"""One-shot / on-demand ingestion of the annual-report PDFs into pgvector.

    python -m mcp_servers.filings_rag_mcp.ingest              # ingest all, skip done
    python -m mcp_servers.filings_rag_mcp.ingest --only RELIANCE TCS
    python -m mcp_servers.filings_rag_mcp.ingest --force      # re-ingest everything
    python -m mcp_servers.filings_rag_mcp.ingest --status     # just print progress

Resumability:
- A filename in ``filing_ingestions`` = fully done -> skipped (unless --force).
- Chunks present but no ``filing_ingestions`` row = a previous run died mid-file
  -> those chunks are deleted and the file is redone from scratch.
- Chunk inserts + embeddings are committed per batch, so a crash loses at most one
  batch of work, never the whole run.
- On an embedding quota wall (daily cap) the run stops cleanly; just run it again
  later to continue.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config, db
from .chunking import Chunk, chunk_stats, iter_pdf_chunks
from .embeddings import EmbeddingQuotaError, embed_documents

# Test companies first so a partial run still covers what the README demos.
_PRIORITY = ["RELIANCE", "TCS", "M&M"]


def _ordered_pdfs() -> list[Path]:
    pdfs = sorted(config.FILINGS_DIR.glob("*.pdf"))
    return sorted(
        pdfs,
        key=lambda p: (
            _PRIORITY.index(config.ticker_from_filename(p.name))
            if config.ticker_from_filename(p.name) in _PRIORITY
            else len(_PRIORITY),
            p.name,
        ),
    )


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _ingest_one(pdf_path: Path, group_size: int) -> dict:
    filename = pdf_path.name
    ticker = config.ticker_from_filename(filename)
    _log(f"parsing {filename} ({ticker}) ...")
    chunks: list[Chunk] = list(iter_pdf_chunks(pdf_path))
    stats = chunk_stats(chunks)
    est_min = stats["tokens"] / max(config.EMBED_TPM, 1)
    _log(
        f"  {filename}: {stats['pages']} pages -> {stats['chunks']} chunks "
        f"({stats['tabular_chunks']} flagged tabular, {stats['tokens']:,} tokens, "
        f"~{est_min:.0f} min at {config.EMBED_TPM:,} tok/min)"
    )
    if not chunks:
        _log(f"  {filename}: no extractable text, skipping")
        return {"filename": filename, "chunks": 0, "skipped": True}

    db.delete_filing(filename)  # clean slate (handles a prior partial run)

    embedded = 0
    with db.connect() as conn:
        # `embed_documents` sub-batches each group to the per-minute token budget;
        # committing per group keeps a crash cheap.
        for start in range(0, len(chunks), group_size):
            group = chunks[start : start + group_size]
            t0 = time.time()
            vectors = embed_documents([c.text for c in group])
            rows = [{**vars(c), "embedding": v} for c, v in zip(group, vectors)]
            db.insert_chunk_batch(conn, rows)
            embedded += len(group)
            _log(
                f"  {filename}: embedded {embedded}/{len(chunks)} "
                f"(+{len(group)} in {time.time() - t0:.1f}s)"
            )

        meta = {
            "filename": filename,
            "ticker": ticker,
            "company": config.company_name(ticker),
            "fiscal_year": config.fiscal_year_from_filename(filename),
            "pages": stats["pages"],
            "chunks": stats["chunks"],
            "tabular_chunks": stats["tabular_chunks"],
            "embed_model": config.EMBED_MODEL,
            "embed_dim": config.EMBED_DIM,
        }
        db.record_ingestion(conn, meta)
    _log(f"  {filename}: DONE ({embedded} chunks)")
    return {"filename": filename, "chunks": embedded, "skipped": False}


def run(only: list[str] | None, force: bool, group_size: int) -> int:
    db.init_schema()
    done = db.ingestion_status()
    chunk_counts = db.chunk_counts_by_filename()
    pdfs = _ordered_pdfs()
    if only:
        wanted = {t.upper() for t in only}
        pdfs = [p for p in pdfs if config.ticker_from_filename(p.name).upper() in wanted]
        if not pdfs:
            _log(f"no filings match --only {only}")
            return 1

    _log(f"embedding model={config.EMBED_MODEL} dim={config.EMBED_DIM} "
         f"tpm_cap={config.EMBED_TPM} commit_group={group_size}")
    _log(f"{len(pdfs)} filing(s) queued: {[p.name for p in pdfs]}")

    total_new = 0
    for pdf_path in pdfs:
        filename = pdf_path.name
        if not force and filename in done:
            _log(f"skip {filename} (already ingested: {done[filename]['chunks']} chunks)")
            continue
        if filename in chunk_counts and filename not in done:
            _log(f"note {filename}: {chunk_counts[filename]} orphan chunks from a "
                 f"partial run -> will re-ingest")
        try:
            result = _ingest_one(pdf_path, group_size)
            total_new += result["chunks"]
        except EmbeddingQuotaError as exc:
            _log(f"STOPPED on embedding quota: {exc}")
            _log("re-run this command later to continue where it left off.")
            _print_summary()
            return 2
        except KeyboardInterrupt:
            _log("interrupted; the current file will be re-done on the next run.")
            _print_summary()
            return 130

    _log(f"ingestion complete: {total_new} new chunks this run")
    _print_summary()
    return 0


def _print_summary() -> None:
    summary = db.corpus_summary()
    _log("=== corpus summary ===")
    for row in summary["by_ticker"]:
        _log(
            f"  {row['ticker']:<10} {row['chunks']:>5} chunks  "
            f"{row['tabular_chunks']:>4} tabular  pages {row['min_page']}-{row['max_page']}"
        )
    _log(f"  TOTAL: {summary['total_chunks']} chunks across "
         f"{len(summary['by_ticker'])} filings")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="TICKER", help="ingest only these tickers")
    ap.add_argument("--force", action="store_true", help="re-ingest even if already done")
    ap.add_argument("--status", action="store_true", help="print progress and exit")
    ap.add_argument("--group", type=int, default=60,
                    help="chunks per DB commit (embeddings are token-batched inside)")
    args = ap.parse_args()

    if args.status:
        db.init_schema()
        _print_summary()
        return
    sys.exit(run(args.only, args.force, args.group))


if __name__ == "__main__":
    main()
