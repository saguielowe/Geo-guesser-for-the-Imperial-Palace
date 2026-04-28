import json
from pathlib import Path
from PIL import Image
root = Path(r"d:/Users/23329/Desktop/综合/学习/清华大学/大二下/寻迹故宫")
catalog = json.loads((root / 'data/processed/scene_catalog.mvp20.local.json').read_text(encoding='utf-8'))
scene = catalog[0]
print(scene['scene_name'], scene.get('pano_stub'))
print('widths_desc', scene.get('tiled_widths_desc'))
base = root / 'data/raw/panoramas/20/tiles' / scene['pano_stub']
for face in ['f','b','l','r','u','d']:
    level_dir = base / face / 'l3'
    rows = sorted([p.name for p in level_dir.iterdir() if p.is_dir()]) if level_dir.exists() else []
    print(face, 'rows', rows)
    if rows:
        for row in rows[:2]:
            row_dir = level_dir / row
            files = sorted(row_dir.glob('*.jpg'))
            print(' ', row, len(files), files[0].name if files else None)
            if files:
                img = Image.open(files[0])
                print('   size', img.size)
        break
