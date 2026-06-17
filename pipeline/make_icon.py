"""Generate brain.ico (multi-size Windows icon) matching dashboard branding.
Run once: python make_icon.py
Output: brain/brain.ico
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brain.ico"


def make_size(size: int) -> Image.Image:
    """Brain glyph: cyan→magenta gradient rings + glowing core."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    margin = max(1, size // 16)
    w_outer = max(2, size // 18)

    # Outer ring — cyan
    d.ellipse([margin, margin, size - margin, size - margin],
              outline=(0, 225, 255, 255), width=w_outer)

    # Inner ring — magenta
    m2 = size // 4
    w_inner = max(1, size // 24)
    d.ellipse([m2, m2, size - m2, size - m2],
              outline=(255, 43, 214, 240), width=w_inner)

    # Core dot — white with soft glow
    m3 = int(size * 0.4)
    d.ellipse([m3, m3, size - m3, size - m3], fill=(255, 255, 255, 255))

    # Add subtle outer glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([margin, margin, size - margin, size - margin],
               outline=(0, 225, 255, 80), width=w_outer + 2)
    if size >= 32:
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(1, size // 32)))
    out = Image.alpha_composite(glow, img)
    return out


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [make_size(s) for s in sizes]
    # PIL .ico save: pass the largest, sizes=, append_images=
    images[-1].save(
        str(OUT),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    print(f"[ok] wrote {OUT}  ({OUT.stat().st_size} bytes, {len(sizes)} sizes)")


if __name__ == "__main__":
    main()
