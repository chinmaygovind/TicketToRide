"""Generate icon-192.png and icon-512.png from the SVG icon design."""
from PIL import Image, ImageDraw
import os

# Colors from the app theme
BG        = (26,  18,  16)    # #1a1210
GOLD      = (200, 168, 75)    # #c8a84b
GOLD_DARK = (184, 146, 58)    # #b8923a
BROWN     = (160, 120, 40)    # #a07828
RAIL      = (139, 105, 20)    # #8B6914
RAIL_DARK = (107,  79, 16)    # #6B4F10
DARK      = ( 42,  32, 24)    # #2a2018
STEAM     = ( 90,  74, 58)    # #5a4a3a


def rounded_rect(draw, x1, y1, x2, y2, r, fill):
    draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
    draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
    draw.ellipse([x1, y1, x1 + 2*r, y1 + 2*r], fill=fill)
    draw.ellipse([x2 - 2*r, y1, x2, y1 + 2*r], fill=fill)
    draw.ellipse([x1, y2 - 2*r, x1 + 2*r, y2], fill=fill)
    draw.ellipse([x2 - 2*r, y2 - 2*r, x2, y2], fill=fill)


def generate_icon(size):
    # All coordinates from the SVG viewBox (512x512); scale to target size
    k = size / 512

    def s(v):
        return round(v * k)

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background with rounded corners
    rounded_rect(draw, 0, 0, size - 1, size - 1, s(72), BG + (255,))

    # Rails (two horizontal bars)
    draw.rectangle([s(36), s(382), s(476), s(394)], fill=RAIL + (255,))
    draw.rectangle([s(36), s(406), s(476), s(418)], fill=RAIL + (255,))

    # Sleeper/tie planks
    for x in (64, 128, 192, 256, 320, 384, 434):
        draw.rectangle([s(x), s(376), s(x + 14), s(424)], fill=RAIL_DARK + (255,))

    # Smokestack shaft + cap
    draw.rectangle([s(128), s(156), s(162), s(240)], fill=GOLD + (255,))
    draw.rectangle([s(114), s(148), s(176), s(166)], fill=GOLD + (255,))

    # Boiler body (lower)
    draw.rectangle([s(68), s(250), s(368), s(330)], fill=GOLD_DARK + (255,))
    # Boiler highlight (top band)
    draw.rectangle([s(68), s(250), s(368), s(282)], fill=GOLD + (255,))

    # Cab body
    draw.rectangle([s(318), s(178), s(444), s(330)], fill=GOLD + (255,))

    # Cab windows (two upper)
    draw.rectangle([s(334), s(198), s(372), s(228)], fill=DARK + (255,))
    draw.rectangle([s(388), s(198), s(426), s(228)], fill=DARK + (255,))

    # Cab door window
    draw.rectangle([s(356), s(246), s(408), s(308)], fill=DARK + (255,))

    # Front cowcatcher (polygon)
    draw.polygon(
        [(s(46), s(280)), (s(68), s(250)), (s(68), s(330)), (s(46), s(340))],
        fill=BROWN + (255,),
    )

    # Large drive wheels x2
    for cx in (152, 252):
        cy = 352
        draw.ellipse([s(cx - 40), s(cy - 40), s(cx + 40), s(cy + 40)], fill=GOLD + (255,))
        draw.ellipse([s(cx - 20), s(cy - 20), s(cx + 20), s(cy + 20)], fill=BG + (255,))
        draw.ellipse([s(cx - 6),  s(cy - 6),  s(cx + 6),  s(cy + 6)],  fill=GOLD + (255,))

    # Smaller rear wheels x2 (under cab)
    for cx in (360, 430):
        cy = 356
        draw.ellipse([s(cx - 32), s(cy - 32), s(cx + 32), s(cy + 32)], fill=GOLD + (255,))
        draw.ellipse([s(cx - 16), s(cy - 16), s(cx + 16), s(cy + 16)], fill=BG + (255,))
        draw.ellipse([s(cx - 5),  s(cy - 5),  s(cx + 5),  s(cy + 5)],  fill=GOLD + (255,))

    # Connecting rod
    draw.rectangle([s(120), s(344), s(375), s(354)], fill=BROWN + (255,))

    # Steam puffs (semi-transparent circles, composited)
    steam_layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(steam_layer)
    for cx, cy, r, alpha in ((145, 118, 22, 178), (168, 98, 18, 128), (155, 80, 14, 89)):
        sd.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill=STEAM + (alpha,))
    img = Image.alpha_composite(img, steam_layer)

    return img


out_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'images')

for size, fname in ((192, 'icon-192.png'), (512, 'icon-512.png')):
    icon = generate_icon(size)
    path = os.path.join(out_dir, fname)
    icon.save(path, 'PNG')
    print(f"Wrote {path} ({size}x{size})")
