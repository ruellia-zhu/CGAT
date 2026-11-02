"""Generate the PyInstaller splash image (run once, output committed to resources)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "app" / "resources" / "splash.png"
FONT = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
W, H = 460, 260
ACCENT = (47, 107, 94)
INK = (28, 28, 30)
MUTED = (107, 107, 112)


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def main() -> int:
    im = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=0, outline=(232, 232, 227))

    # a small ring mark, echoing the app icon
    cx, cy, r = 60, 92, 24
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ACCENT, width=3)
    d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=ACCENT)

    d.text((100, 68), "共线性 Circos", font=font(BOLD, 26), fill=INK)
    d.text((100, 104), "Circos Studio", font=font(FONT, 15), fill=MUTED)

    d.text((100, 170), "正在启动…", font=font(FONT, 14), fill=MUTED)

    # progress hint strip
    d.rounded_rectangle((100, 198, W - 44, 202), radius=2, fill=(228, 228, 223))
    d.rounded_rectangle((100, 198, 100 + int((W - 144) * 0.45), 202), radius=2, fill=ACCENT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT)
    print("wrote", OUT, im.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
