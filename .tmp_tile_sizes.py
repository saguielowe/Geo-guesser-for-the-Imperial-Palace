from pathlib import Path
from PIL import Image
root = Path(r"d:/Users/23329/Desktop/综合/学习/清华大学/大二下/寻迹故宫")
base = root / 'data/raw/panoramas/20/tiles/1_summer/f/l3'
for row in ['01','02','03','04','05','06']:
    files = sorted((base / row).glob('*.jpg'))
    widths = [Image.open(f).size[0] for f in files]
    heights = [Image.open(f).size[1] for f in files]
    print(row, widths, heights)
