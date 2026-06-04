"""后台资源管理：下载队列、预取、清理与占用统计。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
PANORAMAS_DIR = RAW_DIR / "panoramas"
LEAFLET_DIR = RAW_DIR / "leaflet"

ANCHOR_CATALOG_PATH = PROCESSED_DIR / "scene_catalog.demo_anchors.local.json"
KNOWLEDGE_PATH = PROCESSED_DIR / "scene_knowledge.json"
ANCHOR_POINTS_PATH = PROCESSED_DIR / "map_anchor_points.captured.json"

# ---- 缓存 ----
_cache_lock = threading.Lock()
_usage_cache: Optional[Dict[str, Any]] = None
_usage_cache_ts: float = 0.0
USAGE_CACHE_TTL = 120  # 秒


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _get_anchored_scenes() -> Set[str]:
    """返回已锚点的 scene_name 集合。"""
    anchored: Set[str] = set()
    catalog = _read_json(ANCHOR_CATALOG_PATH)
    if isinstance(catalog, list):
        for row in catalog:
            name = str(row.get("scene_name") or "").strip()
            if name:
                anchored.add(name)
    points = _read_json(ANCHOR_POINTS_PATH)
    if isinstance(points, list):
        for row in points:
            name = str(row.get("scene_name") or "").strip()
            if name:
                anchored.add(name)
    return anchored


def _has_pixel_coord(scene: Dict[str, Any]) -> bool:
    """场景是否有 click_pixel_xy 或 user_x/y 坐标（即有 pixel 级锚点）。"""
    if scene.get("click_pixel_xy"):
        return True
    ux = scene.get("user_x")
    uy = scene.get("user_y")
    if ux is not None and uy is not None:
        try:
            if float(ux) and float(uy):
                return True
        except (ValueError, TypeError):
            pass
    return False


def _count_pano_bytes(scene_dir: Path) -> int:
    """递归统计全景目录占用字节数。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(scene_dir):
            for f in files:
                try:
                    total += (scene_dir / root / f).stat().st_size if root != str(scene_dir) else (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


# Python 3.12+ walk 兼容
try:
    _os_walk = os.walk
except Exception:
    pass


def _count_dir_bytes(dir_path: Path) -> int:
    total = 0
    if not dir_path.exists():
        return 0
    for root, _dirs, files in os.walk(str(dir_path)):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def compute_usage(force: bool = False) -> Dict[str, Any]:
    """计算磁盘占用统计，缓存 120 秒。"""
    global _usage_cache, _usage_cache_ts
    now = time.time()
    with _cache_lock:
        if not force and _usage_cache is not None and (now - _usage_cache_ts) < USAGE_CACHE_TTL:
            return _usage_cache

    pano_mb = 0.0
    other_mb = 0.0

    # 全景瓦片
    if PANORAMAS_DIR.exists():
        for pid_dir in PANORAMAS_DIR.iterdir():
            if not pid_dir.is_dir():
                continue
            pano_mb += _count_dir_bytes(pid_dir) / (1024 * 1024)

    # 其它资源（宫图、JSON、脚本等）
    for entry in RAW_DIR.iterdir():
        if entry.name == "panoramas":
            continue
        if entry.is_dir():
            other_mb += _count_dir_bytes(entry) / (1024 * 1024)
        elif entry.is_file():
            try:
                other_mb += entry.stat().st_size / (1024 * 1024)
            except OSError:
                pass

    with _cache_lock:
        _usage_cache = {
            "pano_mb": round(pano_mb, 1),
            "other_mb": round(other_mb, 1),
            "total_mb": round(pano_mb + other_mb, 1),
            "cached_at": now,
        }
        _usage_cache_ts = now
    return _usage_cache


def _get_scene_pano_dir(scene: Dict[str, Any]) -> Optional[Path]:
    pid = scene.get("panorama_id")
    stub = scene.get("pano_stub")
    if pid and stub:
        return PANORAMAS_DIR / str(pid) / "tiles" / str(stub)
    return None


def list_local_scenes(catalog: List[Dict[str, Any]]) -> List[str]:
    """返回本地已有瓦片的 scene_name 列表。"""
    local: List[str] = []
    for row in catalog:
        d = _get_scene_pano_dir(row)
        if d and d.exists():
            local.append(str(row.get("scene_name") or ""))
    return [n for n in local if n]


def prefetch_scenes(
    catalog: List[Dict[str, Any]],
    *,
    max_scenes: int = 5,
    anchored: Optional[Set[str]] = None,
) -> List[str]:
    """
    预取策略：优先已锚点 / 有 pixel 坐标的场景，其次非夏季，
    跳过已本地存在的。
    """
    if anchored is None:
        anchored = _get_anchored_scenes()

    local_set = set(list_local_scenes(catalog))

    def _priority(scene: Dict[str, Any]) -> Tuple[int, int]:
        name = str(scene.get("scene_name") or "")
        score = 0
        if name in anchored:
            score += 100
        if _has_pixel_coord(scene):
            score += 50
        season = str(scene.get("season_hint") or "").lower()
        if season and season != "summer":
            score += 10
        return (-score, 0)

    candidates = [s for s in catalog if str(s.get("scene_name") or "") not in local_set]
    candidates.sort(key=_priority)
    return [str(s.get("scene_name") or "") for s in candidates[:max_scenes]]


def prune_scenes(
    catalog: List[Dict[str, Any]],
    *,
    max_mb: Optional[float] = None,
    max_scenes: Optional[int] = None,
    anchored: Optional[Set[str]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    清理策略：按场景数或容量清理，保护已锚点场景。
    返回清理结果摘要。
    """
    if anchored is None:
        anchored = _get_anchored_scenes()

    usage = compute_usage(force=True)
    local_names = list_local_scenes(catalog)
    # 构建 name → dir 映射
    name_to_dir: Dict[str, Path] = {}
    name_to_size: Dict[str, float] = {}
    for row in catalog:
        name = str(row.get("scene_name") or "")
        d = _get_scene_pano_dir(row)
        if name and d and d.exists() and name in local_names:
            name_to_dir[name] = d
            name_to_size[name] = _count_dir_bytes(d) / (1024 * 1024)

    # 排序：非锚点优先清理，然后按大小降序
    def _prune_key(name: str) -> Tuple[int, float]:
        return (0 if name in anchored else 1, -name_to_size.get(name, 0))

    sorted_names = sorted(local_names, key=_prune_key)

    pruned: List[str] = []
    freed_mb = 0.0
    remaining_count = len(sorted_names)

    for name in sorted_names:
        if max_scenes is not None and remaining_count <= max_scenes:
            break
        if max_mb is not None and usage["total_mb"] - freed_mb <= max_mb:
            break
        if name in anchored:
            continue
        d = name_to_dir.get(name)
        if d and d.exists():
            sz = name_to_size.get(name, 0)
            if not dry_run:
                try:
                    shutil.rmtree(str(d))
                except OSError:
                    continue
            pruned.append(name)
            freed_mb += sz
            remaining_count -= 1

    return {
        "pruned": pruned,
        "pruned_count": len(pruned),
        "freed_mb": round(freed_mb, 1),
        "dry_run": dry_run,
        "remaining_local_scenes": remaining_count,
        "total_mb_after": round(usage["total_mb"] - freed_mb, 1),
    }


def load_knowledge() -> List[Dict[str, Any]]:
    """加载建筑知识题库。"""
    data = _read_json(KNOWLEDGE_PATH)
    if isinstance(data, list):
        return data
    return []


def load_anchor_catalog() -> Optional[List[Dict[str, Any]]]:
    """加载锚点题库 catalog（优先使用）。"""
    data = _read_json(ANCHOR_CATALOG_PATH)
    if isinstance(data, list):
        return data
    return None


class DownloadQueue:
    """简化的后台下载队列。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: List[str] = []  # scene_name 列表
        self._active: bool = False
        self._current: Optional[str] = None
        self._completed: List[str] = []
        self._failed: List[Tuple[str, str]] = []  # (name, reason)
        self._progress: Dict[str, float] = {}  # scene_name → 0..1

    def enqueue(self, scene_names: List[str]) -> int:
        with self._lock:
            added = 0
            for name in scene_names:
                if name not in self._queue and name not in self._completed:
                    self._queue.append(name)
                    added += 1
            return added

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "current": self._current,
                "queued": len(self._queue),
                "completed": len(self._completed),
                "failed": len(self._failed),
                "queue": list(self._queue),
                "failed_items": [
                    {"scene_name": name, "reason": reason}
                    for name, reason in self._failed[-5:]  # 最近 5 条
                ],
                "progress": dict(self._progress),
            }

    def start(self, catalog: List[Dict[str, Any]]) -> None:
        """启动后台下载线程。"""
        with self._lock:
            if self._active:
                return
            self._active = True

        def _worker() -> None:
            while True:
                with self._lock:
                    if not self._queue:
                        self._active = False
                        self._current = None
                        return
                    name = self._queue.pop(0)
                    self._current = name
                    self._progress[name] = 0.0

                try:
                    self._download_scene(name, catalog)
                    with self._lock:
                        self._completed.append(name)
                        self._progress[name] = 1.0
                except Exception as exc:
                    with self._lock:
                        self._failed.append((name, str(exc)))
                        self._progress[name] = -1.0

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _download_scene(self, scene_name: str, catalog: List[Dict[str, Any]]) -> None:
        """调用现有下载脚本下载单个场景。"""
        script = ROOT / "scripts" / "download_from_catalog.py"
        if not script.exists():
            raise FileNotFoundError(f"下载脚本不存在: {script}")

        # 从 catalog 中找到场景行
        scene_row = None
        for row in catalog:
            if str(row.get("scene_name") or "") == scene_name:
                scene_row = row
                break
        if scene_row is None:
            raise ValueError(f"场景 {scene_name} 不在 catalog 中，无法下载")

        # 检查磁盘空间（至少 100 MB 余量）
        try:
            check_dir = PANORAMAS_DIR if PANORAMAS_DIR.exists() else DATA_DIR
            usage = shutil.disk_usage(str(check_dir))
            free_mb = usage.free / (1024 * 1024)
            if free_mb < 100:
                raise OSError(f"磁盘空间不足：仅剩 {free_mb:.0f} MB（需要至少 100 MB）")
        except OSError:
            raise  # 磁盘空间不足，直接抛出
        except Exception:
            pass  # disk_usage 偶发失败（如权限）不阻塞下载

        # 创建临时 catalog 文件（只含该场景）
        tmp_path = PROCESSED_DIR / f"_tmp_download_{scene_name}.json"
        try:
            tmp_path.write_text(
                json.dumps([scene_row], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 带指数退避重试（最多 3 次）
            max_retries = 3
            last_error = ""
            for attempt in range(max_retries):
                try:
                    result = subprocess.run(
                        [
                            sys.executable, str(script),
                            "--catalog", str(tmp_path),
                            "--levels", "l3",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=600,
                        cwd=str(ROOT),
                    )
                    if result.returncode == 0:
                        return  # 成功
                    last_error = (
                        result.stderr.strip()
                        or result.stdout.strip()
                        or f"exit {result.returncode}"
                    )
                except subprocess.TimeoutExpired:
                    last_error = f"下载超时（第 {attempt + 1}/{max_retries} 次）"
                except Exception as exc:
                    last_error = str(exc)

                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))  # 2s, 4s 退避

            raise RuntimeError(last_error or "下载失败（已达最大重试次数）")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


# ---- 场景播放记录 ----
PLAYED_SCENES_PATH = PROCESSED_DIR / "played_scenes.json"
_played_cache: Optional[Set[str]] = None
_played_lock = threading.Lock()

def _load_played() -> Set[str]:
    if not PLAYED_SCENES_PATH.exists():
        return set()
    try:
        data = _read_json(PLAYED_SCENES_PATH)
        if isinstance(data, list):
            return set(data)
    except Exception:
        pass
    return set()

def get_played_scenes() -> Set[str]:
    global _played_cache
    with _played_lock:
        if _played_cache is None:
            _played_cache = _load_played()
        return _played_cache

def mark_played(scene_name: str) -> None:
    global _played_cache
    with _played_lock:
        if _played_cache is None:
            _played_cache = _load_played()
        _played_cache.add(scene_name)
        PLAYED_SCENES_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLAYED_SCENES_PATH.write_text(
            json.dumps(sorted(_played_cache), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

# ---- 下载模式配置 ----
RESOURCE_CONFIG_PATH = PROCESSED_DIR / "resource_config.json"
DEFAULT_CONFIG = {"download_mode": "manual"}  # "manual" | "lazy"

def get_resource_config() -> Dict[str, Any]:
    data = _read_json(RESOURCE_CONFIG_PATH)
    if isinstance(data, dict):
        return {**DEFAULT_CONFIG, **data}
    return dict(DEFAULT_CONFIG)

def set_resource_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    current = get_resource_config()
    current.update(updates)
    RESOURCE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESOURCE_CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return current

# ---- 自动预取 ----
AUTO_PREFETCH_THRESHOLD = 5  # 剩余未玩场景不足时触发

def auto_prefetch_check(catalog: List[Dict[str, Any]]) -> Optional[List[str]]:
    """如果懒下载模式且未玩本地场景不足，返回待下载列表。"""
    config = get_resource_config()
    if config.get("download_mode") != "lazy":
        return None

    local = set(list_local_scenes(catalog))
    played = get_played_scenes()
    unplayed_local = local - played
    unplayed_all = {str(r.get("scene_name") or "") for r in catalog} - played

    if len(unplayed_local) >= AUTO_PREFETCH_THRESHOLD:
        return None

    # 从未下载的未玩场景中选
    need = [name for name in unplayed_all if name not in local]
    if not need:
        return None

    # 优先锚点场景
    anchored = _get_anchored_scenes()
    need.sort(key=lambda n: (0 if n in anchored else 1, n))

    return need[:5]


# 全局单例
_queue = DownloadQueue()
