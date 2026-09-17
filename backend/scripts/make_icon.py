"""Generate the Prosperya application icon (multi-size .ico).

Draws the brand mark — dark petrol rounded square, ring of 10 colored
nodes, serif "P" in champagne — at 256px and exports the standard
Windows icon sizes. Run: python scripts/make_icon.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
NODES = ["#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A",
         "#F6C515", "#55B57A", "#2C83C7", "#D42375", "#FF7A1A"]
OUT = Path(__file__).resolve().parent / "prosperya.ico"


def render(size: int) -> Image.Image:
    s = size / 256  # scale factor from the 256 master
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded-square background, dark petrol gradient approximation.
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(56 * s),
                        fill="#172326")
    d.rounded_rectangle([0, 0, size - 1, int(size * 0.55)], radius=int(56 * s),
                        fill="#1d2c2f")

    cx = cy = size / 2
    ring_r = 82 * s
    node_r = 26 * s
    for i, color in enumerate(NODES):
        a = (i / len(NODES)) * math.tau - math.pi / 2
        x, y = cx + math.cos(a) * ring_r, cy + math.sin(a) * ring_r
        d.ellipse([x - node_r, y - node_r, x + node_r, y + node_r], fill=color)

    # Inner disc + serif P in champagne.
    inner = 46 * s
    d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
              fill="#0b1416", outline="#3a4d52", width=max(1, int(1.5 * s)))
    try:
        font = ImageFont.truetype("georgiab.ttf", int(52 * s))
    except OSError:
        font = ImageFont.load_default(int(52 * s))
    d.text((cx, cy - 2 * s), "P", font=font, fill="#e9d8a6", anchor="mm")
    return img


def main() -> None:
    master = render(SIZE)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
             (256, 256)]
    master.save(OUT, format="ICO", sizes=sizes)
    print(f"Icon written: {OUT}")


if __name__ == "__main__":
    main()
