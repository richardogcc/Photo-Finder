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
from typing import Any

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
        default=None,
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
        default=None,
        metavar="PCT",
        help="Minimum similarity percentage (0-100, default: 90).",
    )
    parser.add_argument(
        "--size-tolerance",
        type=float,
        default=None,
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
        default=None,
        metavar="N",
        help="Hash size (larger = more precise but slower, default: 16).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Batch size for hashing tasks (default: 500).",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel processes (default: auto = CPU count).",
    )
    parser.add_argument(
        "--io-workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of I/O worker threads (default: 16).",
    )
    parser.add_argument(
        "--cache-db",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to SQLite cache database (default: .photo_finder_cache.sqlite3 in project root).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable SQLite hash cache.",
    )
    parser.add_argument(
        "--no-dir-index",
        action="store_true",
        help="Disable directory index cache.",
    )
    parser.add_argument(
        "--refresh-dir-index",
        action="store_true",
        help="Rebuild directory index cache.",
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
    parser.add_argument(
        "--preset",
        type=str,
        choices=["no-shortcuts", "medium", "thorough"],
        default=None,
        help="Preset: no-shortcuts, medium, thorough.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to JSON config file (default: .photo_finder.json in CWD).",
    )

    return parser


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_config_path(arg_path: Path | None) -> Path | None:
    if arg_path is not None:
        return arg_path
    candidate = Path.cwd() / ".photo_finder.json"
    return candidate if candidate.exists() else None


def _apply_preset(name: str | None) -> dict[str, Any]:
    if not name:
        return {}
    key = name
    if key == "no-shortcuts":
        return {
            "use_cache": False,
            "use_dir_index": False,
            "size_tolerance_pct": None,
        }
    if key == "thorough":
        return {
            "use_cache": True,
            "use_dir_index": True,
            "size_tolerance_pct": None,
        }
    # medium (default-like)
    return {
        "use_cache": True,
        "use_dir_index": True,
        "size_tolerance_pct": 50.0,
    }


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    defaults = SearchConfig()
    merged: dict[str, Any] = {
        "algorithm": defaults.algorithm,
        "hash_size": defaults.hash_size,
        "threshold": defaults.threshold,
        "max_workers": defaults.max_workers,
        "show_progress": defaults.show_progress,
        "use_cache": defaults.use_cache,
        "cache_db_path": defaults.cache_db_path,
        "size_tolerance_pct": defaults.size_tolerance_pct,
        "batch_size": defaults.batch_size,
        "io_workers": defaults.io_workers,
        "use_dir_index": defaults.use_dir_index,
        "refresh_dir_index": defaults.refresh_dir_index,
    }

    config_path = _resolve_config_path(args.config)
    config_data: dict[str, Any] = _load_config(config_path) if config_path else {}

    preset_name = args.preset or config_data.get("preset")
    merged.update(_apply_preset(preset_name))

    # Apply config file values
    if "algorithm" in config_data:
        merged["algorithm"] = HashAlgorithm(config_data["algorithm"])
    for key in (
        "hash_size",
        "threshold",
        "max_workers",
        "show_progress",
        "use_cache",
        "size_tolerance_pct",
        "batch_size",
        "io_workers",
        "use_dir_index",
        "refresh_dir_index",
    ):
        if key in config_data:
            merged[key] = config_data[key]
    if "cache_db_path" in config_data and config_data["cache_db_path"]:
        merged["cache_db_path"] = Path(config_data["cache_db_path"])

    # Apply CLI overrides
    if args.algorithm is not None:
        merged["algorithm"] = args.algorithm
    if args.hash_size is not None:
        merged["hash_size"] = args.hash_size
    if args.threshold is not None:
        merged["threshold"] = args.threshold
    if args.workers is not None:
        merged["max_workers"] = args.workers
    if args.batch_size is not None:
        merged["batch_size"] = args.batch_size
    if args.io_workers is not None:
        merged["io_workers"] = args.io_workers
    if args.cache_db is not None:
        merged["cache_db_path"] = args.cache_db
    if args.no_cache:
        merged["use_cache"] = False
    if args.no_dir_index:
        merged["use_dir_index"] = False
    if args.refresh_dir_index:
        merged["refresh_dir_index"] = True
    if args.no_size_filter:
        merged["size_tolerance_pct"] = None
    elif args.size_tolerance is not None:
        merged["size_tolerance_pct"] = args.size_tolerance
    if args.no_progress:
        merged["show_progress"] = False

    output_json = bool(config_data.get("json", False))
    if args.json:
        output_json = True

    config = SearchConfig(
        algorithm=merged["algorithm"],
        hash_size=merged["hash_size"],
        threshold=merged["threshold"],
        max_workers=merged["max_workers"],
        show_progress=merged["show_progress"],
        use_cache=merged["use_cache"],
        cache_db_path=merged["cache_db_path"],
        size_tolerance_pct=merged["size_tolerance_pct"],
        batch_size=merged["batch_size"],
        io_workers=merged["io_workers"],
        use_dir_index=merged["use_dir_index"],
        refresh_dir_index=merged["refresh_dir_index"],
    )

    if not output_json:
        print("╔══════════════════════════════════════════════════════════╗")
        print("║            🖼️  Photo Finder v1.0.0                      ║")
        print("╚══════════════════════════════════════════════════════════╝")

    try:
        matches, stats = search(args.image, args.directory, config)
    except KeyboardInterrupt:
        print("\n\n⚠️  Search interrupted by user.", file=sys.stderr)
        return 130
    except (FileNotFoundError, ValueError) as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1

    if output_json:
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
