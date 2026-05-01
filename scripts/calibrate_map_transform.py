#!/usr/bin/env python3
"""Fit affine transform from scene coordinate_x/y to minimap pixels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def scene_index(catalog_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in catalog_rows:
        name = str(row.get("scene_name") or "")
        if name:
            out[name] = row
    return out


def parse_scene_xy(row: Dict[str, Any]) -> Tuple[float, float]:
    for xk, yk in [("coordinate_x", "coordinate_y"), ("x_axis", "y_axis")]:
        try:
            x = float(row.get(xk))
            y = float(row.get(yk))
            return x, y
        except (TypeError, ValueError):
            pass
    coordinate = str(row.get("coordinate") or "")
    if "," in coordinate:
        a, b = [token.strip() for token in coordinate.split(",")[:2]]
        return float(a), float(b)
    raise ValueError("scene row has no usable coordinate_x/y or x_axis/y_axis")


def solve_3x3(a: List[List[float]], b: List[float]) -> List[float]:
    m = [row[:] + [b_i] for row, b_i in zip(a, b)]
    n = 3
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise RuntimeError("Singular matrix while solving 3x3 system")
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        factor = m[col][col]
        for k in range(col, n + 1):
            m[col][k] /= factor
        for row in range(n):
            if row == col:
                continue
            f = m[row][col]
            for k in range(col, n + 1):
                m[row][k] -= f * m[col][k]
    return [m[i][n] for i in range(n)]


def fit_affine(points: List[Tuple[float, float, float, float]]) -> Dict[str, float]:
    if len(points) < 3:
        raise RuntimeError("Need at least 3 anchor points")

    # Solve two linear models with normal equations:
    # px = a*x + b*y + c
    # py = d*x + e*y + f
    xtx = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    xt_px = [0.0, 0.0, 0.0]
    xt_py = [0.0, 0.0, 0.0]
    for x, y, px, py in points:
        v = [x, y, 1.0]
        for i in range(3):
            for j in range(3):
                xtx[i][j] += v[i] * v[j]
            xt_px[i] += v[i] * px
            xt_py[i] += v[i] * py

    a, b, c = solve_3x3(xtx, xt_px)
    d, e, f = solve_3x3(xtx, xt_py)
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "f": f}


def rmse(points: List[Tuple[float, float, float, float]], t: Dict[str, float]) -> float:
    acc = 0.0
    for x, y, px, py in points:
        px2 = t["a"] * x + t["b"] * y + t["c"]
        py2 = t["d"] * x + t["e"] * y + t["f"]
        dx = px2 - px
        dy = py2 - py
        acc += dx * dx + dy * dy
    return (acc / max(1, len(points))) ** 0.5


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate map affine transform from anchors")
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument(
        "--anchors",
        type=Path,
        default=Path("data/processed/map_anchor_points.sample.json"),
        help="JSON list of {scene_name, map_px, map_py}",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("data/processed/scene_catalog.mvp20.local.json"),
        help="Scene catalog with coordinate_x/y",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/map_transform.json"),
        help="Output transform JSON path",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    anchors_path = (workspace / args.anchors).resolve()
    catalog_path = (workspace / args.catalog).resolve()
    output_path = (workspace / args.output).resolve()

    anchors = load_json(anchors_path)
    rows = load_json(catalog_path)
    idx = scene_index(rows)
    points: List[Tuple[float, float, float, float]] = []
    misses: List[str] = []

    for anchor in anchors:
        scene_name = str(anchor.get("scene_name") or "")
        row = idx.get(scene_name)
        if not row:
            misses.append(scene_name)
            continue
        try:
            x, y = parse_scene_xy(row)
            px = float(anchor.get("map_px"))
            py = float(anchor.get("map_py"))
        except (TypeError, ValueError):
            misses.append(scene_name)
            continue
        points.append((x, y, px, py))

    if len(points) < 3:
        raise RuntimeError(f"Need >=3 valid anchors, got {len(points)}")

    t = fit_affine(points)
    result = {
        "kind": "affine",
        "anchors_file": str(anchors_path),
        "anchor_count_used": len(points),
        "anchor_count_missing": len(misses),
        "rmse_pixels": rmse(points, t),
        "world_size": 8192,
        "affine": t,
    }
    save_json(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if misses:
        print("missing_or_invalid_anchors:", ", ".join(misses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
