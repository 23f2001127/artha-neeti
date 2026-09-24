"""Subprocess entry point for the cross-process rate-limiter tests.

Usage: python rate_limiter_worker.py <bucket> <iterations> <tokens> <out_file>
Writes one line per acquire attempt to ``<out_file>.<pid>``.
"""

from __future__ import annotations

import os
import sys
import time

from shared import llm_rate_limiter as rl


def main(bucket: str, iterations: int, tokens: int, out_file: str) -> None:
    lines: list[str] = []
    for _ in range(iterations):
        try:
            rid = rl.acquire(tokens, bucket, count=1, timeout=120.0)
        except rl.QuotaExceededError:
            lines.append(f"QUOTA {time.time():.4f} {os.getpid()}")
            break
        lines.append(f"OK {time.time():.4f} {os.getpid()} {rid}")
        time.sleep(0.01)
    # One file per process: concurrent appends to a shared file interleave and lose lines.
    with open(f"{out_file}.{os.getpid()}", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
