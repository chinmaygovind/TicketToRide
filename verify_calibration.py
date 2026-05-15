#!/usr/bin/env python3
"""
Show board image with all calibrated city dots and route segment boxes overlaid.
Press any key or close window to exit.
"""
import cv2
import numpy as np
import math

from city_coords import CITIES
from route_segments import ROUTE_SEGMENTS
from game_data import ROUTES

IMG_PATH = "static/images/board.png"

COLOR_BGR = {
    "purple": (196, 132, 252),
    "blue":   (250, 165,  96),
    "orange": ( 60, 146, 251),
    "white":  (240, 232, 226),
    "green":  (128, 222,  74),
    "yellow": ( 21, 204, 250),
    "black":  (163, 156, 156),
    "red":    (113, 113, 248),
    "gray":   (219, 213, 209),
}

def rot_rect(cx, cy, w, h, angle_deg):
    a  = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return np.array(
        [(int(cx + x*ca - y*sa), int(cy + x*sa + y*ca)) for x, y in corners],
        dtype=np.int32
    )

img = cv2.imread(IMG_PATH)
if img is None:
    raise FileNotFoundError(f"Cannot open {IMG_PATH}")

# ── Route segment boxes ──────────────────────────────────────────────────────
route_by_id = {r["id"]: r for r in ROUTES}

for rid, segs in ROUTE_SEGMENTS.items():
    route = route_by_id.get(rid)
    if not route:
        continue
    color = COLOR_BGR.get(route["color"], (200, 200, 200))
    c1 = CITIES.get(route["city1"])
    c2 = CITIES.get(route["city2"])
    if c1 and c2:
        # Compute seg width from city-city distance (same as game.js)
        dx, dy = c2[0]-c1[0], c2[1]-c1[1]
        dist = math.hypot(dx, dy)
        seg_w = (dist / route["length"]) * 0.78
        seg_h = 8
    else:
        seg_w, seg_h = 18, 8

    for (cx, cy, angle) in segs:
        pts = rot_rect(cx, cy, seg_w, seg_h, angle)
        cv2.polylines(img, [pts], True, color, 1)
        cv2.circle(img, (cx, cy), 2, color, -1)

# ── City dots + full name labels ─────────────────────────────────────────────
for name, (x, y) in CITIES.items():
    cv2.circle(img, (x, y), 5, (0, 215, 255), -1)        # gold fill
    cv2.circle(img, (x, y), 5, (255, 255, 255), 1)        # white border

    # leader line + background box so name is readable over any background
    lx, ly = x + 8, y - 8
    (tw, th), _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.32, 1)
    cv2.rectangle(img, (lx - 1, ly - th - 1), (lx + tw + 1, ly + 2),
                  (0, 0, 0), -1)
    cv2.putText(img, name, (lx, ly),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 255, 255), 1)

# ── Save debug image ────────────────────────────────────────────────────────
debug_out = "static/images/calibration_verification.png"
cv2.imwrite(debug_out, img)
print(f"Saved verification image to {debug_out}")

# ── Show ─────────────────────────────────────────────────────────────────────
# Scale to fit screen
h, w = img.shape[:2]
max_dim = 1400
scale = min(max_dim / w, max_dim / h, 1.0)
if scale < 1.0:
    img = cv2.resize(img, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

cv2.imshow("Calibration Verification", img)
cv2.waitKey(0)
cv2.destroyAllWindows()
