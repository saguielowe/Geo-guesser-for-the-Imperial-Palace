import json
from pathlib import Path
from PIL import Image
root = Path(r"d:/Users/23329/Desktop/综合/学习/清华大学/大二下/寻迹故宫")
catalog = json.loads((root / 'data/processed/scene_catalog.mvp20.local.json').read_text(encoding='utf-8'))
scene = catalog[0]
base = root / 'data/raw/panoramas/20/tiles' / scene['pano_stub']
for face in ['f','b','l','r','u','d']:
    level_dirs = sorted([p.name for p in (base / face).iterdir() if p.is_dir()])
    print(face, level_dirs)
    level_dir = base / face / level_dirs[0]
    rows = sorted([p.name for p in level_dir.iterdir() if p.is_dir()])
    print(' rows', len(rows), rows[0], rows[-1])
    widths = []
    heights = []
    for row in rows:
        files = sorted((level_dir / row).glob('*.jpg'))
        widths.append(sum(Image.open(f).size[0] for f in files))
        heights.append(max(Image.open(f).size[1] for f in files) if files else 0)
    print(' face width range', min(widths), max(widths))
    print(' face height range', min(heights), max(heights))
    break
