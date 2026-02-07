"""
Perceptual image hashing module.

Supports multiple hash algorithms and enables extremely fast
image similarity comparison.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import imagehash
import numpy as np
from PIL import Image

try:
    import pyvips  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyvips = None

# Supported image extensions
IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".avif", ".ico", ".svg",
})


class HashAlgorithm(str, Enum):
    """Available perceptual hashing algorithms."""
    AVERAGE = "average"       # aHash – fast, good for exact duplicates
    PERCEPTUAL = "perceptual" # pHash – resistant to resizing/compression
    DIFFERENCE = "difference" # dHash – very fast, detects gradient changes
    WAVELET = "wavelet"       # wHash – robust against transformations

    def __str__(self) -> str:
        return self.value


# Algorithm → imagehash function mapping
_HASH_FUNCTIONS = {
    HashAlgorithm.AVERAGE: imagehash.average_hash,
    HashAlgorithm.PERCEPTUAL: imagehash.phash,
    HashAlgorithm.DIFFERENCE: imagehash.dhash,
    HashAlgorithm.WAVELET: imagehash.whash,
}


@dataclass(frozen=True)
class ImageHashResult:
    """Hash result for an image with metadata."""
    path: Path
    hash_value: imagehash.ImageHash
    algorithm: HashAlgorithm
    file_size: int  # bytes

    def distance(self, other: ImageHashResult) -> int:
        """Hamming distance between two hashes (0 = identical)."""
        return self.hash_value - other.hash_value

    def similarity_pct(self, other: ImageHashResult) -> float:
        """Similarity percentage (100.0 = identical)."""
        max_bits = self.hash_value.hash.size
        dist = self.distance(other)
        return max(0.0, (1.0 - dist / max_bits) * 100.0)


@dataclass
class MatchResult:
    """A match found between the reference image and a candidate."""
    reference: Path
    candidate: Path
    distance: int
    similarity_pct: float
    file_size: int

    def __str__(self) -> str:
        return (
            f"  ✓ {self.candidate}\n"
            f"    Similarity: {self.similarity_pct:.1f}% | "
            f"Hamming distance: {self.distance} | "
            f"Size: {_human_size(self.file_size)}"
        )


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def compute_hash(
    image_path: Path,
    algorithm: HashAlgorithm = HashAlgorithm.PERCEPTUAL,
    hash_size: int = 16,
) -> Optional[ImageHashResult]:
    """
    Compute the perceptual hash of an image.

    Args:
        image_path: Path to the image file.
        algorithm: Hashing algorithm to use.
        hash_size: Hash size (larger = more precise, slower).

    Returns:
        ImageHashResult or None if the image cannot be processed.
    """
    try:
        img = _load_image(image_path)
        hash_fn = _HASH_FUNCTIONS[algorithm]
        h = hash_fn(img, hash_size=hash_size)
        return ImageHashResult(
            path=image_path,
            hash_value=h,
            algorithm=algorithm,
            file_size=image_path.stat().st_size,
        )
    except Exception:
        return None


def is_image_file(path: Path) -> bool:
    """Check if a file is an image by its extension."""
    return path.suffix.lower() in IMAGE_EXTENSIONS


def collect_image_paths(directory: Path) -> list[Path]:
    """Recursively collect all image paths in a directory."""
    paths: list[Path] = []
    for root, _dirs, files in os.walk(directory):
        root_path = Path(root)
        for fname in files:
            fpath = root_path / fname
            if is_image_file(fpath):
                paths.append(fpath)
    return paths


def _load_image(image_path: Path) -> Image.Image:
    """Load image using libvips if available, otherwise PIL."""
    if pyvips is not None:
        vimg = pyvips.Image.new_from_file(str(image_path), access="sequential")
        if vimg.bands > 3:
            vimg = vimg[:3]
        if vimg.bands == 1:
            vimg = vimg.colourspace("srgb")
        mem = vimg.write_to_memory()
        arr = np.frombuffer(mem, dtype=np.uint8).reshape(vimg.height, vimg.width, vimg.bands)
        return Image.fromarray(arr, mode="RGB")

    with Image.open(image_path) as img:
        return img.convert("RGB")
