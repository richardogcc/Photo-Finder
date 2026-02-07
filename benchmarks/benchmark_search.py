"""Simple benchmark for Photo Finder.

Usage:
  python benchmarks/benchmark_search.py /path/to/reference.jpg /path/to/dir
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from photo_finder.engine import SearchConfig, search


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    config = SearchConfig(show_progress=False)

    times = []
    for _ in range(args.runs):
        start = time.perf_counter()
        search(args.reference, args.directory, config)
        times.append(time.perf_counter() - start)

    avg = sum(times) / len(times)
    print(f"Runs: {args.runs}")
    print(f"Avg time: {avg:.3f}s")
    print(f"Min time: {min(times):.3f}s")
    print(f"Max time: {max(times):.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
