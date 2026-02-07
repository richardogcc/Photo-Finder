"""
CLI – Command-line interface for Photo Finder.

Usage:
    python -m photo_finder <image> <directory> [options]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import SearchConfig, search
from .hasher import HashAlgorithm


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo_finder",
        description=(
            "🔍 Photo Finder – Find duplicate or similar images.\n\n"
            "Recursively searches a directory for all images that\n"
            "match a reference image using perceptual hashing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m photo_finder photo.jpg ~/Pictures\n"
            "  python -m photo_finder photo.jpg ~/Pictures -a average -t 80\n"
            "  python -m photo_finder photo.jpg /Volumes/Backup --hash-size 8 -w 8\n"
        ),
    )

    parser.add_argument(
        "image",
        type=Path,
        help="Path to the reference image.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Base directory to search recursively.",
    )
    parser.add_argument(
        "-a", "--algorithm",
        type=HashAlgorithm,
        choices=list(HashAlgorithm),
        default=HashAlgorithm.PERCEPTUAL,
        help=(
            "Hash algorithm to use (default: perceptual).\n"
            "  average    – fast, good for exact duplicates.\n"
            "  perceptual – resistant to resizing/compression.\n"
            "  difference – very fast, detects gradient changes.\n"
            "  wavelet    – robust against transformations."
        ),
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=90.0,
        metavar="PCT",
        help="Minimum similarity percentage (0-100, default: 90).",
    )
    parser.add_argument(
        "--size-tolerance",
        type=float,
        default=50.0,
        metavar="PCT",
        help="Prefilter by file size tolerance percent (default: 50).",
    )
    parser.add_argument(
        "--no-size-filter",
        action="store_true",
        help="Disable size prefilter.",
    )
    parser.add_argument(
        "--hash-size",
        type=int,
        default=16,
        metavar="N",
        help="Hash size (larger = more precise but slower, default: 16).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        metavar="N",
        help="Batch size for hashing tasks (default: 500).",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=0,
        metavar="N",
        help="Number of parallel processes (default: auto = CPU count).",
    )
    parser.add_argument(
        "--io-workers",
        type=int,
        default=16,
        metavar="N",
        help="Number of I/O worker threads (default: 16).",
    )
    parser.add_argument(
        "--cache-db",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to SQLite cache database (default: .photo_finder_cache.sqlite3 in search dir).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable SQLite hash cache.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = SearchConfig(
        algorithm=args.algorithm,
        hash_size=args.hash_size,
        threshold=args.threshold,
        max_workers=args.workers,
        show_progress=not args.no_progress,
        use_cache=not args.no_cache,
        cache_db_path=args.cache_db,
        size_tolerance_pct=None if args.no_size_filter else args.size_tolerance,
        batch_size=args.batch_size,
        io_workers=args.io_workers,
    )

    print("╔══════════════════════════════════════════════════════════╗")
    print("║            🖼️  Photo Finder v1.0.0                      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    try:
        matches, stats = search(args.image, args.directory, config)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "matches": [
                {
                    "reference": str(m.reference),
                    "candidate": str(m.candidate),
                    "similarity_pct": m.similarity_pct,
                    "distance": m.distance,
                    "file_size": m.file_size,
                }
                for m in matches
            ],
            "stats": {
                "total_files": stats.total_files,
                "images_scanned": stats.images_scanned,
                "images_failed": stats.images_failed,
                "matches_found": stats.matches_found,
                "elapsed_seconds": stats.elapsed_seconds,
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        # Display results
        if matches:
            print(f"\n🎯 {len(matches)} match(es) found:\n")
            for i, m in enumerate(matches, 1):
                print(f"  [{i}] {m}")
                print()
        else:
            print("\n😔 No matches found with the configured threshold.")
            print(f"   Try lowering the threshold (current: {config.threshold}%).")

        print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
