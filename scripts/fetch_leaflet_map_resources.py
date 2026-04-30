#!/usr/bin/env python3
"""Download Leaflet runtime and Forbidden City minimap tiles (z1-z5)."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List

BASE_URL = "https://pano.dpm.org.cn"
LEAFLET_JS_URL = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
LEAFLET_CSS_URL = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"


@dataclass
class DownloadResult:
    url: str
    local_path: str
    status: str
    size: int
    note: str = ""


class Fetcher:
    def __init__(self, timeout: int, retries: int, sleep: float):
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep

    def get(self, url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (LeafletMapFetcher)",
                "Accept": "*/*",
            },
        )
        last_err = None
        for i in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except Exception as err:  # noqa: BLE001
                last_err = err
                if i + 1 < self.retries:
                    time.sleep(self.sleep)
        raise RuntimeError(f"GET failed: {url} -> {last_err}")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: object) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def try_download(fetcher: Fetcher, url: str, target: Path) -> DownloadResult:
    ensure_parent(target)
    if target.exists():
        return DownloadResult(url=url, local_path=str(target), status="skipped_exists", size=target.stat().st_size)
    try:
        data = fetcher.get(url)
        target.write_bytes(data)
        return DownloadResult(url=url, local_path=str(target), status="downloaded", size=len(data))
    except Exception as err:  # noqa: BLE001
        return DownloadResult(url=url, local_path=str(target), status="failed", size=0, note=str(err))


def build_tile_jobs(raw_dir: Path, min_zoom: int, max_zoom: int) -> List[tuple[str, Path]]:
    jobs: List[tuple[str, Path]] = []
    for z in range(min_zoom, max_zoom + 1):
        side = 2**z
        for x in range(side):
            for y in range(side):
                url = f"{BASE_URL}/leaflet/tiles/{z}/tile_{x}_{y}.png"
                local = raw_dir / "leaflet" / "tiles" / str(z) / f"tile_{x}_{y}.png"
                jobs.append((url, local))
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch minimap tiles and Leaflet runtime.")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="Project root path.")
    parser.add_argument("--min-zoom", type=int, default=1)
    parser.add_argument("--max-zoom", type=int, default=5)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=0.35)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    raw_dir = workspace / "data" / "raw"
    logs_dir = workspace / "logs"
    vendor_dir = raw_dir / "vendor"
    fetcher = Fetcher(timeout=args.timeout, retries=args.retries, sleep=args.retry_sleep)
    started = time.time()

    manifest: List[DownloadResult] = []

    manifest.append(try_download(fetcher, LEAFLET_JS_URL, vendor_dir / "leaflet.js"))
    manifest.append(try_download(fetcher, LEAFLET_CSS_URL, vendor_dir / "leaflet.css"))

    jobs = build_tile_jobs(raw_dir, args.min_zoom, args.max_zoom)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(try_download, fetcher, url, target) for url, target in jobs]
        for future in concurrent.futures.as_completed(futures):
            manifest.append(future.result())

    summary = {
        "started_at": started,
        "ended_at": time.time(),
        "workspace": str(workspace),
        "min_zoom": args.min_zoom,
        "max_zoom": args.max_zoom,
        "tile_jobs": len(jobs),
        "status_count": {
            "downloaded": sum(1 for row in manifest if row.status == "downloaded"),
            "skipped_exists": sum(1 for row in manifest if row.status == "skipped_exists"),
            "failed": sum(1 for row in manifest if row.status == "failed"),
        },
    }
    ts = time.strftime("%Y%m%d-%H%M%S")
    write_json(logs_dir / f"leaflet-fetch-summary-{ts}.json", summary)
    write_json(
        logs_dir / f"leaflet-fetch-manifest-{ts}.json",
        [row.__dict__ for row in manifest if row.status in {"failed", "downloaded"}],
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status_count"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
