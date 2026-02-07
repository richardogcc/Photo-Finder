from pathlib import Path

from PIL import Image

from photo_finder.engine import SearchConfig, search
from photo_finder.hasher import HashAlgorithm


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    img = Image.new("RGB", (128, 128), color=color)
    img.save(path)


def test_search_finds_similar_images(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    _make_image(ref, (255, 0, 0))

    dup = tmp_path / "dup.png"
    _make_image(dup, (255, 0, 0))

    other = tmp_path / "other.png"
    _make_image(other, (0, 0, 255))

    config = SearchConfig(
        algorithm=HashAlgorithm.AVERAGE,
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
