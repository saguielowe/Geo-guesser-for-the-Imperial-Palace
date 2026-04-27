#!/usr/bin/env python3
"""Phase 0.1 resource fetcher for pano.dpm.org.cn.

Goals:
1) Archive raw coordinates and tour.xml files.
2) Fetch a minimal tile set for 2-3 anchor panoramas.
3) Produce processed scene index for frontend usage.
4) Keep a manifest with status/size/hash for reproducibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_URL = "https://pano.dpm.org.cn"
COORDINATES_URL = f"{BASE_URL}/api/zh-CN/project/coordinates.json"
TOUR_XML_URL = f"{BASE_URL}/api/zh-CN/project/krpano/tour.xml"
ANCHOR_TILE_URLS = [
    f"{BASE_URL}/panoramas/47/krpano/panos/2942_autumn.tiles/f/l1/01/l1_f_01_01.jpg",
    f"{BASE_URL}/panoramas/20/krpano/panos/2038_summer.tiles/r/l3/01/l3_r_01_01.jpg",
    f"{BASE_URL}/panoramas/61/krpano/panos/3222_summer.tiles/l/l2/03/l2_l_03_03.jpg",
]
FACES = ["f", "b", "l", "r", "u", "d"]
DEFAULT_LEVELS = ["l3"]

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        last_err: Optional[Exception] = None
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Phase0Fetcher)",
                "Accept": "*/*",
            },
        )
        for i in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except Exception as err:  # noqa: BLE001
                last_err = err
                if i < self.retries:
                    time.sleep(self.sleep)
        raise RuntimeError(f"GET failed after retries: {url} -> {last_err}")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def parse_anchor(url: str) -> Tuple[int, str, str]:
    # /panoramas/{id}/krpano/panos/{pano_stub}.tiles/...
    m = re.search(r"/panoramas/(\d+)/krpano/panos/([^/.]+)\.tiles/", url)
    if not m:
        raise ValueError(f"Invalid anchor tile url: {url}")
    panorama_id = int(m.group(1))
    pano_stub = m.group(2)
    season = pano_stub.split("_")[-1] if "_" in pano_stub else "unknown"
    return panorama_id, pano_stub, season


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


def parse_tour_scenes(xml_data: bytes) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_data)
    scenes: List[Dict[str, Any]] = []
    for scene in root.iter("scene"):
        attrs = dict(scene.attrib)
        attrs["_xml"] = ET.tostring(scene, encoding="unicode")
        scenes.append(attrs)
    return scenes


def find_scene_for_stub(scenes: List[Dict[str, Any]], pano_stub: str) -> Optional[Dict[str, Any]]:
    for s in scenes:
        joined = " ".join(str(v) for v in s.values())
        if pano_stub in joined:
            return s
    return scenes[0] if scenes else None


def find_scene_from_tour(
    scenes: List[Dict[str, Any]], pano_stub: str, coord_row: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    by_stub = find_scene_for_stub(scenes, pano_stub)
    if by_stub is not None:
        return by_stub

    if coord_row:
        target_scene_name = str(coord_row.get("scene_name", ""))
        target_scene_title = str(coord_row.get("scene_title", ""))
        for scene in scenes:
            if str(scene.get("name", "")) == target_scene_name:
                return scene
            if str(scene.get("title", "")) == target_scene_title:
                return scene
    return None


def load_global_tour(fetcher: Fetcher, raw_dir: Path, manifest: List[DownloadResult]) -> List[Dict[str, Any]]:
    target = raw_dir / "project_tour.xml"
    result = try_download(fetcher, TOUR_XML_URL, target)
    manifest.append(result)
    if result.status == "failed":
        raise RuntimeError(f"Failed to fetch global tour.xml: {result.note}")
    return parse_tour_scenes(target.read_bytes())


def load_coordinates(fetcher: Fetcher, raw_dir: Path, manifest: List[DownloadResult]) -> List[Dict[str, Any]]:
    target = raw_dir / "coordinates.json"
    result = try_download(fetcher, COORDINATES_URL, target)
    manifest.append(result)
    if result.status == "failed":
        raise RuntimeError(f"Failed to fetch coordinates: {result.note}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError(f"coordinates.json returned non-zero code: {payload.get('code')}")
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise RuntimeError("coordinates data is not a list")
    return data


def choose_coordinate_entry(
    coords: List[Dict[str, Any]], panorama_id: int, pano_stub: str, season_hint: str
) -> Optional[Dict[str, Any]]:
    rows = [row for row in coords if int(row.get("panorama_id", -1)) == panorama_id]
    if not rows:
        return None

    id_match = re.match(r"^(\d+)_", pano_stub)
    stub_id = int(id_match.group(1)) if id_match else None

    # Best effort 1: exact scene_id numeric match from pano_stub.
    if stub_id is not None:
        for row in rows:
            try:
                if int(row.get("scene_id", -1)) == stub_id:
                    return row
            except Exception:  # noqa: BLE001
                continue

    # Best effort 2: scene_name contains the full pano_stub token.
    for row in rows:
        if pano_stub in str(row.get("scene_name", "")):
            return row

    # Best effort 3: season contains hint.
    for row in rows:
        seasons = row.get("seasons")
        if isinstance(seasons, list) and season_hint in seasons:
            return row

    return rows[0]


def minimal_tile_urls(panorama_id: int, pano_stub: str, levels: List[str]) -> Iterable[Tuple[str, Path]]:
    for level in levels:
        for face in FACES:
            # We intentionally request one canonical tile per face/level.
            rel = f"panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles/{face}/{level}/01/{level}_{face}_01_01.jpg"
            url = f"{BASE_URL}/{rel}"
            local = Path("panoramas") / str(panorama_id) / "tiles" / pano_stub / face / level / "01" / f"{level}_{face}_01_01.jpg"
            yield url, local


def to_scene_index_entry(
    panorama_id: int,
    pano_stub: str,
    season_hint: str,
    coord_row: Optional[Dict[str, Any]],
    scene_from_tour: Optional[Dict[str, Any]],
    tile_results: List[DownloadResult],
    levels: List[str],
) -> Dict[str, Any]:
    seasons = []
    if coord_row and isinstance(coord_row.get("seasons"), list):
        seasons = coord_row["seasons"]
    if season_hint and season_hint not in seasons:
        seasons = seasons + [season_hint]

    available_tiles = [r.local_path for r in tile_results if r.status in {"downloaded", "skipped_exists"}]
    failed_tiles = [r.url for r in tile_results if r.status == "failed"]

    return {
        "panorama_id": panorama_id,
        "pano_stub": pano_stub,
        "season_hint": season_hint,
        "scene_id": coord_row.get("scene_id") if coord_row else None,
        "scene_name": coord_row.get("scene_name") if coord_row else None,
        "scene_title": coord_row.get("scene_title") if coord_row else None,
        "panorama_name": coord_row.get("panorama_name") if coord_row else None,
        "scene_group_name": coord_row.get("scene_group_name") if coord_row else None,
        "coordinate": coord_row.get("coordinate") if coord_row else None,
        "x_axis": coord_row.get("x_axis") if coord_row else None,
        "y_axis": coord_row.get("y_axis") if coord_row else None,
        "seasons": seasons,
        "tour_scene_name": scene_from_tour.get("name") if scene_from_tour else None,
        "tour_scene_title": scene_from_tour.get("title") if scene_from_tour else None,
        "tile_template": f"panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles/{{face}}/{{level}}/01/{{level}}_{{face}}_01_01.jpg",
        "levels_fetched": levels,
        "available_tile_count": len(available_tiles),
        "failed_tile_count": len(failed_tiles),
    }


def write_json(path: Path, obj: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0.1 resource fetcher")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--sample-size", type=int, default=3, help="How many anchors to process")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=3, help="HTTP retries")
    parser.add_argument("--sleep", type=float, default=1.2, help="Retry interval seconds")
    parser.add_argument(
        "--levels",
        default=",".join(DEFAULT_LEVELS),
        help="Comma-separated tile levels to fetch, e.g. l3 or l1,l2,l3",
    )
    args = parser.parse_args()

    root = Path(args.workspace).resolve()
    raw_dir = root / "data" / "raw"
    processed_dir = root / "data" / "processed"
    logs_dir = root / "logs"
    run_ts = time.strftime("%Y%m%d-%H%M%S")

    fetcher = Fetcher(timeout=args.timeout, retries=args.retries, sleep=args.sleep)
    manifest: List[DownloadResult] = []
    scene_index: List[Dict[str, Any]] = []
    levels = [s.strip() for s in args.levels.split(",") if s.strip()]
    if not levels:
        raise RuntimeError("No levels specified. Use --levels l3 or similar.")

    coords = load_coordinates(fetcher, raw_dir, manifest)
    global_tour_scenes = load_global_tour(fetcher, raw_dir, manifest)

    anchors = ANCHOR_TILE_URLS[: max(1, args.sample_size)]
    for anchor in anchors:
        panorama_id, pano_stub, season_hint = parse_anchor(anchor)

        coord_row = choose_coordinate_entry(coords, panorama_id, pano_stub, season_hint)
        scene_from_tour = find_scene_from_tour(global_tour_scenes, pano_stub, coord_row)

        tile_results: List[DownloadResult] = []
        for tile_url, tile_rel in minimal_tile_urls(panorama_id, pano_stub, levels):
            tile_target = raw_dir / tile_rel
            tile_res = try_download(fetcher, tile_url, tile_target)
            tile_results.append(tile_res)
            manifest.append(tile_res)

        scene_index.append(
            to_scene_index_entry(
                panorama_id=panorama_id,
                pano_stub=pano_stub,
                season_hint=season_hint,
                coord_row=coord_row,
                scene_from_tour=scene_from_tour,
                tile_results=tile_results,
                levels=levels,
            )
        )

    manifest_payload = {
        "generated_at": run_ts,
        "base_url": BASE_URL,
        "coordinates_url": COORDINATES_URL,
        "tour_xml_url": TOUR_XML_URL,
        "levels": levels,
        "entries": [r.__dict__ for r in manifest],
    }
    summary = {
        "generated_at": run_ts,
        "sample_size": len(scene_index),
        "levels": levels,
        "downloaded": sum(1 for r in manifest if r.status == "downloaded"),
        "skipped_exists": sum(1 for r in manifest if r.status == "skipped_exists"),
        "failed": sum(1 for r in manifest if r.status == "failed"),
        "scenes": scene_index,
    }

    write_json(logs_dir / f"phase0-manifest-{run_ts}.json", manifest_payload)
    write_json(processed_dir / "scene_index.phase0.json", scene_index)
    write_json(logs_dir / f"phase0-summary-{run_ts}.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
