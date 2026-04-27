#!/usr/bin/env python3

from __future__ import annotations

import json
import mimetypes
import random
import threading
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


def build_tile_template(panorama_id: int, pano_stub: str) -> str:
    return (
        f"/assets/panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles"
        f"/{{face}}/{{level}}/{{row}}/{{level}}_{{face}}_{{row}}_{{col}}.jpg"
    )


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
    coordinate_raw = str(row.get("coordinate") or "")
    coordinate_x, coordinate_y = parse_coordinate(coordinate_raw)
    inventory_row = inventory.get((panorama_id, pano_stub), {})
    widths_desc = row.get("tiled_widths_desc", []) or []
    viewer_max_level = max(1, len(widths_desc) - 1) if len(widths_desc) >= 2 else 1
    viewer_cube_resolution = widths_desc[2]
    viewer_base_path = f"/assets/viewer/panos/{panorama_id}/{pano_stub}"
    viewer_path = "/%s/l%l/%y/%x"

    tile_template = build_tile_template(panorama_id, pano_stub)
    sample_tiles = [
        tile_template.format(face=face, level="l3", row="01", col="01")
        for face in ("f", "b", "l", "r", "u", "d")
    ]

    return {
        "scene_name": row.get("scene_name", ""),
        "scene_title": row.get("scene_title", ""),
        "scene_id": row.get("scene_id"),
        "pano_stub": pano_stub,
        "season_hint": row.get("season_hint", ""),
        "preview_url": row.get("preview_url", ""),
        "preview_asset_url": build_preview_url(str(row.get("preview_url") or "")),
        "panorama_id": panorama_id,
        "panorama_name": row.get("panorama_name", ""),
        "scene_group_name": row.get("scene_group_name", ""),
        "coordinate": coordinate_raw,
        "coordinate_x": coordinate_x,
        "coordinate_y": coordinate_y,
        "x_axis": row.get("x_axis"),
        "y_axis": row.get("y_axis"),
        "seasons": row.get("seasons", []),
        "tile_size": row.get("tile_size", 512),
        "tiled_widths_desc": row.get("tiled_widths_desc", []),
        "tile_url_template": build_viewer_alias_template(panorama_id, pano_stub),
        "viewer": {
            "type": "multires",
            "basePath": viewer_base_path,
            "path": viewer_path,
            "extension": "jpg",
            "tileResolution": row.get("tile_size", 512),
            "maxLevel": viewer_max_level,
            "cubeResolution": viewer_cube_resolution,
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
    base = RAW_DIR / "panoramas" / str(panorama_id) / "tiles" / pano_stub / source_face / level

    def candidate_path(row_token: str, col_token: str) -> Path:
        filename = f"{level}_{source_face}_{row_token}_{col_token}.jpg"
        return base / row_token / filename

    candidates = []
    try:
        row_num = int(row)
        col_num = int(col)
    except ValueError:
        row_num = None
        col_num = None

    if row_num is not None and col_num is not None:
        row_idx = row_num
        col_idx = col_num

        row_dirs = sorted([p.name for p in base.iterdir() if p.is_dir()]) if base.exists() else []
        tile_rows = len(row_dirs)
        tile_cols = 0
        if row_dirs:
            first_row = base / row_dirs[0]
            tile_cols = len(list(first_row.glob(f"{level}_{source_face}_{row_dirs[0]}_*.jpg")))

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

        candidates.extend(
            [
                candidate_path(f"{row_idx + 1:02d}", f"{col_idx + 1:02d}"),
                candidate_path(f"{row_idx:02d}", f"{col_idx:02d}"),
                candidate_path(str(row_idx + 1), str(col_idx + 1)),
                candidate_path(str(row_idx), str(col_idx)),
            ]
        )

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    return candidate_path(f"{row}", f"{col}")


def load_state() -> Dict[str, Any]:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Missing catalog: {CATALOG_PATH}")

    raw_catalog = read_json(CATALOG_PATH)
    if not isinstance(raw_catalog, list):
        raise ValueError("scene catalog must be a list")

    inventory = load_inventory()
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
                        face = parts[6]
                        level = parts[7]
                        row = parts[8] if len(parts) > 8 else ""
                        filename = parts[9] if len(parts) > 9 else ""
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