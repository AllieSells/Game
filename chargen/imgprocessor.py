from PIL import Image
from pathlib import Path

INPUT_DIR = Path("chargen")
OUTPUT_DIR = INPUT_DIR / "processed"
OUTPUT_DIR.mkdir(exist_ok=True)

FRAME_W = 64
FRAME_H = 64

# zero-indexed LPC frame position
FRAME_COL = 1
FRAME_ROW = 2

# Must be exactly 32x32:
# right - left = 32
# bottom - top = 32
PORTRAIT_CROP = (16, 10, 48, 42)

for file in INPUT_DIR.glob("*.png"):
    sheet = Image.open(file).convert("RGBA")

    frame_left = FRAME_COL * FRAME_W
    frame_top = FRAME_ROW * FRAME_H

    frame = sheet.crop((
        frame_left,
        frame_top,
        frame_left + FRAME_W,
        frame_top + FRAME_H
    ))

    portrait = frame.crop(PORTRAIT_CROP)

    # Safety check: make sure it is exactly 32x32
    assert portrait.size == (32, 32), f"{file.name} produced {portrait.size}"

    out_path = OUTPUT_DIR / f"{file.stem}_portrait.png"
    portrait.save(out_path)

    print(f"Saved {out_path}")