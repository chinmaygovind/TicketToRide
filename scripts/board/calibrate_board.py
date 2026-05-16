#!/usr/bin/env python3
"""
Two-phase board calibration.
  Phase 1: Click each city dot (36 clicks).
  Phase 2: Click 4 corners of each train-car slot (94 routes × lengths ≈ 280 slots × 4 clicks).

Saves incrementally to calibration_progress.json so you can quit and resume.
Writes city_coords.py and route_segments.py on close.
"""
import tkinter as tk
from PIL import Image, ImageTk
import numpy as np
import cv2, json, math, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))  # project root

IMG_PATH     = os.path.join(_ROOT, "static", "images", "board.png")
SAVE_FILE    = os.path.join(_HERE, "calibration_progress.json")
CITIES_OUT   = os.path.join(_HERE, "city_coords.py")
SEGMENTS_OUT = os.path.join(_ROOT, "route_segments.py")

CITIES = [
    "Vancouver","Seattle","Portland","San Francisco","Los Angeles",
    "Las Vegas","Salt Lake City","Helena","Calgary","Winnipeg",
    "Denver","Omaha","Duluth","Sault St. Marie","Kansas City",
    "Chicago","Saint Louis","Oklahoma City","Dallas","Houston",
    "Little Rock","New Orleans","Nashville","Atlanta","Raleigh",
    "Charleston","Miami","Washington","Pittsburgh","New York",
    "Boston","Montreal","Toronto","Santa Fe","Phoenix","El Paso",
]

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
    {"id": 95,"city1":"Duluth",        "city2":"Omaha",          "length":2,"color":"gray",  "side":1},
    {"id": 96,"city1":"Seattle",       "city2":"Calgary",        "length":4,"color":"gray",  "side":0},
    {"id": 97,"city1":"Phoenix",       "city2":"Santa Fe",       "length":3,"color":"gray",  "side":0},
    {"id": 98,"city1":"El Paso",       "city2":"Oklahoma City",  "length":5,"color":"yellow","side":0},
    {"id": 99,"city1":"Charleston",    "city2":"Miami",          "length":4,"color":"purple","side":0},
]

COLOR_HEX = {
    "purple":"#C084FC","blue":"#60A5FA","orange":"#FB923C",
    "white":"#E2E8F0","green":"#4ADE80","yellow":"#FACC15",
    "black":"#9CA3AF","red":"#F87171","gray":"#D1D5DB",
}

TOTAL_SEGS = sum(r["length"] for r in ROUTES)


class BoardCalibrator:
    def __init__(self, root):
        self.root = root
        root.title("Board Calibration")
        root.configure(bg="#111")

        img_pil = Image.open(IMG_PATH)
        self.orig_w, self.orig_h = img_pil.size

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        self.scale = min((sw - 4) / self.orig_w, (sh - 64) / self.orig_h)
        dw = int(self.orig_w * self.scale)
        dh = int(self.orig_h * self.scale)
        self.tk_img = ImageTk.PhotoImage(img_pil.resize((dw, dh), Image.LANCZOS))

        # ── label bar ────────────────────────────────────────────────────────
        bar = tk.Frame(root, bg="#111", height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.lbl = tk.Label(bar, text="", font=("Arial", 13, "bold"),
                            bg="#111", fg="white", anchor="w", padx=12)
        self.lbl.pack(side="left", fill="y")
        self.cnt = tk.Label(bar, text="", font=("Arial", 12, "bold"),
                            bg="#111", fg="#6ee7b7", anchor="e", padx=12)
        self.cnt.pack(side="right", fill="y")

        # ── canvas ───────────────────────────────────────────────────────────
        self.cv = tk.Canvas(root, width=dw, height=dh,
                            cursor="crosshair", bg="black", highlightthickness=0)
        self.cv.pack()
        self.cv.create_image(0, 0, anchor="nw", image=self.tk_img)

        self.cv.bind("<Button-1>", self.on_click)
        root.bind("<BackSpace>", self.undo)
        root.protocol("WM_DELETE_WINDOW", self.close)

        # ── state ────────────────────────────────────────────────────────────
        self.phase      = "cities"
        self.city_idx   = 0
        self.city_pos   = {}      # name -> (x, y) in original px

        self.route_idx  = 0
        self.seg_idx    = 0
        self.route_segs = {}      # route_id -> [(cx, cy, angle), ...]
        self.corners    = []      # pending corner clicks for current segment

        self.history    = []      # for undo
        self._guide_ids = []      # canvas items to refresh each step

        self._load()
        self._refresh()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(SAVE_FILE):
            return
        with open(SAVE_FILE) as f:
            d = json.load(f)
        self.city_pos = {k: tuple(v) for k, v in d.get("cities", {}).items()}
        self.route_segs = {int(k): [tuple(s) for s in v]
                           for k, v in d.get("segs", {}).items()}
        self.city_idx = sum(1 for c in CITIES if c in self.city_pos)
        if self.city_idx >= len(CITIES):
            self.phase = "routes"
        # Find resume point in routes
        for i, r in enumerate(ROUTES):
            rid = r["id"]
            done = len(self.route_segs.get(rid, []))
            if done < r["length"]:
                self.route_idx = i
                self.seg_idx   = done
                break
        else:
            self.route_idx = len(ROUTES)
        n_segs = sum(len(v) for v in self.route_segs.values())
        print(f"Resumed: {len(self.city_pos)} cities, {n_segs} segments")

    def _save(self):
        with open(SAVE_FILE, "w") as f:
            json.dump({
                "cities": {k: list(v) for k, v in self.city_pos.items()},
                "segs":   {str(k): [list(s) for s in v]
                           for k, v in self.route_segs.items()},
            }, f)

    def _write_outputs(self):
        with open(CITIES_OUT, "w") as f:
            f.write("CITIES = {\n")
            for c in CITIES:
                x, y = self.city_pos.get(c, (0, 0))
                f.write(f'    "{c}":{" "*(20-len(c))}({x:4d}, {y:4d}),\n')
            f.write("}\n")
        with open(SEGMENTS_OUT, "w") as f:
            f.write("# route_id -> [(center_x, center_y, angle_deg), ...]\n")
            f.write("ROUTE_SEGMENTS = {\n")
            for r in ROUTES:
                segs = self.route_segs.get(r["id"], [])
                f.write(f"    {r['id']}: {[list(s) for s in segs]},\n")
            f.write("}\n")
        print(f"Saved {CITIES_OUT} and {SEGMENTS_OUT}")

    # ── UI refresh ───────────────────────────────────────────────────────────

    def _refresh(self):
        # Clear transient guide items
        for i in self._guide_ids:
            self.cv.delete(i)
        self._guide_ids = []

        if self.phase == "cities":
            if self.city_idx >= len(CITIES):
                self.phase = "routes"
                self._refresh()
                return
            city = CITIES[self.city_idx]
            self.lbl.config(
                text=f"CITIES  →  click the dot for:  {city}",
                fg="#FCD34D")
            self.cnt.config(text=f"{self.city_idx} / {len(CITIES)} cities")

        elif self.phase == "routes":
            if self.route_idx >= len(ROUTES):
                self._finish()
                return
            r    = ROUTES[self.route_idx]
            col  = COLOR_HEX.get(r["color"], "#fff")
            done = sum(len(v) for v in self.route_segs.values())
            nc   = len(self.corners)
            self.lbl.config(
                text=f"R{r['id']}  {r['city1']} → {r['city2']}"
                     f"  [{r['color'].upper()}  ×{r['length']}  side={r['side']}]"
                     f"  seg {self.seg_idx+1}/{r['length']}"
                     f"  ·  click corner {nc+1}/4"
                     f"  (Backspace=undo)",
                fg=col)
            self.cnt.config(text=f"{done} / {TOTAL_SEGS} segs")
            self._draw_guide(r)

    def _draw_guide(self, route):
        c1 = self.city_pos.get(route["city1"])
        c2 = self.city_pos.get(route["city2"])
        if not (c1 and c2):
            return
        x1, y1 = c1[0]*self.scale, c1[1]*self.scale
        x2, y2 = c2[0]*self.scale, c2[1]*self.scale
        col = COLOR_HEX.get(route["color"], "white")

        # Route centre-line
        self._guide_ids.append(
            self.cv.create_line(x1, y1, x2, y2,
                                fill=col, width=1, dash=(4, 4)))

        # Endpoint dots
        for sx, sy in ((x1, y1), (x2, y2)):
            self._guide_ids.append(
                self.cv.create_oval(sx-5, sy-5, sx+5, sy+5,
                                    outline=col, width=2, fill=""))

        # Approximate target box for the CURRENT segment
        n  = route["length"]
        dx, dy = x2-x1, y2-y1
        L  = math.hypot(dx, dy)
        if L < 1:
            return
        nx, ny = -dy/L, dx/L          # perpendicular unit

        # side offset (same convention as buildRouteSegments in JS)
        off = (1 if route["side"] == 0 else -1) * 4 * self.scale
        ox, oy = nx*off, ny*off

        t  = (self.seg_idx + 0.5) / n
        cx = x1 + dx*t + ox
        cy = y1 + dy*t + oy
        sw = (L / n) * 0.78          # approx slot width in screen px
        sh = 8 * self.scale

        angle_deg = math.degrees(math.atan2(dy, dx))
        pts = _rot_rect(cx, cy, sw, sh, angle_deg)
        flat = [v for p in pts for v in p]
        self._guide_ids.append(
            self.cv.create_polygon(*flat,
                                   outline=col, fill=col, width=2,
                                   stipple="gray25", dash=(3, 3)))

        # Already-done segments of this route as solid outlines
        done_segs = self.route_segs.get(route["id"], [])
        for (scx, scy, sang) in done_segs:
            pts2 = _rot_rect(scx*self.scale, scy*self.scale, sw, sh, sang)
            flat2 = [v for p in pts2 for v in p]
            self._guide_ids.append(
                self.cv.create_polygon(*flat2,
                                       outline=col, fill="", width=1))

        # Corner clicks so far for current segment
        for (px, py) in self.corners:
            self._guide_ids.append(
                self.cv.create_oval(px*self.scale-3, py*self.scale-3,
                                    px*self.scale+3, py*self.scale+3,
                                    fill="white", outline=""))

    # ── click handling ───────────────────────────────────────────────────────

    def on_click(self, event):
        ox = round(event.x / self.scale)
        oy = round(event.y / self.scale)

        if self.phase == "cities":
            city = CITIES[self.city_idx]
            self.city_pos[city] = (ox, oy)
            dot = self.cv.create_oval(event.x-5, event.y-5,
                                      event.x+5, event.y+5,
                                      fill="#FCD34D", outline="white", width=1)
            lbl = self.cv.create_text(event.x+8, event.y-8, text=city[:5],
                                      fill="#FCD34D", font=("Arial", 8, "bold"))
            self.history.append(("city", city, dot, lbl))
            self.city_idx += 1
            self._save()
            self._refresh()

        elif self.phase == "routes":
            self.corners.append((ox, oy))
            if len(self.corners) == 4:
                self._commit_segment()
            else:
                self._refresh()

    def _commit_segment(self):
        route = ROUTES[self.route_idx]
        rid   = route["id"]

        # Fit minAreaRect to the 4 clicked corners
        pts = np.array(self.corners, dtype=np.float32)
        (cx, cy), (w, h), angle = cv2.minAreaRect(pts)
        if w < h:
            w, h = h, w
            angle = (angle + 90) % 180
        seg = (round(cx), round(cy), round(angle, 1))

        if rid not in self.route_segs:
            self.route_segs[rid] = []
        self.route_segs[rid].append(seg)

        # Draw permanent confirmed rect
        col  = COLOR_HEX.get(route["color"], "#fff")
        pts2 = _rot_rect(cx*self.scale, cy*self.scale,
                         w*self.scale, h*self.scale, angle)
        flat = [v for p in pts2 for v in p]
        rect_id = self.cv.create_polygon(*flat, outline=col,
                                         fill=col, stipple="gray50", width=1)
        self.history.append(("seg", rid, len(self.route_segs[rid])-1, rect_id))
        self.corners = []

        # Advance
        self.seg_idx += 1
        if self.seg_idx >= route["length"]:
            self.route_idx += 1
            self.seg_idx    = 0

        self._save()
        self._refresh()

    # ── undo ─────────────────────────────────────────────────────────────────

    def undo(self, _=None):
        if self.corners:
            self.corners.pop()
            self._refresh()
            return
        if not self.history:
            return
        last = self.history.pop()
        if last[0] == "city":
            _, city, dot, lbl = last
            self.cv.delete(dot); self.cv.delete(lbl)
            self.city_pos.pop(city, None)
            self.city_idx -= 1
            self.phase = "cities"
        elif last[0] == "seg":
            _, rid, seg_i, rect_id = last
            self.cv.delete(rect_id)
            if rid in self.route_segs and len(self.route_segs[rid]) > seg_i:
                self.route_segs[rid] = self.route_segs[rid][:seg_i]
            # Find the route index again
            for i, r in enumerate(ROUTES):
                if r["id"] == rid:
                    self.route_idx = i
                    self.seg_idx   = seg_i
                    break
            self.phase = "routes"
        self._save()
        self._refresh()

    # ── finish ───────────────────────────────────────────────────────────────

    def _finish(self):
        self.lbl.config(text="All done!  Saving outputs…", fg="#6EE7B7")
        self.cnt.config(text=f"{TOTAL_SEGS} / {TOTAL_SEGS} segs")
        self._write_outputs()

    def close(self):
        self._save()
        self._write_outputs()
        self.root.destroy()


# ── geometry helper ───────────────────────────────────────────────────────────

def _rot_rect(cx, cy, w, h, angle_deg):
    a  = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    hw, hh = w/2, h/2
    return [(cx + x*ca - y*sa, cy + x*sa + y*ca)
            for x, y in ((-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh))]


if __name__ == "__main__":
    root = tk.Tk()
    app  = BoardCalibrator(root)
    root.mainloop()
