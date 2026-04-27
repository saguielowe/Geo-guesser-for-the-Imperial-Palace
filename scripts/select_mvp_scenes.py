#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_json(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Select MVP scene subset from scene catalog")
    parser.add_argument("--input", default="data/processed/scene_catalog.phase0.json")
    parser.add_argument("--output", default="data/processed/scene_catalog.mvp20.json")
    parser.add_argument("--size", type=int, default=20)
    args = parser.parse_args()

    src = Path(args.input)
    dst = Path(args.output)
    rows = load_json(src)

    # Prefer diversity across panorama and scene groups.
    selected: List[Dict[str, Any]] = []
    used_panorama = set()
    used_group = set()

    # Pass 1: one scene per panorama where possible.
    for row in rows:
        if len(selected) >= args.size:
            break
        pid = row.get("panorama_id")
        if pid in used_panorama:
            continue
        selected.append(row)
        used_panorama.add(pid)
        if row.get("scene_group_name"):
            used_group.add(row.get("scene_group_name"))

    # Pass 2: fill with unseen groups.
    if len(selected) < args.size:
        for row in rows:
            if len(selected) >= args.size:
                break
            if row in selected:
                continue
            g = row.get("scene_group_name")
            if g and g not in used_group:
                selected.append(row)
                used_group.add(g)

    # Pass 3: fill remaining by original order.
    if len(selected) < args.size:
        for row in rows:
            if len(selected) >= args.size:
                break
            if row not in selected:
                selected.append(row)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "input_count": len(rows),
                "selected_count": len(selected),
                "output": str(dst),
                "unique_panorama": len({r.get('panorama_id') for r in selected}),
                "unique_group": len({r.get('scene_group_name') for r in selected if r.get('scene_group_name')}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
