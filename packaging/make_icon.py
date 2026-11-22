"""Draw the application icon: a folded topographic map with a marked trail and a pin.

    python packaging/make_icon.py

Writes icon.png (window icon), packaging/icon.ico (Windows) and packaging/icon.icns (macOS).
"""
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024   # drawn large, then reduced (anti-aliasing)

GREEN = "#2E7D5B"
PAPER = ("#F6EED6", "#E4D8B4", "#F6EED6")
FOREST = "#B9D7A0"
CONTOUR = "#B08A5A"
TRAIL = "#E2001A"
PIN = "#C8102E"

# Map folded in three panels, alternately raised and lowered
XS = [180, 403, 621, 844]
TOP = [300, 240, 300, 240]
BOTTOM = [800, 740, 800, 740]


def panel(i):
    return [(XS[i], TOP[i]), (XS[i + 1], TOP[i + 1]), (XS[i + 1], BOTTOM[i + 1]), (XS[i], BOTTOM[i])]


def map_mask():
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    for i in range(3):
        d.polygon(panel(i), fill=255)
    return m


def wavy(y0, amp, phase):
    return [(x, y0 + amp * math.sin(x / 95 + phase) + 0.12 * (x - 512)) for x in range(150, 880, 8)]


def dashed(d, pts, width, on, off, fill):
    """Polyline drawn as dashes of `on` px separated by `off` px."""
    pos, drawing = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.dist((x0, y0), (x1, y1))
        t = 0.0
        while t < seg:
            step = min((on if drawing else off) - pos, seg - t)
            if drawing:
                a, b = t / seg, (t + step) / seg
                d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                       fill=fill, width=width)
            t += step
            pos += step
            if pos >= (on if drawing else off):
                pos, drawing = 0.0, not drawing


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([24, 24, S - 24, S - 24], radius=200, fill=GREEN)
    # Shadow of the map
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i in range(3):
        sd.polygon([(x + 14, y + 18) for x, y in panel(i)], fill=(0, 0, 0, 70))
    img = Image.alpha_composite(img, shadow)

    # Map content on its own layer, cut to the panels
    content = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c = ImageDraw.Draw(content)
    for i in range(3):
        c.polygon(panel(i), fill=PAPER[i])
    c.ellipse([520, 230, 900, 520], fill=FOREST)
    c.ellipse([140, 610, 420, 860], fill=FOREST)
    for k, y in enumerate((330, 420, 510, 600, 690)):
        c.line(wavy(y, 34, k * 0.7), fill=CONTOUR, width=7)
    # Marked trail, like the hiking routes of the maps
    trail = [(240, 735), (330, 660), (300, 575), (420, 520), (520, 545), (590, 450), (700, 410)]
    c.line(trail, fill="#FFFFFF", width=34, joint="curve")
    dashed(c, trail, 22, 46, 22, TRAIL)
    # Shading of the lowered panel, to show the folds
    shade = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shade).polygon(panel(1), fill=(60, 40, 0, 28))
    content = Image.alpha_composite(content, shade)
    alpha = ImageChops.multiply(content.getchannel("A"), map_mask())
    content.putalpha(alpha)
    img = Image.alpha_composite(img, content)

    # Pin at the end of the trail
    d = ImageDraw.Draw(img)
    px, py, r = 700, 300, 78
    d.polygon([(px - r * 0.86, py + r * 0.5), (px + r * 0.86, py + r * 0.5), (px, py + r * 2.05)], fill=PIN)
    d.ellipse([px - r, py - r, px + r, py + r], fill=PIN)
    d.ellipse([px - r * 0.42, py - r * 0.42, px + r * 0.42, py + r * 0.42], fill="#FFFFFF")
    return img


def main():
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(ROOT / "icon.png")
    img.save(ROOT / "packaging" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                      (128, 128), (256, 256)])
    img.save(ROOT / "packaging" / "icon.icns")


if __name__ == "__main__":
    main()
