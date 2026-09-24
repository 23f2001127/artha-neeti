"""Generate every brand derivative from assets/brand/logo.png.

Outputs transparent mark/wordmark/lockup crops to assets/brand/ (used by the
PDF renderer) and web assets (favicons, app icons, social card) to
frontend/public/brand/.

    python scripts/build_brand_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "brand" / "logo.png"
BRAND_DIR = ROOT / "assets" / "brand"
WEB_DIR = ROOT / "frontend" / "public" / "brand"

NAVY = (6, 13, 23)
TILE = (11, 20, 34)

# Regions of the source lockup (1254x1254), found from its opaque bounding boxes.
MARK_BOX = (330, 220, 1030, 730)
WORDMARK_BOX = (95, 760, 1160, 945)
LOCKUP_BOX = (95, 220, 1160, 1012)


def key_out_background(img: Image.Image) -> Image.Image:
    """Make the dark halo transparent while keeping anti-aliased edges clean.

    Alpha follows brightness; colour is un-premultiplied against the near-black
    background so edges don't carry a dark fringe on light surfaces.
    """
    img = img.convert("RGBA")
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            t = min(1.0, max(0.0, (max(r, g, b) - 28) / 60))
            if t <= 0:
                px[x, y] = (0, 0, 0, 0)
                continue
            px[x, y] = (
                min(255, int(r / t)),
                min(255, int(g / t)),
                min(255, int(b / t)),
                int(a * t),
            )
    return img


def trim(img: Image.Image, pad: int = 8) -> Image.Image:
    bbox = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def fit(img: Image.Image, height: int) -> Image.Image:
    width = round(img.width * height / img.height)
    return img.resize((width, height), Image.LANCZOS)


def tile_icon(mark: Image.Image, size: int, radius_ratio: float = 0.22, padding: float = 0.09) -> Image.Image:
    """The mark on a rounded navy tile - legible on light and dark browser chrome."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255)
    canvas.paste(Image.new("RGBA", (size, size), TILE + (255,)), (0, 0), mask)
    inner = int(size * (1 - 2 * padding))
    scaled = mark.copy()
    scaled.thumbnail((inner, inner), Image.LANCZOS)
    canvas.alpha_composite(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2))
    return canvas


def social_card(lockup: Image.Image) -> Image.Image:
    width, height = 1200, 630
    card = Image.new("RGB", (width, height), NAVY)
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((250, 40, 950, 600), fill=(230, 184, 106, 40))
    card.paste(glow.filter(ImageFilter.GaussianBlur(120)), (0, 0), glow.filter(ImageFilter.GaussianBlur(120)))
    art = lockup.copy()
    art.thumbnail((760, 500), Image.LANCZOS)
    card.paste(art, ((width - art.width) // 2, (height - art.height) // 2), art)
    return card


def main() -> None:
    source = Image.open(SOURCE)
    keyed = key_out_background(source)

    mark = trim(keyed.crop(MARK_BOX))
    wordmark = trim(keyed.crop(WORDMARK_BOX))
    lockup = trim(keyed.crop(LOCKUP_BOX))

    fit(mark, 512).save(BRAND_DIR / "mark.png", optimize=True)
    fit(wordmark, 160).save(BRAND_DIR / "wordmark.png", optimize=True)
    fit(lockup, 800).save(BRAND_DIR / "lockup.png", optimize=True)

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    fit(mark, 160).save(WEB_DIR / "mark.png", optimize=True)
    fit(wordmark, 88).save(WEB_DIR / "wordmark.png", optimize=True)
    fit(lockup, 420).save(WEB_DIR / "lockup.png", optimize=True)

    for size, name in ((16, "favicon-16.png"), (32, "favicon-32.png"), (180, "apple-touch-icon.png"),
                       (192, "icon-192.png"), (512, "icon-512.png")):
        tile_icon(mark, size).save(WEB_DIR / name, optimize=True)
    tile_icon(mark, 256).save(WEB_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    social_card(lockup).save(WEB_DIR / "og-image.png", optimize=True)

    print("brand assets written to", BRAND_DIR.relative_to(ROOT), "and", WEB_DIR.relative_to(ROOT))


if __name__ == "__main__":
    main()
