#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_BASE = ROOT / "data" / "raw" / "panoramas" / "999" / "tiles" / "synth_debug"
FACES = ["f", "b", "l", "r", "u", "d"]
SIZE = 512
ROWS = 6
COLS = 6

FACE_COLORS = {
    "f": (43, 124, 255),
    "b": (255, 120, 42),
    "l": (58, 188, 106),
    "r": (168, 106, 255),
    "u": (255, 196, 56),
    "d": (56, 204, 204),
}


def get_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "arial.ttf",
        "DejaVuSans.ttf",
        "msyh.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    title_font = get_font(44)
    code_font = get_font(180)
    sub_font = get_font(32)

    for face in FACES:
        base_color = FACE_COLORS[face]
        for row in range(1, ROWS + 1):
            row_token = f"{row:02d}"
            row_dir = OUT_BASE / face / "l3" / row_token
            row_dir.mkdir(parents=True, exist_ok=True)
            for col in range(1, COLS + 1):
                col_token = f"{col:02d}"
                code = f"{row}-{col}"
                tile_name = f"l3_{face}_{row_token}_{col_token}.jpg"
                tile_path = row_dir / tile_name

                img = Image.new("RGB", (SIZE, SIZE), base_color)
                draw = ImageDraw.Draw(img)

                # Border + center cross, easier to see seam orientation.
                draw.rectangle((2, 2, SIZE - 3, SIZE - 3), outline=(250, 250, 250), width=4)
                draw.line((0, SIZE // 2, SIZE, SIZE // 2), fill=(240, 240, 240), width=2)
                draw.line((SIZE // 2, 0, SIZE // 2, SIZE), fill=(240, 240, 240), width=2)

                # Row/Col color bars for instant orientation cues.
                row_color = (40 + row * 30, 30 + row * 20, 255 - row * 20)
                col_color = (255 - col * 20, 60 + col * 25, 40 + col * 20)
                draw.rectangle((0, 0, SIZE, 28), fill=row_color)
                draw.rectangle((0, SIZE - 28, SIZE, SIZE), fill=col_color)

                draw.text((16, 32), f"FACE {face.upper()}  L3", fill=(255, 255, 255), font=title_font)

                # Huge center code: this is the primary visual marker.
                center_text = f"{row}{col}"
                draw.text((132, 150), center_text, fill=(255, 255, 255), font=code_font)

                draw.text((16, 404), f"R{row_token} C{col_token}", fill=(255, 255, 255), font=sub_font)
                draw.text((16, 442), tile_name, fill=(255, 255, 255), font=sub_font)

                img.save(tile_path, format="JPEG", quality=95)

    print(f"Generated debug tiles at: {OUT_BASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
