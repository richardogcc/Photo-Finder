# 🖼️ Photo Finder

A command-line tool to find duplicate or similar images using **perceptual hashing**.
Recursively searches a directory and displays all matches against a reference image.

## How it works

It uses **perceptual hashing** algorithms that generate a "fingerprint" for each
image based on its visual content (not raw bytes). This allows detection of images
that are:

- ✅ Exact copies
- ✅ Resized
- ✅ Re-compressed (different JPEG quality)
- ✅ Slightly modified in color/brightness
- ✅ Converted between formats (PNG → JPG)

## Installation

```bash
# Clone or download the project
cd "Photo Finder"

# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install as a package (recommended)
pip install .

# Or install from requirements
pip install -r requirements.txt

# Optional: faster image decoding via libvips
brew install libvips          # macOS
pip install pyvips            # or: pip install ".[fast]"
```

> **Windows note:** Photo Finder uses `multiprocessing` with the *fork*
> start-method (default on macOS/Linux). On Windows the *spawn* method is
> used instead, which requires invoking the tool via
> `python -m photo_finder` so that the `if __name__` guard is respected.
> Core functionality works, but performance and edge-case behavior may
> differ.

## Usage

```bash
# Basic search
python -m photo_finder <reference_image> <search_directory>

# Real-world example
python -m photo_finder vacation_photo.jpg ~/Pictures

# With advanced options
python -m photo_finder photo.jpg ~/Pictures -a perceptual -t 85 -w 8
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `-a`, `--algorithm` | Hash algorithm (`average`, `perceptual`, `difference`, `wavelet`) | `perceptual` |
| `-t`, `--threshold` | Minimum similarity % (0-100) | `90` |
| `--size-tolerance` | Prefilter by file size tolerance % | `50` |
| `--no-size-filter` | Disable size prefilter | `false` |
| `--hash-size` | Hash size (larger = more precise, slower) | `16` |
| `--batch-size` | Batch size for hashing tasks | `500` |
| `-w`, `--workers` | Number of parallel processes (0 = auto) | `0` (auto) |
| `--io-workers` | Number of I/O worker threads | `16` |
| `--cache-db` | Path to SQLite cache DB | `.photo_finder_cache.sqlite3` |
| `--no-cache` | Disable SQLite hash cache | `false` |
| `--no-dir-index` | Disable directory index cache | `false` |
| `--refresh-dir-index` | Rebuild directory index cache | `false` |
| `--no-progress` | Disable progress bar | `false` |
| `--json` | Output results as JSON | `false` |
| `--preset` | Preset: `no-shortcuts`, `medium`, `thorough` | — |
| `--config` | Path to JSON config file | `.photo_finder.json` |

### Available algorithms

| Algorithm | Speed | Accuracy | Best for |
|-----------|-------|----------|----------|
| `average` | ⚡⚡⚡ | ⭐⭐ | Exact duplicates |
| `perceptual` | ⚡⚡ | ⭐⭐⭐ | General use (recommended) |
| `difference` | ⚡⚡⚡ | ⭐⭐ | Gradient detection |
| `wavelet` | ⚡ | ⭐⭐⭐ | Complex transformations |

## Cache & performance

By default, Photo Finder stores hashes in a **SQLite cache** at the project
root (`.photo_finder_cache.sqlite3`) so repeated scans are much faster. The
cache is automatically invalidated when the file size or modification time
changes.

It also maintains a **directory index** (list of image files). If you want to
force a rescan, use `--refresh-dir-index`, or disable it with `--no-dir-index`.

You can also enable a **size prefilter** to reduce the number of files that need
hashing. This is controlled by `--size-tolerance` (percentage around the
reference image file size).

## Presets & config file

You can use presets to avoid long CLI commands:

- `no-shortcuts`: no cache, no directory index, no size prefilter
- `medium`: defaults
- `thorough`: cache + directory index, no size prefilter

You can also create a config file (`.photo_finder.json`) in your working directory:

```json
{
   "preset": "medium",
   "algorithm": "perceptual",
   "threshold": 90,
   "hash_size": 16,
   "max_workers": 0,
   "use_cache": true,
   "use_dir_index": true,
   "size_tolerance_pct": 50,
   "batch_size": 500,
   "io_workers": 16
}
```

## Example output

```
╔══════════════════════════════════════════════════════════╗
║            🖼️  Photo Finder v1.0.0                      ║
╚══════════════════════════════════════════════════════════╝

🔍 Computing reference hash: photo.jpg
   Algorithm: perceptual | Hash: ffc3c3e38181c3ff

📂 Scanning directory: /Users/user/Pictures
   2847 images found

⚙️  Processing with 8 workers...

   Hashing [████████████████████████████████████████] 100.0% (2847/2847)

🎯 3 match(es) found:

  [1]   ✓ /Users/user/Pictures/2024/photo_copy.jpg
        Similarity: 100.0% | Hamming distance: 0 | Size: 2.3 MB

  [2]   ✓ /Users/user/Pictures/backup/photo_small.png
        Similarity: 96.5% | Hamming distance: 9 | Size: 856.0 KB

  [3]   ✓ /Users/user/Pictures/edited/photo_bright.jpg
        Similarity: 91.2% | Hamming distance: 23 | Size: 1.8 MB

────────────────────────────────────────────────────────────
📊 Search Statistics
────────────────────────────────────────────────────────────
  Image files found    : 2847
  Images processed     : 2843
  Images failed        : 4
  Matches found        : 3
  Total time           : 4.52s
  Speed                : 629 img/s
────────────────────────────────────────────────────────────
```

## Supported formats

JPG/JPEG, PNG, BMP, GIF, TIFF, WebP, HEIC, HEIF, AVIF, ICO

## Architecture

```
photo_finder/
├── __init__.py     # Package metadata
├── __main__.py     # CLI (entry point)
├── cache.py        # SQLite hash & directory index cache
├── engine.py       # Parallel search engine
├── hasher.py       # Perceptual hashing and image utilities
└── py.typed        # PEP 561 marker for type checkers
```

## Tests + benchmarks

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run a quick benchmark
python benchmarks/benchmark_search.py <reference_image> <search_directory>
```
