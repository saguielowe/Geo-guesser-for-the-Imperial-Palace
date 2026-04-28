import json
from pathlib import Path
root = Path(r"d:/Users/23329/Desktop/综合/学习/清华大学/大二下/寻迹故宫")
catalog = json.loads((root / 'data/processed/scene_catalog.mvp20.local.json').read_text(encoding='utf-8'))
scene = catalog[0]
base = root / 'data/raw/panoramas/20/tiles' / scene['pano_stub']
level_dir = base / 'f' / 'l3'
for row_dir in sorted([p for p in level_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
    files = sorted(row_dir.glob('*.jpg'))
    print(row_dir.name, len(files), files[0].name if files else '-')
