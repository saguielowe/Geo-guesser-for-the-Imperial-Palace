from pathlib import Path
root = Path(r"d:/Users/23329/Desktop/综合/学习/清华大学/大二下/寻迹故宫")
base = root / 'data/raw/panoramas/20/tiles/1_summer/u/l3'
for row in ['04','05','06']:
    row_dir = base / row
    print('ROW', row, 'exists', row_dir.exists())
    if row_dir.exists():
        print('entries', len(list(row_dir.glob('*.jpg'))))
        for f in sorted(row_dir.glob('*.jpg'))[:2]:
            print(f.name)
