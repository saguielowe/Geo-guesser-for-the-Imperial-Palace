#!/usr/bin/env python3

from __future__ import annotations

import json
import mimetypes
import random
import re
import threading
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
FRONTEND_DIR = ROOT / "frontend"
CATALOG_PATH = PROCESSED_DIR / "scene_catalog.mvp20.local.json"
INVENTORY_PATH = PROCESSED_DIR / "local_tiles_inventory.json"
TOUR_XML_PATH = RAW_DIR / "project_tour.xml"


def parse_coordinate(value: str) -> Tuple[Optional[float], Optional[float]]:
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_inventory() -> Dict[Tuple[int, str], Dict[str, Any]]:
    if not INVENTORY_PATH.exists():
        return {}
    payload = read_json(INVENTORY_PATH)
    inventory: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for row in payload:
        panorama_id = row.get("panorama_id")
        pano_stub = row.get("pano_stub")
        if panorama_id is None or not pano_stub:
            continue
        inventory[(int(panorama_id), str(pano_stub))] = row
    return inventory


def parse_level_token(level_value: str) -> Optional[int]:
    token = str(level_value).strip().lower()
    if token.startswith("l"):
        token = token[1:]
    return int(token) if token.isdigit() else None


def parse_level_from_cube_url(cube_url: str) -> Optional[int]:
    match = re.search(r"/l(\d+)(?:/|_)", cube_url)
    if not match:
        return None
    return int(match.group(1))


def load_tour_scene_index() -> Tuple[Dict[str, Dict[str, Any]], Dict[Tuple[int, str], Dict[str, Any]]]:
    if not TOUR_XML_PATH.exists():
        return {}, {}

    root = ET.fromstring(TOUR_XML_PATH.read_text(encoding="utf-8"))
    by_scene: Dict[str, Dict[str, Any]] = {}
    by_pano: Dict[Tuple[int, str], Dict[str, Any]] = {}

    for scene_node in root.findall(".//scene"):
        scene_name = str(scene_node.attrib.get("name") or "").strip()
        if not scene_name:
            continue

        preview_node = scene_node.find("preview")
        preview_url = str(preview_node.attrib.get("url") or "") if preview_node is not None else ""

        multires_image: Optional[ET.Element] = None
        for image_node in scene_node.findall("image"):
            if str(image_node.attrib.get("type") or "").upper() != "CUBE":
                continue
            if str(image_node.attrib.get("multires") or "").lower() != "true":
                continue
            multires_image = image_node
            break

        if multires_image is None:
            continue

        tile_size_raw = multires_image.attrib.get("tilesize")
        tile_size = int(tile_size_raw) if str(tile_size_raw or "").isdigit() else 512

        levels: Dict[int, Dict[str, Any]] = {}
        panorama_id: Optional[int] = None
        pano_stub = ""

        for level_node in multires_image.findall("level"):
            cube_node = level_node.find("cube")
            cube_url = str(cube_node.attrib.get("url") or "") if cube_node is not None else ""
            if not cube_url:
                continue

            level_no = parse_level_from_cube_url(cube_url)
            if level_no is None:
                continue

            tiled_w_raw = str(level_node.attrib.get("tiledimagewidth") or "")
            tiled_h_raw = str(level_node.attrib.get("tiledimageheight") or "")
            tiled_w = int(tiled_w_raw) if tiled_w_raw.isdigit() else 0
            tiled_h = int(tiled_h_raw) if tiled_h_raw.isdigit() else 0

            levels[level_no] = {
                "cube_url": cube_url,
                "tiledimagewidth": tiled_w,
                "tiledimageheight": tiled_h,
            }

            if panorama_id is None or not pano_stub:
                path_match = re.search(r"/panoramas/(\d+)/krpano/panos/([^/]+)\.tiles/", cube_url)
                if path_match:
                    panorama_id = int(path_match.group(1))
                    pano_stub = path_match.group(2)

        if not levels:
            continue

        level_numbers = sorted(levels.keys())
        record = {
            "scene_name": scene_name,
            "preview_url": preview_url,
            "tile_size": tile_size,
            "levels": levels,
            "level_numbers": level_numbers,
            "panorama_id": panorama_id,
            "pano_stub": pano_stub,
        }
        by_scene[scene_name] = record
        if panorama_id is not None and pano_stub:
            by_pano[(panorama_id, pano_stub)] = record

    return by_scene, by_pano


TOUR_SCENE_INDEX, TOUR_PANO_INDEX = load_tour_scene_index()
INVENTORY = load_inventory()


def choose_viewer_level_number(tour_scene: Optional[Dict[str, Any]], inventory_row: Dict[str, Any]) -> int:
    xml_levels = list(tour_scene.get("level_numbers") or []) if tour_scene else []
    local_levels = []
    for key, count in (inventory_row.get("levels") or {}).items():
        if not count:
            continue
        level_no = parse_level_token(str(key))
        if level_no is not None:
            local_levels.append(level_no)

    local_levels = sorted(set(local_levels))
    if xml_levels and local_levels:
        intersection = sorted(level for level in local_levels if level in xml_levels)
        if intersection:
            return intersection[-1]
    if local_levels:
        return local_levels[-1]
    if xml_levels:
        return xml_levels[-1]
    return 1


def pick_local_level_tag(inventory_row: Dict[str, Any], default_tag: str = "l1") -> str:
    level_numbers: List[int] = []
    for key, count in (inventory_row.get("levels") or {}).items():
        if not count:
            continue
        level_no = parse_level_token(str(key))
        if level_no is not None:
            level_numbers.append(level_no)
    if level_numbers:
        return f"l{max(level_numbers)}"
    return default_tag


def inspect_local_level_grid(panorama_id: int, pano_stub: str, level_tag: str, face: str = "f") -> Dict[str, Any]:
    level_dir = RAW_DIR / "panoramas" / str(panorama_id) / "tiles" / pano_stub / face / level_tag
    row_names: List[str] = []
    col_names: List[str] = []

    if level_dir.exists():
        row_dirs = sorted([path for path in level_dir.iterdir() if path.is_dir()], key=lambda path: path.name)
        for row_dir in row_dirs:
            files = sorted(row_dir.glob("*.jpg"))
            if files:
                row_names.append(row_dir.name)

        if row_names:
            first_row = level_dir / row_names[0]
            for file_path in sorted(first_row.glob("*.jpg")):
                stem_parts = file_path.stem.split("_")
                if stem_parts:
                    col_names.append(stem_parts[-1])

    return {
        "row_names": row_names,
        "col_names": col_names,
        "row_count": len(row_names),
        "col_count": len(col_names),
    }


def materialize_cube_url(cube_url_template: str, face: str, row_token: str, col_token: str) -> str:
    # krpano CUBE 模板中会重复使用 %s，并以 %0v / %0h 表示行列索引。
    url = cube_url_template.replace("%s", face)
    url = url.replace("%0v", row_token).replace("%0h", col_token)
    url = url.replace("%v", row_token).replace("%h", col_token)
    return url


def xml_cube_url_to_local_url(cube_url: str, panorama_id: int, pano_stub: str) -> str:
    source_prefix = f"/panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles/"
    local_prefix = f"/panoramas/{panorama_id}/tiles/{pano_stub}/"
    if source_prefix in cube_url:
        return cube_url.replace(source_prefix, local_prefix, 1)
    return cube_url


def select_scene_tour_config(scene_name: str, panorama_id: int, pano_stub: str) -> Optional[Dict[str, Any]]:
    by_name = TOUR_SCENE_INDEX.get(scene_name)
    if by_name:
        return by_name
    return TOUR_PANO_INDEX.get((panorama_id, pano_stub))


def build_viewer_alias_template(panorama_id: int, pano_stub: str) -> str:
    return f"/assets/viewer/panos/{panorama_id}/{pano_stub}/{{face}}/l{{level}}/{{row}}/{{col}}.jpg"


# Pannellum multires 与 krpano CUBE 在面定义 / uv 方向上并不完全一致。
# 提供多套映射模式，便于在本地一键切换调试拼接效果。
MAPPING_PRESETS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "identity": {
        "f": ("f", "id"),
        "b": ("b", "id"),
        "l": ("l", "id"),
        "r": ("r", "id"),
        "u": ("u", "id"),
        "d": ("d", "id"),
    },
    "legacy_adapted": {
        "f": ("u", "flip_xy"),
        "b": ("d", "id"),
        "l": ("r", "swap_fy"),
        "r": ("l", "swap_fx"),
        "u": ("f", "flip_xy"),
        "d": ("b", "id"),
    },
    "swap_lr": {
        "f": ("f", "id"),
        "b": ("b", "id"),
        "l": ("r", "id"),
        "r": ("l", "id"),
        "u": ("u", "id"),
        "d": ("d", "id"),
    },
}
MAPPING_MODE_ORDER = ["identity", "legacy_adapted", "swap_lr"]
CURRENT_MAPPING_MODE = MAPPING_MODE_ORDER[0]
MAPPING_LOCK = threading.Lock()


def get_mapping_payload() -> Dict[str, Any]:
    with MAPPING_LOCK:
        return {
            "current_mode": CURRENT_MAPPING_MODE,
            "modes": MAPPING_MODE_ORDER,
        }


def set_mapping_mode(mode: str) -> str:
    if mode not in MAPPING_PRESETS:
        raise ValueError(f"unknown_mapping_mode: {mode}")
    global CURRENT_MAPPING_MODE  # noqa: PLW0603
    with MAPPING_LOCK:
        CURRENT_MAPPING_MODE = mode
        return CURRENT_MAPPING_MODE


def rotate_mapping_mode() -> str:
    global CURRENT_MAPPING_MODE  # noqa: PLW0603
    with MAPPING_LOCK:
        current_index = MAPPING_MODE_ORDER.index(CURRENT_MAPPING_MODE)
        CURRENT_MAPPING_MODE = MAPPING_MODE_ORDER[(current_index + 1) % len(MAPPING_MODE_ORDER)]
        return CURRENT_MAPPING_MODE


def get_current_face_transforms() -> Dict[str, Tuple[str, str]]:
    with MAPPING_LOCK:
        return MAPPING_PRESETS[CURRENT_MAPPING_MODE]


def build_debug_tile_urls(panorama_id: int, pano_stub: str, source_level: str, row_count: int, col_count: int) -> Dict[str, List[str]]:
    urls: Dict[str, List[str]] = {}
    for face in ("f", "b", "l", "r", "u", "d"):
        face_urls: List[str] = []
        for row_index in range(row_count):
            for col_index in range(col_count):
                face_urls.append(
                    f"/assets/viewer/panos/{panorama_id}/{pano_stub}/{face}/{source_level}/{row_index}/{col_index}.jpg"
                )
        urls[face] = face_urls
    return urls


def build_preview_url(preview_url: str) -> str:
    if not preview_url:
        return ""
    if preview_url.startswith("/"):
        local_path = RAW_DIR / preview_url.lstrip("/")
        if local_path.exists():
            return f"/assets{preview_url}"
        return ""
    return preview_url


def build_scene_record(row: Dict[str, Any], inventory: Dict[Tuple[int, str], Dict[str, Any]]) -> Dict[str, Any]:
    panorama_id = int(row.get("panorama_id") or 0)
    pano_stub = str(row.get("pano_stub") or "")
    scene_name = str(row.get("scene_name") or "")
    coordinate_raw = str(row.get("coordinate") or "")
    coordinate_x, coordinate_y = parse_coordinate(coordinate_raw)
    inventory_row = inventory.get((panorama_id, pano_stub), {})
    tour_scene = select_scene_tour_config(scene_name, panorama_id, pano_stub)

    viewer_level_no = choose_viewer_level_number(tour_scene, inventory_row)
    viewer_local_level_tag = pick_local_level_tag(inventory_row, f"l{viewer_level_no}")
    grid_info = inspect_local_level_grid(panorama_id, pano_stub, viewer_local_level_tag)

    cube_resolution = int(row.get("tile_size") or 512)
    tile_resolution = int(row.get("tile_size") or 512)
    tiled_widths_desc: List[int] = list(row.get("tiled_widths_desc") or [])
    sample_tiles: List[str] = []

    if tour_scene:
        tile_resolution = int(tour_scene.get("tile_size") or tile_resolution)
        level_info = (tour_scene.get("levels") or {}).get(viewer_level_no, {})
        level_width = int(level_info.get("tiledimagewidth") or 0)
        level_height = int(level_info.get("tiledimageheight") or 0)
        cube_resolution = max(level_width, level_height, cube_resolution)
        tiled_widths_desc = sorted(
            [
                int((tour_scene.get("levels") or {}).get(level_no, {}).get("tiledimagewidth") or 0)
                for level_no in (tour_scene.get("level_numbers") or [])
            ],
            reverse=True,
        )
        cube_url_template = str(level_info.get("cube_url") or "")
        if cube_url_template:
            for face in ("f", "b", "l", "r", "u", "d"):
                sample_tiles.append(materialize_cube_url(cube_url_template, face, "01", "01"))

    viewer_base_path = f"/assets/viewer/panos/{panorama_id}/{pano_stub}"
    viewer_path = "/%s/l%l/%y/%x"

    xml_level_numbers = list((tour_scene or {}).get("level_numbers") or [])

    return {
        "scene_name": scene_name,
        "scene_title": row.get("scene_title", ""),
        "scene_id": row.get("scene_id"),
        "pano_stub": pano_stub,
        "season_hint": row.get("season_hint", ""),
        "preview_url": (tour_scene or {}).get("preview_url") or row.get("preview_url", ""),
        "preview_asset_url": build_preview_url(str((tour_scene or {}).get("preview_url") or row.get("preview_url") or "")),
        "panorama_id": panorama_id,
        "panorama_name": row.get("panorama_name", ""),
        "scene_group_name": row.get("scene_group_name", ""),
        "coordinate": coordinate_raw,
        "coordinate_x": coordinate_x,
        "coordinate_y": coordinate_y,
        "x_axis": row.get("x_axis"),
        "y_axis": row.get("y_axis"),
        "seasons": row.get("seasons", []),
        "tile_size": tile_resolution,
        "tiled_widths_desc": tiled_widths_desc,
        "viewer_source_level": viewer_local_level_tag,
        "viewer_source_tile_rows": grid_info["row_count"],
        "viewer_source_tile_cols": grid_info["col_count"],
        "viewer_xml_levels": xml_level_numbers,
        "viewer_debug_tile_urls": build_debug_tile_urls(
            panorama_id,
            pano_stub,
            viewer_local_level_tag,
            grid_info["row_count"],
            grid_info["col_count"],
        ),
        "tile_url_template": build_viewer_alias_template(panorama_id, pano_stub),
        "viewer": {
            "type": "multires",
            "basePath": viewer_base_path,
            "path": "/l%l/%s/%y/%x",
            "extension": "jpg",
            "tileResolution": tile_resolution,
            "maxLevel": max(1, max(xml_level_numbers) if xml_level_numbers else viewer_level_no),
            "cubeResolution": max(cube_resolution, tile_resolution),
            "autoLoad": True,
            "showControls": True,
            "mouseZoom": "fullscreenonly",
            "backgroundColor": [0.04, 0.05, 0.09],
        },
        "sample_tile_urls": sample_tiles,
        "local_tile_count": inventory_row.get("file_count", 0),
        "local_tile_levels": inventory_row.get("levels", {}),
        "local_tile_faces": inventory_row.get("faces", {}),
    }


def resolve_viewer_tile_path(panorama_id: int, pano_stub: str, face: str, level: str, row: str, col: str) -> Path:
    face_transforms = get_current_face_transforms()
    source_face, transform = face_transforms.get(face, (face, "id"))
    tour_scene = TOUR_PANO_INDEX.get((panorama_id, pano_stub))
    if not tour_scene:
        raise FileNotFoundError(f"tour_scene_not_found: panorama_id={panorama_id}, pano_stub={pano_stub}")

    requested_level_no = parse_level_token(level) or 1
    local_level_tag = pick_local_level_tag(INVENTORY.get((panorama_id, pano_stub), {}), f"l{requested_level_no}")
    selected_level_no = parse_level_token(local_level_tag) or requested_level_no
    selected_level_tag = local_level_tag
    level_info = (tour_scene.get("levels") or {}).get(selected_level_no, {})
    cube_url_template = str(level_info.get("cube_url") or "")
    if not cube_url_template:
        raise FileNotFoundError(f"cube_url_missing: scene={tour_scene.get('scene_name')}, level={selected_level_no}")

    grid_info = inspect_local_level_grid(panorama_id, pano_stub, selected_level_tag, source_face)

    try:
        row_num = int(row)
        col_num = int(col)
    except ValueError as err:
        raise FileNotFoundError(f"invalid_row_or_col: row={row}, col={col}") from err

    row_idx = row_num
    col_idx = col_num
    tile_rows = int(grid_info.get("row_count") or 0)
    tile_cols = int(grid_info.get("col_count") or 0)

    if tile_rows > 0 and tile_cols > 0:
        if transform == "flip_xy":
            row_idx = tile_rows - 1 - row_idx
            col_idx = tile_cols - 1 - col_idx
        elif transform == "swap_fy":
            row_idx, col_idx = tile_rows - 1 - col_idx, row_idx
        elif transform == "swap_fx":
            row_idx, col_idx = col_idx, tile_cols - 1 - row_idx

        row_idx = max(0, min(tile_rows - 1, row_idx))
        col_idx = max(0, min(tile_cols - 1, col_idx))

    candidates: List[Path] = []
    row_tokens = [f"{row_idx + 1:02d}", str(row_idx + 1), f"{row_idx:02d}", str(row_idx)]
    col_tokens = [f"{col_idx + 1:02d}", str(col_idx + 1), f"{col_idx:02d}", str(col_idx)]
    seen_paths: set[Path] = set()

    for row_token in row_tokens:
        for col_token in col_tokens:
            rendered_url = materialize_cube_url(cube_url_template, source_face, row_token, col_token)
            rendered_url = xml_cube_url_to_local_url(rendered_url, panorama_id, pano_stub)
            candidate = RAW_DIR / rendered_url.lstrip("/")
            if candidate in seen_paths:
                continue
            seen_paths.add(candidate)
            candidates.append(candidate)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    detail = {
        "scene": tour_scene.get("scene_name"),
        "level": selected_level_no,
        "face": source_face,
        "row": row,
        "col": col,
    }
    raise FileNotFoundError(f"tile_not_found_from_xml_template: {detail}")


def load_state() -> Dict[str, Any]:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Missing catalog: {CATALOG_PATH}")

    raw_catalog = read_json(CATALOG_PATH)
    if not isinstance(raw_catalog, list):
        raise ValueError("scene catalog must be a list")

    inventory = INVENTORY
    scenes = [build_scene_record(row, inventory) for row in raw_catalog]
    scenes.sort(key=lambda item: (item.get("scene_id") or 0, item.get("scene_name") or ""))

    x_values = [scene["coordinate_x"] for scene in scenes if scene["coordinate_x"] is not None]
    y_values = [scene["coordinate_y"] for scene in scenes if scene["coordinate_y"] is not None]
    bounds = {
        "x_min": min(x_values) if x_values else None,
        "x_max": max(x_values) if x_values else None,
        "y_min": min(y_values) if y_values else None,
        "y_max": max(y_values) if y_values else None,
    }

    by_name = {scene["scene_name"]: scene for scene in scenes if scene.get("scene_name")}
    return {
        "scenes": scenes,
        "by_name": by_name,
        "bounds": bounds,
        "inventory_count": len(inventory),
    }


STATE = load_state()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ForbiddenCityMVP/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content_type, _ = mimetypes.guess_type(path.name)
        body = path.read_bytes()
        self._send(HTTPStatus.OK, body, content_type or "application/octet-stream")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        pathname = unquote(parsed.path)

        if pathname == "/" or pathname == "/index.html":
            return self._serve_file(FRONTEND_DIR / "index.html")
        if pathname == "/app.js":
            return self._serve_file(FRONTEND_DIR / "app.js")
        if pathname == "/styles.css":
            return self._serve_file(FRONTEND_DIR / "styles.css")

        if pathname == "/api/health":
            return self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "scene_count": len(STATE["scenes"]),
                    "inventory_count": STATE["inventory_count"],
                },
            )

        if pathname == "/api/config":
            first_scene = STATE["scenes"][0] if STATE["scenes"] else None
            mapping_payload = get_mapping_payload()
            return self._send_json(
                HTTPStatus.OK,
                {
                    "bounds": STATE["bounds"],
                    "scene_count": len(STATE["scenes"]),
                    "inventory_count": STATE["inventory_count"],
                    "default_scene_name": first_scene["scene_name"] if first_scene else None,
                    "mapping_mode": mapping_payload["current_mode"],
                    "mapping_modes": mapping_payload["modes"],
                },
            )

        if pathname == "/api/debug/mapping":
            return self._send_json(HTTPStatus.OK, get_mapping_payload())

        if pathname == "/api/map/stats":
            return self._send_json(
                HTTPStatus.OK,
                {
                    "bounds": STATE["bounds"],
                    "scene_count": len(STATE["scenes"]),
                },
            )

        if pathname == "/api/scenes":
            params = parse_qs(parsed.query)
            limit = params.get("limit", [None])[0]
            items = STATE["scenes"]
            if limit:
                try:
                    limit_value = max(1, int(limit))
                    items = items[:limit_value]
                except ValueError:
                    pass
            return self._send_json(
                HTTPStatus.OK,
                {
                    "total": len(STATE["scenes"]),
                    "items": items,
                },
            )

        if pathname == "/api/scenes/random":
            if not STATE["scenes"]:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "scene_catalog_empty"})
            return self._send_json(HTTPStatus.OK, random.choice(STATE["scenes"]))

        if pathname.startswith("/api/scenes/"):
            scene_name = pathname.removeprefix("/api/scenes/")
            scene = STATE["by_name"].get(scene_name)
            if not scene:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "scene_not_found", "scene_name": scene_name})
            return self._send_json(HTTPStatus.OK, scene)

        if pathname.startswith("/assets/"):
            if pathname.startswith("/assets/viewer/panos/"):
                parts = pathname.split("/")
                if len(parts) >= 8:
                    try:
                        panorama_id = int(parts[4])
                        pano_stub = parts[5]
                        # Handle both formats: {face}/l{level}/{row}/{col} and /l{level}/{face}/{row}/{col}
                        if parts[6].startswith("l"):
                            # Format 2: /l{level}/{face}/{row}/{col}
                            level_part = parts[6]
                            face = parts[7]
                            row = parts[8] if len(parts) > 8 else ""
                            filename = parts[9] if len(parts) > 9 else ""
                        else:
                            # Format 1: /{face}/l{level}/{row}/{col}
                            face = parts[6]
                            level_part = parts[7]
                            row = parts[8] if len(parts) > 8 else ""
                            filename = parts[9] if len(parts) > 9 else ""
                        
                        # Handle both "l3" and "3" format
                        if level_part.startswith("l"):
                            level = level_part
                        else:
                            level = f"l{level_part}"
                        
                        col = filename.rsplit(".", 1)[0] if filename else ""
                        tile_path = resolve_viewer_tile_path(panorama_id, pano_stub, face, level, row, col)
                        return self._serve_file(tile_path)
                    except Exception as err:  # noqa: BLE001
                        return self._send_json(HTTPStatus.NOT_FOUND, {"error": "viewer_tile_route_error", "detail": str(err)})
            asset_path = pathname.removeprefix("/assets/")
            return self._serve_file(RAW_DIR / asset_path)

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": pathname})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        pathname = unquote(parsed.path)

        if pathname == "/api/debug/mapping":
            try:
                payload = self._read_json_body()
                action = str(payload.get("action") or "")
                mode = str(payload.get("mode") or "")

                if action == "next":
                    current_mode = rotate_mapping_mode()
                elif mode:
                    current_mode = set_mapping_mode(mode)
                else:
                    current_mode = get_mapping_payload()["current_mode"]

                return self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "current_mode": current_mode,
                        "modes": MAPPING_MODE_ORDER,
                    },
                )
            except ValueError as err:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
            except json.JSONDecodeError:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": pathname})


def main() -> int:
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Serving on http://{host}:{port}")
    print(f"Scenes: {len(STATE['scenes'])} | Inventory entries: {STATE['inventory_count']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())