#!/usr/bin/env python3
"""Phase 0.2 bulk scene discovery and tile downloader.

This script discovers scenes automatically from global tour.xml and coordinates.json,
then optionally downloads tile images for selected levels.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_URL = "https://pano.dpm.org.cn"
COORDINATES_URL = f"{BASE_URL}/api/zh-CN/project/coordinates.json"
TOUR_XML_URL = f"{BASE_URL}/api/zh-CN/project/krpano/tour.xml"
FACES = ["f", "b", "l", "r", "u", "d"]
DEFAULT_LEVELS = ["l3"]


@dataclass
class DownloadResult:
    url: str
    local_path: str
    status: str
    size: int
    sha256: str
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
                "User-Agent": "Mozilla/5.0 (Phase0BulkTiles)",
                "Accept": "*/*",
            },
        )
        last_err: Optional[Exception] = None
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def try_download(fetcher: Fetcher, url: str, target: Path) -> DownloadResult:
    ensure_parent(target)
    if target.exists():
        return DownloadResult(
            url=url,
            local_path=str(target),
            status="skipped_exists",
            size=target.stat().st_size,
            sha256=sha256_file(target),
        )
    try:
        data = fetcher.get(url)
        target.write_bytes(data)
        return DownloadResult(
            url=url,
            local_path=str(target),
            status="downloaded",
            size=len(data),
            sha256=sha256_bytes(data),
        )
    except Exception as err:  # noqa: BLE001
        return DownloadResult(
            url=url,
            local_path=str(target),
            status="failed",
            size=0,
            sha256="",
            note=str(err),
        )


def load_coordinates(fetcher: Fetcher, raw_dir: Path, manifest: List[DownloadResult]) -> List[Dict[str, Any]]:
    target = raw_dir / "coordinates.json"
    res = try_download(fetcher, COORDINATES_URL, target)
    manifest.append(res)
    if res.status == "failed":
        raise RuntimeError(f"Failed to fetch coordinates.json: {res.note}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise RuntimeError("coordinates data is not a list")
    return data


def load_tour(fetcher: Fetcher, raw_dir: Path, manifest: List[DownloadResult]) -> ET.Element:
    target = raw_dir / "project_tour.xml"
    res = try_download(fetcher, TOUR_XML_URL, target)
    manifest.append(res)
    if res.status == "failed":
        raise RuntimeError(f"Failed to fetch project tour.xml: {res.note}")
    return ET.fromstring(target.read_bytes())


def scene_stub_from_scene_name(scene_name: str) -> str:
    # scene_2038_summer -> 2038_summer
    if scene_name.startswith("scene_"):
        return scene_name[len("scene_") :]
    return scene_name


def parse_panorama_id_from_preview(preview_url: str) -> Optional[int]:
    m = re.search(r"/panoramas/(\d+)/", preview_url)
    return int(m.group(1)) if m else None


def parse_scene_records(tour_root: ET.Element) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for scene in tour_root.iter("scene"):
        scene_name = scene.attrib.get("name", "")
        scene_title = scene.attrib.get("title", "")
        preview_node = scene.find("preview")
        image_node = scene.find("image")
        preview_url = preview_node.attrib.get("url", "") if preview_node is not None else ""
        panorama_id = parse_panorama_id_from_preview(preview_url)

        tiled_widths: List[int] = []
        tile_size = 512
        if image_node is not None:
            if image_node.attrib.get("tilesize"):
                try:
                    tile_size = int(image_node.attrib.get("tilesize", "512"))
                except Exception:  # noqa: BLE001
                    tile_size = 512
            for lv in image_node.findall("level"):
                try:
                    w = int(lv.attrib.get("tiledimagewidth", "0"))
                    if w > 0:
                        tiled_widths.append(w)
                except Exception:  # noqa: BLE001
                    continue

        tiled_widths = sorted(set(tiled_widths), reverse=True)
        records.append(
            {
                "scene_name": scene_name,
                "scene_title": scene_title,
                "pano_stub": scene_stub_from_scene_name(scene_name),
                "season_hint": scene_name.split("_")[-1] if "_" in scene_name else "unknown",
                "preview_url": preview_url,
                "panorama_id": panorama_id,
                "tile_size": tile_size,
                "tiled_widths_desc": tiled_widths,
            }
        )
    return records


def build_coordinate_index(coords: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(c.get("scene_name", "")): c for c in coords if c.get("scene_name")}


def choose_width_for_level(widths_desc: List[int], level_label: str) -> Optional[int]:
    if not widths_desc:
        return None

    # Empirical mapping for this dataset:
    # many scenes have 4 widths (e.g. 5184/2624/1280/640) but published files are l3/l2/l1 = 2624/1280/640.
    if len(widths_desc) >= 4:
        level_map = {
            "l3": widths_desc[1],
            "l2": widths_desc[2],
            "l1": widths_desc[3],
        }
    elif len(widths_desc) == 3:
        level_map = {
            "l3": widths_desc[0],
            "l2": widths_desc[1],
            "l1": widths_desc[2],
        }
    elif len(widths_desc) == 2:
        level_map = {
            "l3": widths_desc[0],
            "l2": widths_desc[1],
            "l1": widths_desc[1],
        }
    else:
        level_map = {
            "l3": widths_desc[0],
            "l2": widths_desc[0],
            "l1": widths_desc[0],
        }
    return level_map.get(level_label, widths_desc[0])


def iter_tile_urls(scene: Dict[str, Any], levels: List[str]) -> Iterable[Tuple[str, Path, str, int, int]]:
    panorama_id = scene["panorama_id"]
    pano_stub = scene["pano_stub"]
    tile_size = scene["tile_size"]
    widths_desc = scene["tiled_widths_desc"]

    if panorama_id is None:
        return

    for lv in levels:
        width = choose_width_for_level(widths_desc, lv)
        if not width:
            continue
        tiles_per_axis = max(1, math.ceil(width / tile_size))
        for face in FACES:
            for row in range(1, tiles_per_axis + 1):
                row_s = f"{row:02d}"
                for col in range(1, tiles_per_axis + 1):
                    col_s = f"{col:02d}"
                    rel = (
                        f"panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles/"
                        f"{face}/{lv}/{row_s}/{lv}_{face}_{row_s}_{col_s}.jpg"
                    )
                    url = f"{BASE_URL}/{rel}"
                    local = (
                        Path("panoramas")
                        / str(panorama_id)
                        / "tiles"
                        / pano_stub
                        / face
                        / lv
                        / row_s
                        / f"{lv}_{face}_{row_s}_{col_s}.jpg"
                    )
                    yield url, local, lv, row, col


def download_scene_tiles(
    fetcher: Fetcher,
    raw_dir: Path,
    scene: Dict[str, Any],
    levels: List[str],
    workers: int,
) -> List[DownloadResult]:
    tasks = [(url, raw_dir / rel) for (url, rel, _lv, _r, _c) in iter_tile_urls(scene, levels)]
    if not tasks:
        return []

    results: List[DownloadResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = [ex.submit(try_download, fetcher, url, target) for (url, target) in tasks]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    return results


def merge_scene_with_coordinates(scene: Dict[str, Any], cidx: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    coord = cidx.get(scene["scene_name"])
    merged = dict(scene)
    if coord:
        merged.update(
            {
                "scene_id": coord.get("scene_id"),
                "panorama_name": coord.get("panorama_name"),
                "scene_group_name": coord.get("scene_group_name"),
                "coordinate": coord.get("coordinate"),
                "x_axis": coord.get("x_axis"),
                "y_axis": coord.get("y_axis"),
                "seasons": coord.get("seasons", []),
            }
        )
    else:
        merged.update(
            {
                "scene_id": None,
                "panorama_name": None,
                "scene_group_name": None,
                "coordinate": None,
                "x_axis": None,
                "y_axis": None,
                "seasons": [scene.get("season_hint")],
            }
        )
    return merged


def summarize_estimate(scenes: List[Dict[str, Any]], levels: List[str]) -> Dict[str, Any]:
    total_tiles = 0
    by_level: Dict[str, int] = {lv: 0 for lv in levels}
    for sc in scenes:
        widths = sc.get("tiled_widths_desc", [])
        tile_size = sc.get("tile_size", 512)
        for lv in levels:
            w = choose_width_for_level(widths, lv)
            if not w:
                continue
            n = max(1, math.ceil(w / tile_size))
            cnt = 6 * n * n
            by_level[lv] += cnt
            total_tiles += cnt
    return {
        "scene_count": len(scenes),
        "levels": levels,
        "estimated_total_tiles": total_tiles,
        "estimated_by_level": by_level,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0.2 bulk scene discovery and tile downloader")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--levels", default=",".join(DEFAULT_LEVELS), help="Comma levels: l1,l2,l3")
    parser.add_argument("--scene-limit", type=int, default=0, help="Limit scenes for downloading (0 means all)")
    parser.add_argument("--download-mode", choices=["none", "full"], default="none", help="Download mode")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout")
    parser.add_argument("--retries", type=int, default=3, help="HTTP retries")
    parser.add_argument("--sleep", type=float, default=0.8, help="Retry wait seconds")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent download workers for full mode")
    parser.add_argument(
        "--exclude-panorama-ids",
        default="",
        help="Comma panorama ids to skip, e.g. 20,47",
    )
    parser.add_argument(
        "--scene-name-contains",
        default="",
        help="Optional substring filter for scene_name (case-insensitive)",
    )
    parser.add_argument(
        "--allow-all",
        action="store_true",
        help="Allow full download for all discovered scenes when scene-limit is 0",
    )
    args = parser.parse_args()

    root = Path(args.workspace).resolve()
    raw_dir = root / "data" / "raw"
    processed_dir = root / "data" / "processed"
    logs_dir = root / "logs"

    run_ts = time.strftime("%Y%m%d-%H%M%S")
    levels = [s.strip() for s in args.levels.split(",") if s.strip()]
    if not levels:
        raise RuntimeError("No levels specified")

    fetcher = Fetcher(timeout=args.timeout, retries=args.retries, sleep=args.sleep)
    manifest: List[DownloadResult] = []

    coords = load_coordinates(fetcher, raw_dir, manifest)
    tour_root = load_tour(fetcher, raw_dir, manifest)

    scenes_raw = parse_scene_records(tour_root)
    cidx = build_coordinate_index(coords)
    scenes = [merge_scene_with_coordinates(sc, cidx) for sc in scenes_raw if sc.get("panorama_id") is not None]

    catalog_path = processed_dir / "scene_catalog.phase0.json"
    write_json(catalog_path, scenes)

    estimate = summarize_estimate(scenes, levels)

    exclude_panorama_ids = {
        int(token.strip())
        for token in str(args.exclude_panorama_ids).split(",")
        if token.strip().isdigit()
    }
    scene_name_contains = str(args.scene_name_contains or "").strip().lower()

    filtered = scenes
    if exclude_panorama_ids:
        filtered = [sc for sc in filtered if int(sc.get("panorama_id") or -1) not in exclude_panorama_ids]
    if scene_name_contains:
        filtered = [sc for sc in filtered if scene_name_contains in str(sc.get("scene_name") or "").lower()]

    selected = filtered
    if args.scene_limit > 0:
        selected = filtered[: args.scene_limit]

    if args.download_mode == "full" and args.scene_limit == 0 and not args.allow_all:
        raise RuntimeError(
            "Refusing to full-download all scenes without explicit confirmation. "
            "Use --allow-all to continue, or set --scene-limit for MVP-sized runs."
        )

    tile_manifest: List[DownloadResult] = []
    if args.download_mode == "full":
        for i, sc in enumerate(selected, start=1):
            scene_results = download_scene_tiles(fetcher, raw_dir, sc, levels, args.workers)
            tile_manifest.extend(scene_results)
            print(
                f"scene {i}/{len(selected)}: {sc.get('scene_name')} -> "
                f"downloaded={sum(1 for r in scene_results if r.status == 'downloaded')} "
                f"skipped={sum(1 for r in scene_results if r.status == 'skipped_exists')} "
                f"failed={sum(1 for r in scene_results if r.status == 'failed')}"
            )

    summary = {
        "generated_at": run_ts,
        "levels": levels,
        "download_mode": args.download_mode,
        "scene_count_total": len(scenes),
        "scene_count_filtered": len(filtered),
        "scene_count_selected": len(selected),
        "estimate": estimate,
        "downloaded": sum(1 for r in tile_manifest if r.status == "downloaded"),
        "skipped_exists": sum(1 for r in tile_manifest if r.status == "skipped_exists"),
        "failed": sum(1 for r in tile_manifest if r.status == "failed"),
    }

    full_manifest = {
        "generated_at": run_ts,
        "coordinates_url": COORDINATES_URL,
        "tour_xml_url": TOUR_XML_URL,
        "base_url": BASE_URL,
        "meta_entries": [m.__dict__ for m in manifest],
        "tile_entries": [m.__dict__ for m in tile_manifest],
    }

    write_json(logs_dir / f"phase0-bulk-summary-{run_ts}.json", summary)
    write_json(logs_dir / f"phase0-bulk-manifest-{run_ts}.json", full_manifest)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
