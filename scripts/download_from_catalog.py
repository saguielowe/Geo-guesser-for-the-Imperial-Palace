#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.phase0_bulk_tiles import Fetcher, download_scene_tiles


def main() -> int:
    parser = argparse.ArgumentParser(description="Download tiles for scenes listed in a catalog JSON")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--catalog", required=True, help="Catalog JSON path (list of scene rows)")
    parser.add_argument("--levels", default="l3", help="Comma levels, e.g. l3")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.8)
    args = parser.parse_args()

    root = Path(args.workspace).resolve()
    catalog_path = (root / args.catalog).resolve()
    scenes = json.loads(catalog_path.read_text(encoding="utf-8"))
    levels = [s.strip() for s in args.levels.split(",") if s.strip()]
    fetcher = Fetcher(timeout=args.timeout, retries=args.retries, sleep=args.sleep)
    raw_dir = root / "data" / "raw"

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    for i, scene in enumerate(scenes, start=1):
        results = download_scene_tiles(fetcher, raw_dir, scene, levels, args.workers)
        downloaded = sum(1 for row in results if row.status == "downloaded")
        skipped = sum(1 for row in results if row.status == "skipped_exists")
        failed = sum(1 for row in results if row.status == "failed")
        total_downloaded += downloaded
        total_skipped += skipped
        total_failed += failed
        print(
            f"scene {i}/{len(scenes)} {scene.get('scene_name')} "
            f"downloaded={downloaded} skipped={skipped} failed={failed}"
        )

    print(
        json.dumps(
            {
                "scene_count": len(scenes),
                "levels": levels,
                "downloaded": total_downloaded,
                "skipped_exists": total_skipped,
                "failed": total_failed,
                "catalog": str(catalog_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if total_failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
