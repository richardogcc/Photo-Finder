"""Photo Finder – Recursive search for similar images using perceptual hashing."""

from importlib.metadata import version as _version, PackageNotFoundError

try:
    __version__: str = _version("photo-finder")
except PackageNotFoundError:  # not installed as a package
    __version__ = "1.0.0"
