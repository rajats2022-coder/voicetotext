"""Take any square PNG and produce a macOS-style squircle icon at 1024x1024.

Output: art resized to 824x824, centered on transparent 1024 canvas, with a
superellipse mask (n=5) — the Apple squircle shape. Ready to feed to
`tauri icon`.
"""
import sys
from PIL import Image, ImageDraw

SRC = sys.argv[1]
DST = sys.argv[2]

CANVAS = 1024
ART = 824
MARGIN = (CANVAS - ART) // 2
N = 5.0

src = Image.open(SRC).convert("RGBA").resize((ART, ART), Image.LANCZOS)

mask = Image.new("L", (ART, ART), 0)
pixels = mask.load()
half = ART / 2.0
for y in range(ART):
    for x in range(ART):
        dx = (x - half + 0.5) / half
        dy = (y - half + 0.5) / half
        if abs(dx) ** N + abs(dy) ** N <= 1.0:
            pixels[x, y] = 255

canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
canvas.paste(src, (MARGIN, MARGIN), mask)
canvas.save(DST, "PNG")
print(f"wrote {DST}")
