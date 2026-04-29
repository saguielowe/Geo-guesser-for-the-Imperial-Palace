#!/usr/bin/env python3
"""Download pannellum JS/CSS into data/raw/assets/vendor for offline loading.

Usage: python scripts/install_pannellum.py
"""
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data" / "raw" / "assets" / "vendor"
VENDOR_DIR.mkdir(parents=True, exist_ok=True)

FILES = {
    "https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js": "pannellum.js",
    "https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css": "pannellum.css",
}

def download(url: str, dest: Path) -> None:
    print(f"Downloading {url} -> {dest}")
    with urlopen(url) as r, open(dest, "wb") as f:
        f.write(r.read())

def main() -> int:
    for url, name in FILES.items():
        dest = VENDOR_DIR / name
        try:
            download(url, dest)
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return 1
    print("Downloaded pannellum files to", VENDOR_DIR)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
