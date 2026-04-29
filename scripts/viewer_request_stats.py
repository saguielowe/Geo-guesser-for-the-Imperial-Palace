#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_LOG_PATH = Path("logs/viewer-network-requests.jsonl")


def iter_records(path: Path) -> Iterable[Dict[str, Any]]:
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


def summarize(records: Iterable[Dict[str, Any]], top_n: int = 50) -> Dict[str, Any]:
    total = 0
    methods = Counter()
    paths = Counter()
    levels = Counter()
    tiles_by_face: Dict[str, int] = defaultdict(int)
    rows = Counter()
    cols = Counter()
    status_codes = Counter()
    tile_paths_by_key: Dict[str, List[str]] = defaultdict(list)
    tile_row_cols: Dict[str, Dict[str, set[str]]] = defaultdict(lambda: {"rows": set(), "cols": set()})

    for record in records:
        total += 1
        method = str(record.get("method") or "")
        path = str(record.get("path") or "")
        methods[method] += 1
        paths[path] += 1
        code = record.get("code")
        status_codes[str(code)] += 1

        if path.startswith("/assets/viewer/panos/") and (record.get("face") is None or record.get("level") is None):
            match = re.search(
                r"/assets/viewer/panos/(\d+)/([^/]+)/(?:([fbrlud])/l(\d+)|l(\d+)/([fbrlud]))/(\d+)/(\d+)\.jpg$",
                path,
            )
            if match:
                face = match.group(3) or match.group(6) or ""
                level = match.group(4) or match.group(5) or ""
                record = {
                    **record,
                    "face": face,
                    "level": int(level) if str(level).isdigit() else None,
                    "row": int(match.group(7)),
                    "col": int(match.group(8)),
                }

        if path.startswith("/assets/viewer/panos/"):
            level = record.get("level")
            if level is not None:
                levels[f"l{level}"] += 1
            face = str(record.get("face") or "")
            if face:
                tiles_by_face[face] += 1
            row = record.get("row")
            col = record.get("col")
            if row is not None:
                rows[str(row)] += 1
            if col is not None:
                cols[str(col)] += 1
            if face and level is not None and row is not None and col is not None:
                key = f"l{level}/{face}"
                tile_paths_by_key[key].append(path)
                tile_row_cols[key]["rows"].add(str(row))
                tile_row_cols[key]["cols"].add(str(col))

    coverage: Dict[str, Any] = {}
    for key in sorted(tile_row_cols.keys()):
        row_values = sorted(tile_row_cols[key]["rows"], key=lambda value: int(value))
        col_values = sorted(tile_row_cols[key]["cols"], key=lambda value: int(value))
        coverage[key] = {
            "rows": row_values,
            "cols": col_values,
            "row_count": len(row_values),
            "col_count": len(col_values),
            "sample_urls": tile_paths_by_key[key][:top_n],
        }

    return {
        "total_requests": total,
        "methods": methods.most_common(top_n),
        "status_codes": status_codes.most_common(top_n),
        "top_paths": paths.most_common(top_n),
        "tile_levels": levels.most_common(top_n),
        "tile_faces": sorted(tiles_by_face.items()),
        "tile_rows": rows.most_common(top_n),
        "tile_cols": cols.most_common(top_n),
        "coverage": coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize viewer network requests captured by backend/server.py.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH, help="Path to JSONL request log")
    parser.add_argument("--top", type=int, default=30, help="How many rows to print for top tables")
    args = parser.parse_args()

    records = list(iter_records(args.log))
    summary = summarize(records, top_n=max(1, args.top))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
