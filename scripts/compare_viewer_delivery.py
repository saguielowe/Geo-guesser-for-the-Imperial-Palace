#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple


DEFAULT_REQUEST_LOG = Path("logs/viewer-network-requests.jsonl")
DEFAULT_MANIFEST_LOG = Path("logs/viewer-manifest-log.jsonl")


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def flatten_expected_tiles(expected_tiles: Dict[str, List[str]]) -> Set[str]:
    urls: Set[str] = set()
    for face_urls in expected_tiles.values():
        for url in face_urls or []:
            urls.add(str(url))
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare viewer manifests with actual network requests.")
    parser.add_argument("--scene", default="", help="Only report a single scene name")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_LOG, help="Viewer manifest JSONL log")
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUEST_LOG, help="Viewer request JSONL log")
    args = parser.parse_args()

    manifests = list(iter_jsonl(args.manifest))
    requests = list(iter_jsonl(args.requests))

    request_urls_by_scene: Dict[str, Set[str]] = defaultdict(set)
    all_request_urls: Set[str] = set()
    for record in requests:
        path = str(record.get("path") or "")
        if path.startswith("/assets/viewer/panos/"):
            all_request_urls.add(path)

    latest_by_scene: Dict[str, Dict[str, Any]] = {}
    for manifest in manifests:
        scene_name = str(manifest.get("scene_name") or "")
        if args.scene and scene_name != args.scene:
            continue
        latest_by_scene[scene_name] = manifest

    for scene_name, manifest in latest_by_scene.items():
        expected_urls = flatten_expected_tiles(manifest.get("expected_tiles") or {})
        request_urls_by_scene[scene_name].update(url for url in expected_urls if url in all_request_urls)
        missing = sorted(expected_urls - all_request_urls)
        present = sorted(expected_urls & all_request_urls)
        payload = {
            "scene_name": scene_name,
            "expected_count": len(expected_urls),
            "present_count": len(present),
            "missing_count": len(missing),
            "present_sample": present[:40],
            "missing_sample": missing[:40],
            "maxLevel": manifest.get("maxLevel"),
            "source_level": manifest.get("source_level"),
            "source_rows": manifest.get("source_rows"),
            "source_cols": manifest.get("source_cols"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
