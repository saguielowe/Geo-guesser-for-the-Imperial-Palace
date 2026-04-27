#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path("data/raw/panoramas")
CATALOG = Path("data/processed/scene_catalog.phase0.json")
OUT_INVENTORY = Path("data/processed/local_tiles_inventory.json")
OUT_MVP = Path("data/processed/scene_catalog.mvp20.local.json")


def load_catalog() -> List[Dict[str, Any]]:
    if not CATALOG.exists():
        return []
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def main() -> int:
    pattern = re.compile(r"panoramas/(\d+)/tiles/([^/]+)/([fbrlud])/(l\d)/")

    stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "panorama_id": None,
        "pano_stub": None,
        "levels": defaultdict(int),
        "faces": defaultdict(int),
        "file_count": 0,
    })

    if ROOT.exists():
        for p in ROOT.rglob("*.jpg"):
            m = pattern.search(p.as_posix())
            if not m:
                continue
            pid, stub, face, level = m.groups()
            key = f"{pid}:{stub}"
            rec = stats[key]
            rec["panorama_id"] = int(pid)
            rec["pano_stub"] = stub
            rec["levels"][level] += 1
            rec["faces"][face] += 1
            rec["file_count"] += 1

    inventory: List[Dict[str, Any]] = []
    for rec in stats.values():
        inventory.append(
            {
                "panorama_id": rec["panorama_id"],
                "pano_stub": rec["pano_stub"],
                "file_count": rec["file_count"],
                "levels": dict(sorted(rec["levels"].items())),
                "faces": dict(sorted(rec["faces"].items())),
            }
        )

    inventory.sort(key=lambda x: (x["panorama_id"], x["pano_stub"]))
    OUT_INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    OUT_INVENTORY.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build local MVP list from already downloaded stubs only.
    catalog = load_catalog()
    available_keys = {(i["panorama_id"], i["pano_stub"]) for i in inventory}

    local_rows: List[Dict[str, Any]] = []
    for row in catalog:
        key = (row.get("panorama_id"), row.get("pano_stub"))
        if key in available_keys:
            local_rows.append(row)

    selected: List[Dict[str, Any]] = []
    used_panorama = set()

    # Pass 1: prefer one scene per available panorama.
    for row in local_rows:
        if len(selected) >= 20:
            break
        pid = row.get("panorama_id")
        if pid in used_panorama:
            continue
        selected.append(row)
        used_panorama.add(pid)

    # Pass 2: fill remaining slots by existing order.
    if len(selected) < 20:
        for row in local_rows:
            if len(selected) >= 20:
                break
            if row not in selected:
                selected.append(row)
    OUT_MVP.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "inventory_output": str(OUT_INVENTORY),
        "mvp_output": str(OUT_MVP),
        "downloaded_scene_stubs": len(inventory),
        "downloaded_files": sum(i["file_count"] for i in inventory),
        "mvp_scene_count": len(selected),
        "panorama_ids": sorted({i["panorama_id"] for i in inventory}),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
