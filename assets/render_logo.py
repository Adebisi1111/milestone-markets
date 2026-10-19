"""Render the MilestoneMarkets logo assets.

The mark matches the SVG already used in the app (a violet->mint gradient tile
with a stepped path from a start node to a milestone node), so the logo and the
in-product wordmark are the same identity. Everything is drawn at 4x and
downsampled, which is what gives the rounded corners and diagonal edges clean
antialiasing without an SVG rasteriser.
"""

import os

from PIL import Image, ImageDraw, ImageFont

LANCZOS = Image.Resampling.LANCZOS

OUT = os.path.dirname(os.path.abspath(__file__))
SS = 4  # supersample factor

VIOLET = (109, 94, 248)   # #6D5EF8
MINT = (47, 217, 138)     # #2FD98A

# Geometry as fractions of the tile, taken from the in-app SVG (32x32 viewBox):
# path M9.5 22.5 V13 h6.5 v-3 h6.5, nodes r2.3 at both ends.
PTS = [(9.5 / 32, 22.5 / 32), (9.5 / 32, 13 / 32), (16 / 32, 13 / 32),
       (16 / 32, 10 / 32), (22.5 / 32, 10 / 32)]
NODE_R = 2.3 / 32
STROKE = 2.1 / 32
RADIUS = 9 / 32


def _gradient(size: int) -> Image.Image:
    """Diagonal violet -> mint gradient."""
    try:
        import numpy as np
    except ImportError:
        np = None

    if np is not None:
        y, x = np.mgrid[0:size, 0:size]
        t = (x + y) / (2.0 * (size - 1))
        t = t[..., None]
        rgb = (1 - t) * np.array(VIOLET) + t * np.array(MINT)
        return Image.fromarray(rgb.astype("uint8"), "RGB")

    img = Image.new("RGB", (size, size))
    px = img.load()
    for yy in range(size):
        for xx in range(size):
            t = (xx + yy) / (2.0 * (size - 1))
            px[xx, yy] = tuple(int(round((1 - t) * a + t * b)) for a, b in zip(VIOLET, MINT))
    return img


def _rounded_mask(size: int, radius: float) -> Image.Image:
    m = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size * SS - 1, size * SS - 1], radius=radius * SS, fill=255
    )
    return m.resize((size, size), LANCZOS)


def mark(size: int = 512, tile: bool = True) -> Image.Image:
    """The mark. `tile=True` gives the gradient tile; False gives the glyph alone."""
    grad = _gradient(size)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if tile:
        layer.paste(grad.convert("RGBA"), (0, 0), _rounded_mask(size, RADIUS))

    # Draw the path + nodes at 4x for smooth strokes, then downsample.
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    pts = [(x * size * SS, y * size * SS) for x, y in PTS]
    w = int(round(STROKE * size * SS))
    d.line(pts, fill=(255, 255, 255, 255), width=w, joint="curve")
    for p in (pts[0], pts[-1]):
        r = NODE_R * size * SS
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(255, 255, 255, 255))
    # Round the stroke ends, which `line` leaves square.
    for p in (pts[0], pts[-1]):
        r = w / 2.0
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(255, 255, 255, 255))
    glyph = big.resize((size, size), LANCZOS)

    layer = Image.alpha_composite(layer, glyph)
    return layer


def _font(px: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def lockup(height: int = 256) -> Image.Image:
    """Horizontal lockup: mark + wordmark, for headers and submission forms."""
    size = height
    m = mark(size)
    pad = int(size * 0.34)
    text = "MilestoneMarkets"
    f = _font(int(size * 0.40))
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    box = tmp.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    W = int(size + pad + tw + pad)
    H = int(size)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(m, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((size + pad, (H - th) / 2 - box[1]), text, font=f, fill=(255, 255, 255, 255))
    return canvas


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in (512, 256, 128, 64, 32):
        mark(s).save(os.path.join(OUT, f"logo-{s}.png"))
    mark(512).save(os.path.join(OUT, "logo.png"))
    # Light-background variant of the wordmark for docs on white.
    lk = lockup(256)
    lk.save(os.path.join(OUT, "logo-wordmark.png"))
    lk_dark = Image.new("RGBA", lk.size, (17, 17, 22, 255))
    lk_dark.alpha_composite(lk)
    lk_dark.convert("RGB").save(os.path.join(OUT, "logo-wordmark-dark.png"))
    print("wrote:", sorted(f for f in os.listdir(OUT) if f.startswith("logo")))
