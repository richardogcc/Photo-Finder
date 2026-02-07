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

# Install dependencies
pip install -r requirements.txt
```

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
| `--hash-size` | Hash size (larger = more precise, slower) | `16` |
| `-w`, `--workers` | Number of parallel processes (0 = auto) | `0` (auto) |
| `--no-progress` | Disable progress bar | `false` |

### Available algorithms

| Algorithm | Speed | Accuracy | Best for |
|-----------|-------|----------|----------|
| `average` | ⚡⚡⚡ | ⭐⭐ | Exact duplicates |
| `perceptual` | ⚡⚡ | ⭐⭐⭐ | General use (recommended) |
| `difference` | ⚡⚡⚡ | ⭐⭐ | Gradient detection |
| `wavelet` | ⚡ | ⭐⭐⭐ | Complex transformations |

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

JPG/JPEG, PNG, BMP, GIF, TIFF, WebP, HEIC, HEIF, AVIF, ICO, SVG

## Architecture

```
photo_finder/
├── __init__.py     # Package metadata
├── __main__.py     # CLI (entry point)
├── hasher.py       # Perceptual hashing and image utilities
└── engine.py       # Parallel search engine
```
