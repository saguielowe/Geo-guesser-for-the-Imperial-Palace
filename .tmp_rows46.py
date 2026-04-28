from pathlib import Path
root = Path(r"d:/Users/23329/Desktop/综合/学习/清华大学/大二下/寻迹故宫")
base = root / 'data/raw/panoramas/20/tiles/1_summer/u/l3'
for row in ['04','05','06']:
    files = sorted((base / row).glob('*.jpg'))
    print(row, len(files), [f.name for f in files[:3]], [f.name for f in files[-3:]])
