#!/usr/bin/env python3
"""
Detect precise city and car-slot positions from user click data.
Reads color_points.json, outputs city_coords.py + route_segments.py + debug image.
"""
import cv2, numpy as np, json, math
from scipy.optimize import linear_sum_assignment
from collections import defaultdict

IMG_PATH     = "static/images/board.png"
POINTS_FILE  = "color_points.json"
CITIES_OUT   = "city_coords.py"
SEGMENTS_OUT = "route_segments.py"
DEBUG_OUT    = "static/images/board_detected.png"
PATCH        = 55    # half-size of local search window around each click
PERP_BAND    = 60    # max perpendicular distance (px) from route centerline
DOUBLE_OFFSET = 6    # perpendicular offset (px) for parallel double-track expected positions

# ── Approximate city positions (used for Hungarian name-matching only) ────────
APPROX_CITIES = {
    "Vancouver":       ( 76, 115), "Seattle":         ( 88, 148),
    "Portland":        ( 75, 178), "San Francisco":   ( 57, 282),
    "Los Angeles":     ( 83, 352), "Las Vegas":       (134, 308),
    "Salt Lake City":  (192, 237), "Helena":          (228, 146),
    "Calgary":         (213,  88), "Winnipeg":        (467,  90),
    "Denver":          (263, 249), "Omaha":           (380, 219),
    "Duluth":          (451, 149), "Sault St. Marie": (573, 144),
    "Kansas City":     (405, 289), "Chicago":         (507, 216),
    "Saint Louis":     (490, 311), "Oklahoma City":   (361, 358),
    "Dallas":          (369, 408), "Houston":         (378, 445),
    "Little Rock":     (446, 378), "New Orleans":     (466, 457),
    "Nashville":       (544, 338), "Atlanta":         (581, 403),
    "Raleigh":         (659, 349), "Charleston":      (671, 399),
    "Miami":           (651, 499), "Washington":      (715, 306),
    "Pittsburgh":      (655, 264), "New York":        (763, 239),
    "Boston":          (793, 179), "Montreal":        (723, 146),
    "Toronto":         (639, 194), "Santa Fe":        (233, 311),
    "Phoenix":         (158, 369), "El Paso":         (222, 416),
}

ROUTES = [
    {"id":  1,"city1":"Vancouver",     "city2":"Seattle",        "length":1,"color":"gray",  "side":0},
    {"id":  2,"city1":"Vancouver",     "city2":"Seattle",        "length":1,"color":"gray",  "side":1},
    {"id":  3,"city1":"Vancouver",     "city2":"Calgary",        "length":3,"color":"gray",  "side":0},
    {"id":  4,"city1":"Seattle",       "city2":"Portland",       "length":1,"color":"gray",  "side":0},
    {"id":  5,"city1":"Seattle",       "city2":"Portland",       "length":1,"color":"gray",  "side":1},
    {"id":  6,"city1":"Seattle",       "city2":"Helena",         "length":6,"color":"yellow","side":0},
    {"id":  7,"city1":"Portland",      "city2":"San Francisco",  "length":5,"color":"green", "side":0},
    {"id":  8,"city1":"Portland",      "city2":"San Francisco",  "length":5,"color":"purple","side":1},
    {"id":  9,"city1":"Portland",      "city2":"Salt Lake City", "length":6,"color":"blue",  "side":0},
    {"id": 10,"city1":"San Francisco", "city2":"Los Angeles",    "length":3,"color":"yellow","side":0},
    {"id": 11,"city1":"San Francisco", "city2":"Los Angeles",    "length":3,"color":"purple","side":1},
    {"id": 12,"city1":"San Francisco", "city2":"Salt Lake City", "length":5,"color":"orange","side":0},
    {"id": 13,"city1":"San Francisco", "city2":"Salt Lake City", "length":5,"color":"white", "side":1},
    {"id": 14,"city1":"Los Angeles",   "city2":"Las Vegas",      "length":2,"color":"gray",  "side":0},
    {"id": 15,"city1":"Los Angeles",   "city2":"Phoenix",        "length":3,"color":"gray",  "side":0},
    {"id": 16,"city1":"Los Angeles",   "city2":"El Paso",        "length":6,"color":"black", "side":0},
    {"id": 17,"city1":"Las Vegas",     "city2":"Salt Lake City", "length":3,"color":"orange","side":0},
    {"id": 18,"city1":"Salt Lake City","city2":"Denver",         "length":3,"color":"red",   "side":0},
    {"id": 19,"city1":"Salt Lake City","city2":"Denver",         "length":3,"color":"yellow","side":1},
    {"id": 20,"city1":"Salt Lake City","city2":"Helena",         "length":3,"color":"purple","side":0},
    {"id": 21,"city1":"Denver",        "city2":"Helena",         "length":4,"color":"green", "side":0},
    {"id": 22,"city1":"Denver",        "city2":"Omaha",          "length":4,"color":"purple","side":0},
    {"id": 23,"city1":"Denver",        "city2":"Kansas City",    "length":4,"color":"black", "side":0},
    {"id": 24,"city1":"Denver",        "city2":"Kansas City",    "length":4,"color":"orange","side":1},
    {"id": 25,"city1":"Denver",        "city2":"Oklahoma City",  "length":4,"color":"red",   "side":0},
    {"id": 26,"city1":"Denver",        "city2":"Santa Fe",       "length":2,"color":"gray",  "side":0},
    {"id": 27,"city1":"Helena",        "city2":"Calgary",        "length":4,"color":"gray",  "side":0},
    {"id": 28,"city1":"Helena",        "city2":"Winnipeg",       "length":4,"color":"blue",  "side":0},
    {"id": 29,"city1":"Helena",        "city2":"Duluth",         "length":6,"color":"orange","side":0},
    {"id": 30,"city1":"Helena",        "city2":"Omaha",          "length":5,"color":"red",   "side":0},
    {"id": 31,"city1":"Calgary",       "city2":"Winnipeg",       "length":6,"color":"white", "side":0},
    {"id": 32,"city1":"Winnipeg",      "city2":"Duluth",         "length":4,"color":"black", "side":0},
    {"id": 33,"city1":"Winnipeg",      "city2":"Sault St. Marie","length":6,"color":"gray",  "side":0},
    {"id": 34,"city1":"Duluth",        "city2":"Omaha",          "length":2,"color":"gray",  "side":0},
    {"id": 35,"city1":"Duluth",        "city2":"Chicago",        "length":3,"color":"red",   "side":0},
    {"id": 36,"city1":"Duluth",        "city2":"Toronto",        "length":6,"color":"purple","side":0},
    {"id": 37,"city1":"Duluth",        "city2":"Sault St. Marie","length":3,"color":"gray",  "side":0},
    {"id": 38,"city1":"Omaha",         "city2":"Kansas City",    "length":1,"color":"gray",  "side":0},
    {"id": 39,"city1":"Omaha",         "city2":"Kansas City",    "length":1,"color":"gray",  "side":1},
    {"id": 40,"city1":"Omaha",         "city2":"Chicago",        "length":4,"color":"blue",  "side":0},
    {"id": 41,"city1":"Kansas City",   "city2":"Saint Louis",    "length":2,"color":"blue",  "side":0},
    {"id": 42,"city1":"Kansas City",   "city2":"Saint Louis",    "length":2,"color":"purple","side":1},
    {"id": 43,"city1":"Kansas City",   "city2":"Oklahoma City",  "length":2,"color":"gray",  "side":0},
    {"id": 44,"city1":"Kansas City",   "city2":"Oklahoma City",  "length":2,"color":"gray",  "side":1},
    {"id": 45,"city1":"Chicago",       "city2":"Saint Louis",    "length":2,"color":"green", "side":0},
    {"id": 46,"city1":"Chicago",       "city2":"Saint Louis",    "length":2,"color":"white", "side":1},
    {"id": 47,"city1":"Chicago",       "city2":"Pittsburgh",     "length":3,"color":"orange","side":0},
    {"id": 48,"city1":"Santa Fe",      "city2":"Oklahoma City",  "length":3,"color":"blue",  "side":0},
    {"id": 49,"city1":"Santa Fe",      "city2":"El Paso",        "length":2,"color":"gray",  "side":0},
    {"id": 50,"city1":"Phoenix",       "city2":"Denver",         "length":5,"color":"white", "side":0},
    {"id": 51,"city1":"Phoenix",       "city2":"El Paso",        "length":3,"color":"gray",  "side":0},
    {"id": 52,"city1":"El Paso",       "city2":"Dallas",         "length":4,"color":"red",   "side":0},
    {"id": 53,"city1":"El Paso",       "city2":"Houston",        "length":6,"color":"green", "side":0},
    {"id": 54,"city1":"Oklahoma City", "city2":"Dallas",         "length":2,"color":"gray",  "side":0},
    {"id": 55,"city1":"Oklahoma City", "city2":"Dallas",         "length":2,"color":"gray",  "side":1},
    {"id": 56,"city1":"Oklahoma City", "city2":"Little Rock",    "length":2,"color":"gray",  "side":0},
    {"id": 57,"city1":"Dallas",        "city2":"Little Rock",    "length":2,"color":"gray",  "side":0},
    {"id": 58,"city1":"Dallas",        "city2":"Houston",        "length":1,"color":"gray",  "side":0},
    {"id": 59,"city1":"Dallas",        "city2":"Houston",        "length":1,"color":"gray",  "side":1},
    {"id": 60,"city1":"Houston",       "city2":"New Orleans",    "length":2,"color":"gray",  "side":0},
    {"id": 61,"city1":"Little Rock",   "city2":"Saint Louis",    "length":2,"color":"gray",  "side":0},
    {"id": 62,"city1":"Little Rock",   "city2":"Nashville",      "length":3,"color":"white", "side":0},
    {"id": 63,"city1":"Little Rock",   "city2":"New Orleans",    "length":3,"color":"green", "side":0},
    {"id": 64,"city1":"New Orleans",   "city2":"Atlanta",        "length":4,"color":"yellow","side":0},
    {"id": 65,"city1":"New Orleans",   "city2":"Atlanta",        "length":4,"color":"orange","side":1},
    {"id": 66,"city1":"New Orleans",   "city2":"Miami",          "length":6,"color":"red",   "side":0},
    {"id": 67,"city1":"Nashville",     "city2":"Saint Louis",    "length":2,"color":"gray",  "side":0},
    {"id": 68,"city1":"Nashville",     "city2":"Atlanta",        "length":1,"color":"gray",  "side":0},
    {"id": 69,"city1":"Nashville",     "city2":"Pittsburgh",     "length":4,"color":"yellow","side":0},
    {"id": 70,"city1":"Nashville",     "city2":"Raleigh",        "length":3,"color":"black", "side":0},
    {"id": 71,"city1":"Atlanta",       "city2":"Raleigh",        "length":2,"color":"gray",  "side":0},
    {"id": 72,"city1":"Atlanta",       "city2":"Charleston",     "length":2,"color":"gray",  "side":0},
    {"id": 73,"city1":"Atlanta",       "city2":"Miami",          "length":5,"color":"blue",  "side":0},
    {"id": 74,"city1":"Raleigh",       "city2":"Charleston",     "length":2,"color":"gray",  "side":0},
    {"id": 75,"city1":"Raleigh",       "city2":"Washington",     "length":2,"color":"gray",  "side":0},
    {"id": 76,"city1":"Raleigh",       "city2":"Washington",     "length":2,"color":"gray",  "side":1},
    {"id": 77,"city1":"Raleigh",       "city2":"Pittsburgh",     "length":2,"color":"gray",  "side":0},
    {"id": 78,"city1":"Washington",    "city2":"Pittsburgh",     "length":2,"color":"gray",  "side":0},
    {"id": 79,"city1":"Washington",    "city2":"Pittsburgh",     "length":2,"color":"gray",  "side":1},
    {"id": 80,"city1":"Washington",    "city2":"New York",       "length":2,"color":"orange","side":0},
    {"id": 81,"city1":"Washington",    "city2":"New York",       "length":2,"color":"black", "side":1},
    {"id": 82,"city1":"Pittsburgh",    "city2":"New York",       "length":2,"color":"white", "side":0},
    {"id": 83,"city1":"Pittsburgh",    "city2":"New York",       "length":2,"color":"green", "side":1},
    {"id": 84,"city1":"Pittsburgh",    "city2":"Toronto",        "length":2,"color":"gray",  "side":0},
    {"id": 85,"city1":"Pittsburgh",    "city2":"Saint Louis",    "length":5,"color":"green", "side":0},
    {"id": 86,"city1":"New York",      "city2":"Boston",         "length":2,"color":"yellow","side":0},
    {"id": 87,"city1":"New York",      "city2":"Boston",         "length":2,"color":"red",   "side":1},
    {"id": 88,"city1":"New York",      "city2":"Montreal",       "length":3,"color":"blue",  "side":0},
    {"id": 89,"city1":"Boston",        "city2":"Montreal",       "length":2,"color":"gray",  "side":0},
    {"id": 90,"city1":"Boston",        "city2":"Montreal",       "length":2,"color":"gray",  "side":1},
    {"id": 91,"city1":"Montreal",      "city2":"Toronto",        "length":3,"color":"gray",  "side":0},
    {"id": 92,"city1":"Montreal",      "city2":"Sault St. Marie","length":5,"color":"black", "side":0},
    {"id": 93,"city1":"Toronto",       "city2":"Sault St. Marie","length":2,"color":"gray",  "side":0},
    {"id": 94,"city1":"Toronto",       "city2":"Chicago",        "length":4,"color":"white", "side":0},
]

# route color "purple" is physically pink on the board
COLOR_MAP = {"purple": "pink"}

# HSV tolerances (h, s, v) per color key
TOLERANCES = {
    "city":   (20, 70, 70),
    "yellow": (15, 65, 65),
    "blue":   (12, 55, 55),
    "red":    (15, 65, 65),
    "green":  (15, 65, 65),
    "orange": (15, 65, 65),
    "pink":   (20, 50, 55),
    "gray":   (60, 22, 32),
    "white":  (60, 30, 45),
    "black":  (60, 42, 38),
}

# BGR colours for debug visualisation
DEBUG_BGR = {
    "gray":(180,180,180), "yellow":(0,220,220), "blue":(220,80,0),
    "red":(0,0,220),      "green":(0,200,0),    "orange":(0,140,220),
    "white":(240,240,240),"purple":(200,80,200),"black":(100,100,100),
}


# ── helpers ───────────────────────────────────────────────────────────────────

def find_rect(hsv_img, x, y, color_key):
    """Return (cx, cy, w, h, angle) of the blob at pixel (x,y), or None."""
    H, W = hsv_img.shape[:2]
    x1,x2 = max(0,x-PATCH), min(W,x+PATCH)
    y1,y2 = max(0,y-PATCH), min(H,y+PATCH)
    local  = hsv_img[y1:y2, x1:x2]

    h0,s0,v0 = int(hsv_img[y,x,0]), int(hsv_img[y,x,1]), int(hsv_img[y,x,2])
    ht,st,vt = TOLERANCES[color_key]

    lo = np.array([max(0,h0-ht), max(0,s0-st), max(0,v0-vt)])
    hi = np.array([min(180,h0+ht), min(255,s0+st), min(255,v0+vt)])
    mask = cv2.inRange(local, lo, hi)

    # red wraps around H=0/180
    if h0 < 15:
        lo2 = np.array([max(0,180-ht+h0), max(0,s0-st), max(0,v0-vt)])
        mask |= cv2.inRange(local, lo2, np.array([180,min(255,s0+st),min(255,v0+vt)]))

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)))

    lx = min(x-x1, local.shape[1]-1)
    ly = min(y-y1, local.shape[0]-1)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    label = int(labels[ly, lx])

    if label == 0:
        ys2,xs2 = np.where(labels > 0)
        if len(xs2) == 0: return None
        idx   = int(np.argmin((xs2-lx)**2 + (ys2-ly)**2))
        label = int(labels[ys2[idx], xs2[idx]])

    if stats[label, cv2.CC_STAT_AREA] < 15: return None

    comp = ((labels==label)*255).astype(np.uint8)
    cnts,_ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts: return None
    c = max(cnts, key=cv2.contourArea)

    (cx,cy),(w,h),angle = cv2.minAreaRect(c)
    if w < h: w,h = h,w; angle = (angle+90)%180

    return (cx+x1, cy+y1, w, h, angle)


def proj(px, py, c1, c2):
    """(along_fraction, signed_perp_px) of point onto segment c1→c2."""
    a = np.array(c1, float); b = np.array(c2, float)
    d = b - a; L = np.linalg.norm(d)
    if L < 1: return 0.0, 0.0
    nd = d / L
    perp_dir = np.array([-nd[1], nd[0]])
    v = np.array([px, py], float) - a
    return float(np.dot(v, nd) / L), float(np.dot(v, perp_dir))


# ── load ──────────────────────────────────────────────────────────────────────
img  = cv2.imread(IMG_PATH)
hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
dbg  = img.copy()

with open(POINTS_FILE) as f:
    points = json.load(f)

# ── step 1: precise rects ────────────────────────────────────────────────────
# Each entry: (cx, cy, w, h, angle, user_x, user_y)
# user_x/y = original click (always on-slot); cx/cy = detected blob centroid
car_rects  = defaultdict(list)
for color_key, pts in points.items():
    if color_key == "city":
        continue
    for (x, y) in pts:
        r = find_rect(hsv, x, y, color_key)
        if r is not None:
            car_rects[color_key].append((*r, x, y))

print("Car rects:", {k:len(v) for k,v in car_rects.items()})

# ── step 2: load ground-truth city positions from city_coords.py ──────────────
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("city_coords", CITIES_OUT)
_mod  = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
city_pos = {k: (int(v[0]), int(v[1])) for k, v in _mod.CITIES.items()}
print(f"Loaded {len(city_pos)} cities from {CITIES_OUT}")

# ── step 3: assign car slots to routes (exclusive Hungarian per color) ────────

def _route_expected(route, city_pos, offset_perp=0.0):
    """Linear interpolation of n segment centers, optionally offset perpendicular."""
    c1n, c2n = route['city1'], route['city2']
    if c1n not in city_pos or c2n not in city_pos:
        return []
    c1, c2 = city_pos[c1n], city_pos[c2n]
    dx, dy = c2[0]-c1[0], c2[1]-c1[1]
    L = math.hypot(dx, dy)
    nx, ny = (-dy/L, dx/L) if L > 0 else (0.0, 1.0)
    n = route['length']
    return [(c1[0]+(i+.5)/n*dx + offset_perp*nx,
             c1[1]+(i+.5)/n*dy + offset_perp*ny)
            for i in range(n)]


def assign_color_rects(rects, routes, city_pos):
    """Exclusively assign rects to route segments; returns {route_id: [(cx,cy,angle)]}."""
    result = {r['id']: [] for r in routes}
    if not rects or not routes:
        return result

    # Identify double-route city pairs (same city pair appears twice for same color)
    pair_cnt = defaultdict(int)
    for r in routes:
        pair_cnt[(min(r['city1'],r['city2']), max(r['city1'],r['city2']))] += 1
    double_pairs = {k for k,v in pair_cnt.items() if v > 1}

    # Build expected positions for every segment across all routes of this color
    all_exp = []   # (route_id, ex, ey)
    rid_to_route = {r['id']: r for r in routes}
    for r in routes:
        gk = (min(r['city1'],r['city2']), max(r['city1'],r['city2']))
        offset = DOUBLE_OFFSET * (1 if r['side'] == 0 else -1) if gk in double_pairs else 0.0
        for ex, ey in _route_expected(r, city_pos, offset):
            all_exp.append((r['id'], ex, ey))

    if not all_exp:
        return result

    nr, ne = len(rects), len(all_exp)
    INF = 1e8
    cost = np.full((nr, ne), INF)

    for i, rect in enumerate(rects):
        cx, cy   = rect[0], rect[1]
        ux, uy   = rect[5], rect[6]   # original user click — used for band/cost
        for j, (rid, ex, ey) in enumerate(all_exp):
            r = rid_to_route[rid]
            c1n, c2n = r['city1'], r['city2']
            if c1n not in city_pos or c2n not in city_pos:
                continue
            af, perp = proj(ux, uy, city_pos[c1n], city_pos[c2n])
            if -0.15 <= af <= 1.15 and abs(perp) <= PERP_BAND:
                cost[i][j] = math.hypot(ux-ex, uy-ey)

    ri, ci = linear_sum_assignment(cost)

    for i, j in zip(ri, ci):
        if cost[i][j] < INF:
            rid = all_exp[j][0]
            rect = rects[i]
            # Store detected centroid (cx,cy,angle) — more precise than click
            result[rid].append((round(rect[0]), round(rect[1]), round(rect[4], 1)))

    # Sort each route's segments along its direction
    for r in routes:
        c1n, c2n = r['city1'], r['city2']
        if c1n in city_pos and c2n in city_pos:
            c1, c2 = city_pos[c1n], city_pos[c2n]
            result[r['id']].sort(key=lambda s: proj(s[0], s[1], c1, c2)[0])

    return result


color_to_routes = defaultdict(list)
for r in ROUTES:
    color_to_routes[COLOR_MAP.get(r['color'], r['color'])].append(r)

route_segs = {}
for color_key, routes in color_to_routes.items():
    assigned = assign_color_rects(car_rects.get(color_key, []), routes, city_pos)
    route_segs.update(assigned)
for r in ROUTES:
    if r['id'] not in route_segs:
        route_segs[r['id']] = []

# ── step 4: report mismatches ─────────────────────────────────────────────────
warns = 0
for route in ROUTES:
    segs = route_segs.get(route['id'], [])
    if len(segs) != route['length']:
        print(f"  WARN r{route['id']:2d} {route['city1']}-{route['city2']}"
              f" [{route['color']}]: expected {route['length']} got {len(segs)}")
        warns += 1
print(f"{warns} route warnings")

# ── step 4.5: linear interpolation fallback for any route with wrong count ─────
# Ensures every route has exactly route.length segments in the output.
fallback = 0
for route in ROUTES:
    segs = route_segs[route['id']]
    if len(segs) == route['length']:
        continue
    c1n, c2n = route['city1'], route['city2']
    if c1n not in city_pos or c2n not in city_pos:
        continue
    c1, c2 = city_pos[c1n], city_pos[c2n]
    dx, dy = c2[0]-c1[0], c2[1]-c1[1]
    ang = round(math.degrees(math.atan2(dy, dx)) % 180, 1)
    n = route['length']
    route_segs[route['id']] = [
        (round(c1[0]+(i+.5)/n*dx), round(c1[1]+(i+.5)/n*dy), ang)
        for i in range(n)]
    fallback += 1
print(f"{fallback} routes using linear interpolation fallback")

# ── step 5: save outputs ──────────────────────────────────────────────────────
# city_coords.py is ground-truth from calibrate_cities.py — do not overwrite

with open(SEGMENTS_OUT,'w') as f:
    f.write("# route_id -> [(cx, cy, angle_deg), ...]\n")
    f.write("ROUTE_SEGMENTS = {\n")
    for route in ROUTES:
        segs = route_segs.get(route['id'],[])
        f.write(f"    {route['id']:2d}: {segs},\n")
    f.write("}\n")
print(f"Saved {SEGMENTS_OUT}")

# ── step 6: debug visualisation ───────────────────────────────────────────────
for name,(x,y) in city_pos.items():
    cv2.circle(dbg,(x,y),6,(0,200,255),2)
    cv2.putText(dbg,name[:4],(x+7,y-4),cv2.FONT_HERSHEY_PLAIN,0.7,(0,200,255),1)

for route in ROUTES:
    col = DEBUG_BGR.get(route['color'],(255,255,255))
    for cx,cy,ang in route_segs.get(route['id'],[]):
        box = cv2.boxPoints(((cx,cy),(28,8),ang))
        cv2.drawContours(dbg,[box.astype(int)],0,col,1)

cv2.imwrite(DEBUG_OUT, dbg)
print(f"Debug image -> {DEBUG_OUT}")
