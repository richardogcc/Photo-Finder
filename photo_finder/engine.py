"""
Parallel search engine for similar images.

Uses multiprocessing to hash images in parallel and
finds matches based on a configurable similarity threshold.

Note: on Windows (spawn start-method) the module-level worker function
must be importable from the top level.  This works on macOS/Linux (fork)
out of the box, but Windows users should invoke the tool via
``python -m photo_finder`` so that ``if __name__`` guards are respected.
"""

from __future__ import annotations

import multiprocessing as mp
import signal
import sys
import time
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
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

__all__ = ["SearchConfig", "SearchStats", "search"]


def _compute_hash_worker(
    args: tuple[Path, int, float, HashAlgorithm, int],
) -> Optional[ImageHashResult]:
    """Multiprocessing worker – computes hash of an image.

    Receives a single tuple so that ``pool.imap_unordered`` can pass
    all per-file metadata without needing ``functools.partial``.
    """
    image_path, file_size, file_mtime, algorithm, hash_size = args
    return compute_hash(
        image_path, algorithm, hash_size,
        file_size=file_size, file_mtime=file_mtime,
    )


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


def _chunked(items: list, size: int) -> list[list]:
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

    verbose = config.show_progress  # gate ALL console output (#16)

    def _log(msg: str) -> None:
        if verbose:
            print(msg)

    # Validation
    if not reference_image.exists():
        raise FileNotFoundError(f"Reference image not found: {reference_image}")
    if not search_directory.is_dir():
        raise FileNotFoundError(f"Search directory not found: {search_directory}")

    stats = SearchStats()
    t_start = time.monotonic()
    reference_image = reference_image.resolve()  # normalize (#8)

    # 1. Compute reference image hash
    _log(f"\n🔍 Computing reference hash: {reference_image.name}")
    ref_hash = compute_hash(reference_image, config.algorithm, config.hash_size)
    if ref_hash is None:
        raise ValueError(f"Could not process reference image: {reference_image}")
    _log(f"   Algorithm: {config.algorithm} | Hash: {ref_hash.hash_value}")

    # 2. Collect all images from directory (with optional directory index)
    _log(f"\n📂 Scanning directory: {search_directory}")
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

    # Normalize all candidate paths and exclude reference image (#8)
    candidates = [
        p.resolve() for p in candidates
        if p.resolve() != reference_image
    ]
    stats.total_files = len(candidates)
    _log(f"   {stats.total_files} images found")

    if stats.total_files == 0:
        stats.elapsed_seconds = time.monotonic() - t_start
        if cache:
            cache.close()
        return [], stats

    # 3. Collect file stats asynchronously (I/O bound)
    _log(f"\n⚙️  Processing with {config.max_workers} workers...\n")
    stats_map: dict[Path, tuple[int, float]] = {}
    if candidates:
        with ThreadPoolExecutor(max_workers=config.io_workers) as executor:
            for path, size, mtime in executor.map(_stat_path, candidates):
                stats_map[path] = (size, mtime)

    # 4. Optional size pre-filter (based on reference file size)
    ref_size = reference_image.stat().st_size
    if config.size_tolerance_pct is not None:
        tol = max(0.0, config.size_tolerance_pct) / 100.0
        min_size = int(ref_size * (1.0 - tol))
        max_size = int(ref_size * (1.0 + tol))
        candidates = [
            p for p in candidates
            if min_size <= stats_map.get(p, (0, 0))[0] <= max_size
        ]
        stats.total_files = len(candidates)
        _log(f"   Size filter: {min_size}–{max_size} bytes | {len(candidates)} candidates")

    # 5. Resolve cached hashes
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

    # 6. Compute missing hashes in parallel (batching)
    # Build worker args tuples: (path, size, mtime, algorithm, hash_size)
    worker_args = [
        (
            p,
            stats_map.get(p, (0, 0.0))[0],
            stats_map.get(p, (0, 0.0))[1],
            config.algorithm,
            config.hash_size,
        )
        for p in missing
    ]

    results: list[Optional[ImageHashResult]] = []
    total_to_hash = len(worker_args)
    if total_to_hash > 0:
        # Ignore SIGINT in workers so the parent can handle Ctrl+C (#14)
        original_sigint = signal.getsignal(signal.SIGINT)
        try:
            with mp.Pool(
                processes=config.max_workers,
                initializer=signal.signal,
                initargs=(signal.SIGINT, signal.SIG_IGN),
            ) as pool:
                processed = 0
                for chunk in _chunked(worker_args, config.batch_size):
                    chunk_results: list[ImageHashResult] = []
                    for result in pool.imap_unordered(_compute_hash_worker, chunk):
                        results.append(result)
                        if result is not None:
                            chunk_results.append(result)
                        processed += 1
                        if config.show_progress:
                            _print_progress(processed, total_to_hash, "   Hashing")
                    if cache and chunk_results:
                        cache.upsert_many(chunk_results, hash_size=config.hash_size)
        except KeyboardInterrupt:
            _log("\n\n⚠️  Interrupted – partial results will be returned.")
        finally:
            signal.signal(signal.SIGINT, original_sigint)

    # Merge cached results
    results.extend(cached_results.values())

    # 7. Filter by similarity threshold
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
