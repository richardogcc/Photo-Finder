"""
CLI – Command-line interface for Photo Finder.

Usage:
    python -m photo_finder <image> <directory> [options]
"""

from __future__ import annotations

import argparse
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
        "--hash-size",
        type=int,
        default=16,
        metavar="N",
        help="Hash size (larger = more precise but slower, default: 16).",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=0,
        metavar="N",
        help="Number of parallel processes (default: auto = CPU count).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar.",
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
    )

    print("╔══════════════════════════════════════════════════════════╗")
    print("║            🖼️  Photo Finder v1.0.0                      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    try:
        matches, stats = search(args.image, args.directory, config)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1

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
