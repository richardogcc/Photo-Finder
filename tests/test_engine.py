from pathlib import Path

import numpy as np
from PIL import Image

from photo_finder.engine import SearchConfig, search
from photo_finder.hasher import HashAlgorithm


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    img = Image.new("RGB", (128, 128), color=color)
    img.save(path)


def _make_noise_image(path: Path, seed: int) -> None:
    """Create a random image with a fixed seed so it's reproducible."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path)


def test_search_finds_similar_images(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    _make_noise_image(ref, seed=42)

    # Exact duplicate
    dup = tmp_path / "dup.png"
    _make_noise_image(dup, seed=42)

    # Completely different image
    other = tmp_path / "other.png"
    _make_noise_image(other, seed=999)

    config = SearchConfig(
        algorithm=HashAlgorithm.PERCEPTUAL,
        threshold=90.0,
        use_cache=False,
        show_progress=False,
        size_tolerance_pct=None,
    )

    matches, stats = search(ref, tmp_path, config)

    paths = {m.candidate.name for m in matches}
    assert "dup.png" in paths
    assert "other.png" not in paths
    assert stats.matches_found == len(matches)


def test_search_no_matches(tmp_path: Path) -> None:
    """When there are no similar images, the result list should be empty."""
    ref = tmp_path / "ref.png"
    _make_noise_image(ref, seed=1)

    other = tmp_path / "other.png"
    _make_noise_image(other, seed=2)

    config = SearchConfig(
        algorithm=HashAlgorithm.PERCEPTUAL,
        threshold=99.0,
        use_cache=False,
        show_progress=False,
        size_tolerance_pct=None,
    )

    matches, stats = search(ref, tmp_path, config)

    assert len(matches) == 0
    assert stats.matches_found == 0


def test_search_empty_directory(tmp_path: Path) -> None:
    """Searching an empty directory returns no matches."""
    ref = tmp_path / "ref.png"
    _make_noise_image(ref, seed=7)

    empty = tmp_path / "empty"
    empty.mkdir()

    config = SearchConfig(
        use_cache=False,
        show_progress=False,
        size_tolerance_pct=None,
    )

    matches, stats = search(ref, empty, config)

    assert matches == []
    assert stats.total_files == 0
