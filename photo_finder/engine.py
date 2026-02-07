"""
Parallel search engine for similar images.

Uses multiprocessing to hash images in parallel and
finds matches based on a configurable similarity threshold.
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Optional

from .hasher import (
    HashAlgorithm,
    ImageHashResult,
    MatchResult,
    collect_image_paths,
    compute_hash,
)


def _compute_hash_worker(
    image_path: Path,
    algorithm: HashAlgorithm,
    hash_size: int,
) -> Optional[ImageHashResult]:
    """Multiprocessing worker – computes hash of an image."""
    return compute_hash(image_path, algorithm, hash_size)


@dataclass
class SearchConfig:
    """Search configuration."""
    algorithm: HashAlgorithm = HashAlgorithm.PERCEPTUAL
    hash_size: int = 16
    threshold: float = 90.0       # minimum similarity %
    max_workers: int = 0          # 0 = auto (number of CPUs)
    show_progress: bool = True

    def __post_init__(self):
        if self.max_workers <= 0:
            self.max_workers = mp.cpu_count() or 4


@dataclass
class SearchStats:
    """Search statistics."""
    total_files: int = 0
    images_scanned: int = 0
    images_failed: int = 0
    matches_found: int = 0
    elapsed_seconds: float = 0.0

    def __str__(self) -> str:
        return (
            f"\n{'─' * 60}\n"
            f"📊 Search Statistics\n"
            f"{'─' * 60}\n"
            f"  Image files found    : {self.total_files}\n"
            f"  Images processed     : {self.images_scanned}\n"
            f"  Images failed        : {self.images_failed}\n"
            f"  Matches found        : {self.matches_found}\n"
            f"  Total time           : {self.elapsed_seconds:.2f}s\n"
            f"  Speed                : "
            f"{self.images_scanned / max(self.elapsed_seconds, 0.001):.0f} img/s\n"
            f"{'─' * 60}"
        )


def _print_progress(current: int, total: int, prefix: str = ""):
    """Print progress bar on the same line."""
    bar_len = 40
    filled = int(bar_len * current / max(total, 1))
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = 100 * current / max(total, 1)
    sys.stdout.write(f"\r{prefix} [{bar}] {pct:5.1f}% ({current}/{total})")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def search(
    reference_image: Path,
    search_directory: Path,
    config: Optional[SearchConfig] = None,
) -> tuple[list[MatchResult], SearchStats]:
    """
    Search for images similar to the reference image.

    Args:
        reference_image: Path to the reference image.
        search_directory: Base directory for recursive search.
        config: Search configuration (uses defaults if None).

    Returns:
        Tuple of (list of matches, statistics).

    Raises:
        FileNotFoundError: If the reference image or directory does not exist.
        ValueError: If the reference image cannot be processed.
    """
    if config is None:
        config = SearchConfig()

    # Validation
    if not reference_image.exists():
        raise FileNotFoundError(f"Reference image not found: {reference_image}")
    if not search_directory.is_dir():
        raise FileNotFoundError(f"Search directory not found: {search_directory}")

    stats = SearchStats()
    t_start = time.monotonic()

    # 1. Compute reference image hash
    print(f"\n🔍 Computing reference hash: {reference_image.name}")
    ref_hash = compute_hash(reference_image, config.algorithm, config.hash_size)
    if ref_hash is None:
        raise ValueError(f"Could not process reference image: {reference_image}")
    print(f"   Algorithm: {config.algorithm} | Hash: {ref_hash.hash_value}")

    # 2. Collect all images from directory
    print(f"\n📂 Scanning directory: {search_directory}")
    candidates = collect_image_paths(search_directory)
    stats.total_files = len(candidates)
    print(f"   {stats.total_files} images found")

    if stats.total_files == 0:
        stats.elapsed_seconds = time.monotonic() - t_start
        return [], stats

    # 3. Compute hashes in parallel
    print(f"\n⚙️  Processing with {config.max_workers} workers...\n")
    worker_fn = partial(
        _compute_hash_worker,
        algorithm=config.algorithm,
        hash_size=config.hash_size,
    )

    results: list[Optional[ImageHashResult]] = []
    with mp.Pool(processes=config.max_workers) as pool:
        for i, result in enumerate(pool.imap_unordered(worker_fn, candidates), 1):
            results.append(result)
            if config.show_progress:
                _print_progress(i, stats.total_files, "   Hashing")

    # 4. Filter by similarity threshold
    matches: list[MatchResult] = []
    for res in results:
        if res is None:
            stats.images_failed += 1
            continue
        stats.images_scanned += 1

        # Skip self-comparison
        if res.path.resolve() == reference_image.resolve():
            continue

        similarity = ref_hash.similarity_pct(res)
        if similarity >= config.threshold:
            matches.append(MatchResult(
                reference=reference_image,
                candidate=res.path,
                distance=ref_hash.distance(res),
                similarity_pct=similarity,
                file_size=res.file_size,
            ))

    # Sort by similarity descending
    matches.sort(key=lambda m: m.similarity_pct, reverse=True)
    stats.matches_found = len(matches)
    stats.elapsed_seconds = time.monotonic() - t_start

    return matches, stats
