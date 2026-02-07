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
from concurrent.futures import ThreadPoolExecutor
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
from .cache import HashCache


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
    use_cache: bool = True
    cache_db_path: Optional[Path] = None
    size_tolerance_pct: Optional[float] = 50.0  # percent; None to disable
    batch_size: int = 500
    io_workers: int = 16
    use_dir_index: bool = True
    refresh_dir_index: bool = False

    def __post_init__(self):
        if self.max_workers <= 0:
            self.max_workers = mp.cpu_count() or 4
        if self.batch_size <= 0:
            self.batch_size = 500
        if self.io_workers <= 0:
            self.io_workers = 16


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


def _chunked(items: list[Path], size: int) -> list[list[Path]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _stat_path(path: Path) -> tuple[Path, int, float]:
    st = path.stat()
    return path, st.st_size, st.st_mtime


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

    # 2. Collect all images from directory (with optional directory index)
    print(f"\n📂 Scanning directory: {search_directory}")
    cache: Optional[HashCache] = None
    if config.use_cache:
        default_db = Path(__file__).resolve().parent.parent / ".photo_finder_cache.sqlite3"
        db_path = config.cache_db_path or default_db
        cache = HashCache(db_path)

    candidates: list[Path]
    if cache and config.use_dir_index and not config.refresh_dir_index:
        cached_index = cache.get_index(search_directory)
        if cached_index is not None:
            candidates = cached_index
        else:
            candidates = collect_image_paths(search_directory)
            cache.replace_index(search_directory, candidates)
    else:
        candidates = collect_image_paths(search_directory)
        if cache and config.use_dir_index:
            cache.replace_index(search_directory, candidates)

    # Exclude reference image early
    candidates = [p for p in candidates if p.resolve() != reference_image.resolve()]
    stats.total_files = len(candidates)
    print(f"   {stats.total_files} images found")

    if stats.total_files == 0:
        stats.elapsed_seconds = time.monotonic() - t_start
        return [], stats

    # 3. Collect file stats asynchronously (I/O bound)
    print(f"\n⚙️  Processing with {config.max_workers} workers...\n")
    stats_map: dict[Path, tuple[int, float]] = {}
    if candidates:
        with ThreadPoolExecutor(max_workers=config.io_workers) as executor:
            for path, size, mtime in executor.map(_stat_path, candidates):
                stats_map[path] = (size, mtime)

    # 5. Optional size pre-filter (based on reference file size)
    ref_size = reference_image.stat().st_size
    if config.size_tolerance_pct is not None:
        tol = max(0.0, config.size_tolerance_pct) / 100.0
        min_size = int(ref_size * (1.0 - tol))
        max_size = int(ref_size * (1.0 + tol))
        candidates = [p for p in candidates if min_size <= stats_map.get(p, (0, 0))[0] <= max_size]
        stats.total_files = len(candidates)
        print(f"   Size filter: {min_size}–{max_size} bytes | {len(candidates)} candidates")

    # 6. Resolve cached hashes
    cached_results: dict[Path, ImageHashResult] = {}
    missing: list[Path] = candidates
    if cache and candidates:
        cached = cache.get_cached(candidates, config.algorithm, config.hash_size)
        cached_results = {}
        missing = []
        for path in candidates:
            cache_entry = cached.get(path)
            if cache_entry is None:
                missing.append(path)
                continue
            size, mtime = stats_map.get(path, (None, None))
            if size == cache_entry.size and mtime == cache_entry.mtime:
                cached_results[path] = HashCache.to_result(cache_entry)
            else:
                missing.append(path)

    # 7. Compute missing hashes in parallel (batching)
    worker_fn = partial(
        _compute_hash_worker,
        algorithm=config.algorithm,
        hash_size=config.hash_size,
    )

    results: list[Optional[ImageHashResult]] = []
    total_to_hash = len(missing)
    if total_to_hash > 0:
        with mp.Pool(processes=config.max_workers) as pool:
            processed = 0
            for chunk in _chunked(missing, config.batch_size):
                chunk_results: list[ImageHashResult] = []
                for result in pool.imap_unordered(worker_fn, chunk):
                    results.append(result)
                    if result is not None:
                        chunk_results.append(result)
                    processed += 1
                    if config.show_progress:
                        _print_progress(processed, total_to_hash, "   Hashing")
                if cache and chunk_results:
                    cache.upsert_many(chunk_results)

    # Merge cached results
    results.extend(cached_results.values())

    # 8. Filter by similarity threshold
    matches: list[MatchResult] = []
    for res in results:
        if res is None:
            stats.images_failed += 1
            continue
        stats.images_scanned += 1

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

    if cache:
        cache.close()

    return matches, stats
