"""
Phase 1: Click each city dot.
Phase 2: Scroll to size the train car box, then Enter to confirm.
Phase 3: Click each route segment center. A/D = fast rotate, side buttons = fine rotate.
Saves city_coords.py and route_segments.py when done.
"""
import tkinter as tk
from PIL import Image, ImageTk
import math

IMAGE_PATH   = "static/images/board.png"
CITIES_OUT   = "city_coords.py"
SEGMENTS_OUT = "route_segments.py"

CITIES = [
    "Vancouver", "Seattle", "Portland", "San Francisco", "Los Angeles",
    "Las Vegas", "Salt Lake City", "Helena", "Calgary", "Winnipeg",
    "Denver", "Omaha", "Duluth", "Sault St. Marie", "Kansas City",
    "Chicago", "Saint Louis", "Oklahoma City", "Dallas", "Houston",
    "Little Rock", "New Orleans", "Nashville", "Atlanta", "Raleigh",
    "Charleston", "Miami", "Washington", "Pittsburgh", "New York",
    "Boston", "Montreal", "Toronto", "Santa Fe", "Phoenix", "El Paso",
]

ROUTES = [
    {"id":  1, "city1": "Vancouver",      "city2": "Seattle",        "length": 1, "color": "gray",   "side": 0},
    {"id":  2, "city1": "Vancouver",      "city2": "Seattle",        "length": 1, "color": "gray",   "side": 1},
    {"id":  3, "city1": "Vancouver",      "city2": "Calgary",        "length": 3, "color": "gray",   "side": 0},
    {"id":  4, "city1": "Seattle",        "city2": "Portland",       "length": 1, "color": "gray",   "side": 0},
    {"id":  5, "city1": "Seattle",        "city2": "Portland",       "length": 1, "color": "gray",   "side": 1},
    {"id":  6, "city1": "Seattle",        "city2": "Helena",         "length": 6, "color": "yellow", "side": 0},
    {"id":  7, "city1": "Portland",       "city2": "San Francisco",  "length": 5, "color": "green",  "side": 0},
    {"id":  8, "city1": "Portland",       "city2": "San Francisco",  "length": 5, "color": "purple", "side": 1},
    {"id":  9, "city1": "Portland",       "city2": "Salt Lake City", "length": 6, "color": "blue",   "side": 0},
    {"id": 10, "city1": "San Francisco",  "city2": "Los Angeles",    "length": 3, "color": "yellow", "side": 0},
    {"id": 11, "city1": "San Francisco",  "city2": "Los Angeles",    "length": 3, "color": "purple", "side": 1},
    {"id": 12, "city1": "San Francisco",  "city2": "Salt Lake City", "length": 5, "color": "orange", "side": 0},
    {"id": 13, "city1": "San Francisco",  "city2": "Salt Lake City", "length": 5, "color": "white",  "side": 1},
    {"id": 14, "city1": "Los Angeles",    "city2": "Las Vegas",      "length": 2, "color": "gray",   "side": 0},
    {"id": 15, "city1": "Los Angeles",    "city2": "Phoenix",        "length": 3, "color": "gray",   "side": 0},
    {"id": 16, "city1": "Los Angeles",    "city2": "El Paso",        "length": 6, "color": "black",  "side": 0},
    {"id": 17, "city1": "Las Vegas",      "city2": "Salt Lake City", "length": 3, "color": "orange", "side": 0},
    {"id": 18, "city1": "Salt Lake City", "city2": "Denver",         "length": 3, "color": "red",    "side": 0},
    {"id": 19, "city1": "Salt Lake City", "city2": "Denver",         "length": 3, "color": "yellow", "side": 1},
    {"id": 20, "city1": "Salt Lake City", "city2": "Helena",         "length": 3, "color": "purple", "side": 0},
    {"id": 21, "city1": "Denver",         "city2": "Helena",         "length": 4, "color": "green",  "side": 0},
    {"id": 22, "city1": "Denver",         "city2": "Omaha",          "length": 4, "color": "purple", "side": 0},
    {"id": 23, "city1": "Denver",         "city2": "Kansas City",    "length": 4, "color": "black",  "side": 0},
    {"id": 24, "city1": "Denver",         "city2": "Kansas City",    "length": 4, "color": "orange", "side": 1},
    {"id": 25, "city1": "Denver",         "city2": "Oklahoma City",  "length": 4, "color": "red",    "side": 0},
    {"id": 26, "city1": "Denver",         "city2": "Santa Fe",       "length": 2, "color": "gray",   "side": 0},
    {"id": 27, "city1": "Helena",         "city2": "Calgary",        "length": 4, "color": "gray",   "side": 0},
    {"id": 28, "city1": "Helena",         "city2": "Winnipeg",       "length": 4, "color": "blue",   "side": 0},
    {"id": 29, "city1": "Helena",         "city2": "Duluth",         "length": 6, "color": "orange", "side": 0},
    {"id": 30, "city1": "Helena",         "city2": "Omaha",          "length": 5, "color": "red",    "side": 0},
    {"id": 31, "city1": "Calgary",        "city2": "Winnipeg",       "length": 6, "color": "white",  "side": 0},
    {"id": 32, "city1": "Winnipeg",       "city2": "Duluth",         "length": 4, "color": "black",  "side": 0},
    {"id": 33, "city1": "Winnipeg",       "city2": "Sault St. Marie","length": 6, "color": "gray",   "side": 0},
    {"id": 34, "city1": "Duluth",         "city2": "Omaha",          "length": 2, "color": "gray",   "side": 0},
    {"id": 35, "city1": "Duluth",         "city2": "Chicago",        "length": 3, "color": "red",    "side": 0},
    {"id": 36, "city1": "Duluth",         "city2": "Toronto",        "length": 6, "color": "purple", "side": 0},
    {"id": 37, "city1": "Duluth",         "city2": "Sault St. Marie","length": 3, "color": "gray",   "side": 0},
    {"id": 38, "city1": "Omaha",          "city2": "Kansas City",    "length": 1, "color": "gray",   "side": 0},
    {"id": 39, "city1": "Omaha",          "city2": "Kansas City",    "length": 1, "color": "gray",   "side": 1},
    {"id": 40, "city1": "Omaha",          "city2": "Chicago",        "length": 4, "color": "blue",   "side": 0},
    {"id": 41, "city1": "Kansas City",    "city2": "Saint Louis",    "length": 2, "color": "blue",   "side": 0},
    {"id": 42, "city1": "Kansas City",    "city2": "Saint Louis",    "length": 2, "color": "purple", "side": 1},
    {"id": 43, "city1": "Kansas City",    "city2": "Oklahoma City",  "length": 2, "color": "gray",   "side": 0},
    {"id": 44, "city1": "Kansas City",    "city2": "Oklahoma City",  "length": 2, "color": "gray",   "side": 1},
    {"id": 45, "city1": "Chicago",        "city2": "Saint Louis",    "length": 2, "color": "green",  "side": 0},
    {"id": 46, "city1": "Chicago",        "city2": "Saint Louis",    "length": 2, "color": "white",  "side": 1},
    {"id": 47, "city1": "Chicago",        "city2": "Pittsburgh",     "length": 3, "color": "orange", "side": 0},
    {"id": 48, "city1": "Santa Fe",       "city2": "Oklahoma City",  "length": 3, "color": "blue",   "side": 0},
    {"id": 49, "city1": "Santa Fe",       "city2": "El Paso",        "length": 2, "color": "gray",   "side": 0},
    {"id": 50, "city1": "Phoenix",        "city2": "Denver",         "length": 5, "color": "white",  "side": 0},
    {"id": 51, "city1": "Phoenix",        "city2": "El Paso",        "length": 3, "color": "gray",   "side": 0},
    {"id": 52, "city1": "El Paso",        "city2": "Dallas",         "length": 4, "color": "red",    "side": 0},
    {"id": 53, "city1": "El Paso",        "city2": "Houston",        "length": 6, "color": "green",  "side": 0},
    {"id": 54, "city1": "Oklahoma City",  "city2": "Dallas",         "length": 2, "color": "gray",   "side": 0},
    {"id": 55, "city1": "Oklahoma City",  "city2": "Dallas",         "length": 2, "color": "gray",   "side": 1},
    {"id": 56, "city1": "Oklahoma City",  "city2": "Little Rock",    "length": 2, "color": "gray",   "side": 0},
    {"id": 57, "city1": "Dallas",         "city2": "Little Rock",    "length": 2, "color": "gray",   "side": 0},
    {"id": 58, "city1": "Dallas",         "city2": "Houston",        "length": 1, "color": "gray",   "side": 0},
    {"id": 59, "city1": "Dallas",         "city2": "Houston",        "length": 1, "color": "gray",   "side": 1},
    {"id": 60, "city1": "Houston",        "city2": "New Orleans",    "length": 2, "color": "gray",   "side": 0},
    {"id": 61, "city1": "Little Rock",    "city2": "Saint Louis",    "length": 2, "color": "gray",   "side": 0},
    {"id": 62, "city1": "Little Rock",    "city2": "Nashville",      "length": 3, "color": "white",  "side": 0},
    {"id": 63, "city1": "Little Rock",    "city2": "New Orleans",    "length": 3, "color": "green",  "side": 0},
    {"id": 64, "city1": "New Orleans",    "city2": "Atlanta",        "length": 4, "color": "yellow", "side": 0},
    {"id": 65, "city1": "New Orleans",    "city2": "Atlanta",        "length": 4, "color": "orange", "side": 1},
    {"id": 66, "city1": "New Orleans",    "city2": "Miami",          "length": 6, "color": "red",    "side": 0},
    {"id": 67, "city1": "Nashville",      "city2": "Saint Louis",    "length": 2, "color": "gray",   "side": 0},
    {"id": 68, "city1": "Nashville",      "city2": "Atlanta",        "length": 1, "color": "gray",   "side": 0},
    {"id": 69, "city1": "Nashville",      "city2": "Pittsburgh",     "length": 4, "color": "yellow", "side": 0},
    {"id": 70, "city1": "Nashville",      "city2": "Raleigh",        "length": 3, "color": "black",  "side": 0},
    {"id": 71, "city1": "Atlanta",        "city2": "Raleigh",        "length": 2, "color": "gray",   "side": 0},
    {"id": 72, "city1": "Atlanta",        "city2": "Charleston",     "length": 2, "color": "gray",   "side": 0},
    {"id": 73, "city1": "Atlanta",        "city2": "Miami",          "length": 5, "color": "blue",   "side": 0},
    {"id": 74, "city1": "Raleigh",        "city2": "Charleston",     "length": 2, "color": "gray",   "side": 0},
    {"id": 75, "city1": "Raleigh",        "city2": "Washington",     "length": 2, "color": "gray",   "side": 0},
    {"id": 76, "city1": "Raleigh",        "city2": "Washington",     "length": 2, "color": "gray",   "side": 1},
    {"id": 77, "city1": "Raleigh",        "city2": "Pittsburgh",     "length": 2, "color": "gray",   "side": 0},
    {"id": 78, "city1": "Washington",     "city2": "Pittsburgh",     "length": 2, "color": "gray",   "side": 0},
    {"id": 79, "city1": "Washington",     "city2": "Pittsburgh",     "length": 2, "color": "gray",   "side": 1},
    {"id": 80, "city1": "Washington",     "city2": "New York",       "length": 2, "color": "orange", "side": 0},
    {"id": 81, "city1": "Washington",     "city2": "New York",       "length": 2, "color": "black",  "side": 1},
    {"id": 82, "city1": "Pittsburgh",     "city2": "New York",       "length": 2, "color": "white",  "side": 0},
    {"id": 83, "city1": "Pittsburgh",     "city2": "New York",       "length": 2, "color": "green",  "side": 1},
    {"id": 84, "city1": "Pittsburgh",     "city2": "Toronto",        "length": 2, "color": "gray",   "side": 0},
    {"id": 85, "city1": "Pittsburgh",     "city2": "Saint Louis",    "length": 5, "color": "green",  "side": 0},
    {"id": 86, "city1": "New York",       "city2": "Boston",         "length": 2, "color": "yellow", "side": 0},
    {"id": 87, "city1": "New York",       "city2": "Boston",         "length": 2, "color": "red",    "side": 1},
    {"id": 88, "city1": "New York",       "city2": "Montreal",       "length": 3, "color": "blue",   "side": 0},
    {"id": 89, "city1": "Boston",         "city2": "Montreal",       "length": 2, "color": "gray",   "side": 0},
    {"id": 90, "city1": "Boston",         "city2": "Montreal",       "length": 2, "color": "gray",   "side": 1},
    {"id": 91, "city1": "Montreal",       "city2": "Toronto",        "length": 3, "color": "gray",   "side": 0},
    {"id": 92, "city1": "Montreal",       "city2": "Sault St. Marie","length": 5, "color": "black",  "side": 0},
    {"id": 93, "city1": "Toronto",        "city2": "Sault St. Marie","length": 2, "color": "gray",   "side": 0},
    {"id": 94, "city1": "Toronto",        "city2": "Chicago",        "length": 4, "color": "white",  "side": 0},
]

COLOR_HEX = {
    "purple": "#A855F7", "blue": "#3B82F6", "orange": "#F97316",
    "white":  "#e2e8f0", "green": "#22C55E", "yellow": "#EAB308",
    "black":  "#6B7280", "red":   "#EF4444", "gray":   "#9ca3af",
}

TOTAL_SEGS = sum(r["length"] for r in ROUTES)

ROTATE_FAST = 15   # A / D keys
ROTATE_FINE = 1    # side mouse buttons
ROTATE_WHEEL = 3   # scroll wheel (routes phase)


class Calibrator:
    def __init__(self, root):
        self.root = root
        self.city_coords = {}
        self.route_segs  = {}

        self.phase      = "cities"
        self.city_idx   = 0
        self.route_idx  = 0
        self.seg_idx    = 0
        self.cur_angle  = 0.0
        self.segs_done  = 0

        # car size in display pixels (calibrated in size_cal phase)
        self.car_w = 22.0
        self.car_h = 9.0

        self.cursor_items = []
        self.placed_items = []

        # fit image to screen
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        img = Image.open(IMAGE_PATH)
        self.orig_w, self.orig_h = img.size
        LABEL_H = 56
        self.scale = min((sw - 20) / self.orig_w, (sh - LABEL_H - 30) / self.orig_h)
        dw = int(self.orig_w * self.scale)
        dh = int(self.orig_h * self.scale)
        self.photo = ImageTk.PhotoImage(img.resize((dw, dh), Image.LANCZOS))

        root.title("Board Calibrator")
        root.configure(bg="#1a1a2e")
        root.resizable(False, False)

        # label bar
        bar = tk.Frame(root, bg="#1a1a2e", height=LABEL_H)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.lbl_main = tk.Label(bar, text="", font=("Arial", 13, "bold"),
                                  bg="#1a1a2e", fg="#f59e0b", anchor="w")
        self.lbl_main.pack(side="left", padx=12, pady=6)
        self.lbl_count = tk.Label(bar, text="", font=("Arial", 12, "bold"),
                                   bg="#1a1a2e", fg="#22c55e", anchor="e")
        self.lbl_count.pack(side="right", padx=14)

        # canvas
        self.canvas = tk.Canvas(root, width=dw, height=dh,
                                cursor="none", bg="black", highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        self.canvas.bind("<Motion>",      self.on_motion)
        self.canvas.bind("<ButtonPress>", self.on_any_button)
        self.canvas.bind("<Leave>",       self.on_leave)
        self.canvas.bind("<MouseWheel>",  self.on_wheel)
        root.bind("<BackSpace>", self.undo)
        root.bind("<a>", lambda e: self.rotate(-ROTATE_FAST))
        root.bind("<d>", lambda e: self.rotate( ROTATE_FAST))
        root.bind("<A>", lambda e: self.rotate(-ROTATE_FAST))
        root.bind("<D>", lambda e: self.rotate( ROTATE_FAST))
        root.bind("<Return>",  self.confirm_size)
        root.bind("<space>",   self.confirm_size)
        root.bind("<Up>",      lambda e: self._resize(0,  1))
        root.bind("<Down>",    lambda e: self._resize(0, -1))
        root.bind("<Right>",   lambda e: self._resize( 1, 0))
        root.bind("<Left>",    lambda e: self._resize(-1, 0))

        self.update_prompt()

    # ── cursor ────────────────────────────────────────────────────────────────

    def _clear_cursor(self):
        for item in self.cursor_items:
            self.canvas.delete(item)
        self.cursor_items = []

    def _draw_cursor(self, ex, ey):
        self._clear_cursor()
        items = []
        if self.phase == "cities":
            r = 9
            items += [
                self.canvas.create_oval(ex-r, ey-r, ex+r, ey+r,
                                         outline="#f59e0b", width=2),
                self.canvas.create_line(ex-r+2, ey, ex+r-2, ey,
                                         fill="#f59e0b", width=1),
                self.canvas.create_line(ex, ey-r+2, ex, ey+r-2,
                                         fill="#f59e0b", width=1),
                self.canvas.create_oval(ex-1, ey-1, ex+1, ey+1,
                                         fill="#f59e0b", outline=""),
            ]
        elif self.phase == "size_cal":
            # show grey car box, no rotation
            pts = _rot_rect(ex, ey, self.car_w, self.car_h, 0)
            flat = [v for p in pts for v in p]
            items += [
                self.canvas.create_polygon(*flat, outline="#f59e0b",
                                            fill="#f59e0b33", width=2),
                self.canvas.create_oval(ex-2, ey-2, ex+2, ey+2,
                                         fill="#f59e0b", outline=""),
            ]
        else:
            color = COLOR_HEX.get(ROUTES[self.route_idx]["color"], "#fff")
            pts = _rot_rect(ex, ey, self.car_w, self.car_h, self.cur_angle)
            flat = [v for p in pts for v in p]
            items += [
                self.canvas.create_polygon(*flat, outline=color,
                                            fill=color + "44", width=2),
                self.canvas.create_oval(ex-2, ey-2, ex+2, ey+2,
                                         fill=color, outline=""),
            ]
        self.cursor_items = items
        for i in items:
            self.canvas.tag_raise(i)

    def on_motion(self, event):
        self._draw_cursor(event.x, event.y)

    def on_leave(self, _):
        self._clear_cursor()

    # ── input ─────────────────────────────────────────────────────────────────

    def on_any_button(self, event):
        if event.num == 1:
            self.on_click(event)
        elif event.num == 8:
            self.rotate(-ROTATE_FINE)
        elif event.num == 9:
            self.rotate( ROTATE_FINE)

    def on_wheel(self, event):
        if self.phase == "routes":
            up = event.delta > 0
            self.rotate(-ROTATE_WHEEL if up else ROTATE_WHEEL)

    def rotate(self, delta):
        if self.phase not in ("routes", "size_cal"):
            return
        self.cur_angle = (self.cur_angle + delta) % 360
        self.update_prompt()

    def confirm_size(self, _=None):
        if self.phase == "size_cal":
            self._start_routes()

    def _resize(self, dw, dh):
        if self.phase != "size_cal":
            return
        self.car_w = max(4, self.car_w + dw)
        self.car_h = max(2, self.car_h + dh)
        self.update_prompt()

    # ── phases ────────────────────────────────────────────────────────────────

    def _start_size_cal(self):
        # Save city_coords.py as soon as cities are done so closing early still works
        with open(CITIES_OUT, "w") as f:
            f.write("CITIES = {\n")
            for city in CITIES:
                x, y = self.city_coords.get(city, (0, 0))
                f.write(f'    "{city}":{" "*(20-len(city))}({x:4d}, {y:4d}),\n')
            f.write("}\n")
        print(f"[cities done] Saved {CITIES_OUT}  — close now to stop here, or continue for route segments")
        self.phase = "size_cal"
        self.update_prompt()

    def _start_routes(self):
        self.phase     = "routes"
        self.route_idx = 0
        self.seg_idx   = 0
        self._set_auto_angle()
        self.update_prompt()

    def _set_auto_angle(self):
        if self.route_idx >= len(ROUTES):
            return
        r = ROUTES[self.route_idx]
        c1 = self.city_coords.get(r["city1"])
        c2 = self.city_coords.get(r["city2"])
        if c1 and c2:
            self.cur_angle = math.degrees(
                math.atan2(c2[1]-c1[1], c2[0]-c1[0])) % 360

    def update_prompt(self):
        if self.phase == "cities":
            if self.city_idx >= len(CITIES):
                self._start_size_cal()
                return
            self.lbl_main.config(
                text=f"CITIES — click dot: {CITIES[self.city_idx]}",
                fg="#f59e0b")
            self.lbl_count.config(
                text=f"{self.city_idx} / {len(CITIES)} cities")

        elif self.phase == "size_cal":
            self.lbl_main.config(
                text=f"SIZE — scroll to fit a train car box  ·  Enter to confirm  "
                     f"(w={self.car_w:.1f} h={self.car_h:.1f})",
                fg="#38bdf8")
            self.lbl_count.config(text="size calibration")

        else:  # routes
            if self.route_idx >= len(ROUTES):
                self._finish()
                return
            r = ROUTES[self.route_idx]
            color = COLOR_HEX.get(r["color"], "#fff")
            self.lbl_main.config(
                text=f"R{r['id']}  {r['city1']} → {r['city2']}  "
                     f"[{r['color'].upper()}  ×{r['length']}  side={r['side']}]  "
                     f"seg {self.seg_idx+1}/{r['length']}  "
                     f"·  A/D fast  side-btn fine  scroll=rotate",
                fg=color)
            self.lbl_count.config(
                text=f"{self.segs_done} / {TOTAL_SEGS} segs")

    # ── clicking ──────────────────────────────────────────────────────────────

    def on_click(self, event):
        ox = round(event.x / self.scale)
        oy = round(event.y / self.scale)

        if self.phase == "cities":
            city = CITIES[self.city_idx]
            self.city_coords[city] = (ox, oy)
            r = 5
            m1 = self.canvas.create_oval(event.x-r, event.y-r,
                                          event.x+r, event.y+r,
                                          outline="#f59e0b", width=2)
            m2 = self.canvas.create_text(event.x+7, event.y-7, text=city,
                                          fill="#f59e0b",
                                          font=("Arial", 8, "bold"), anchor="w")
            self.placed_items.append(("city", city, m1, m2))
            self.city_idx += 1

        elif self.phase == "routes":
            route = ROUTES[self.route_idx]
            rid = route["id"]
            if rid not in self.route_segs:
                self.route_segs[rid] = []
            self.route_segs[rid].append((ox, oy, round(self.cur_angle, 1)))

            color = COLOR_HEX.get(route["color"], "#fff")
            pts = _rot_rect(event.x, event.y, self.car_w, self.car_h, self.cur_angle)
            flat = [v for p in pts for v in p]
            m1 = self.canvas.create_polygon(*flat, outline=color,
                                             fill=color + "55", width=1)
            m2 = self.canvas.create_text(event.x, event.y,
                                          text=f"{rid}.{self.seg_idx+1}",
                                          fill="white", font=("Arial", 6))
            self.placed_items.append(("seg", rid, self.seg_idx, m1, m2))
            self.segs_done += 1
            self.seg_idx += 1
            if self.seg_idx >= route["length"]:
                self.route_idx += 1
                self.seg_idx = 0
                self._set_auto_angle()

        self.update_prompt()
        self._draw_cursor(event.x, event.y)

    # ── undo ──────────────────────────────────────────────────────────────────

    def undo(self, _=None):
        if not self.placed_items:
            return
        item = self.placed_items.pop()
        if item[0] == "city":
            _, city, m1, m2 = item
            self.canvas.delete(m1); self.canvas.delete(m2)
            self.city_coords.pop(city, None)
            self.city_idx -= 1
            self.phase = "cities"
        else:
            _, rid, seg_i, m1, m2 = item
            self.canvas.delete(m1); self.canvas.delete(m2)
            if rid in self.route_segs and self.route_segs[rid]:
                self.route_segs[rid].pop()
                if not self.route_segs[rid]:
                    del self.route_segs[rid]
            self.route_idx = next(i for i, r in enumerate(ROUTES) if r["id"] == rid)
            self.seg_idx   = seg_i
            self.segs_done = max(0, self.segs_done - 1)
            self.phase = "routes"
        self.update_prompt()

    # ── finish ────────────────────────────────────────────────────────────────

    def _finish(self):
        self.lbl_main.config(text="All done! Saving…", fg="#22c55e")
        self.lbl_count.config(text=f"{TOTAL_SEGS} / {TOTAL_SEGS} segs ✓")

        with open(CITIES_OUT, "w") as f:
            f.write("CITIES = {\n")
            for city in CITIES:
                x, y = self.city_coords.get(city, (0, 0))
                f.write(f'    "{city}":{" "*(20-len(city))}({x:4d}, {y:4d}),\n')
            f.write("}\n")

        with open(SEGMENTS_OUT, "w") as f:
            f.write("# route_id -> [(center_x, center_y, angle_deg), ...]\n")
            f.write("ROUTE_SEGMENTS = {\n")
            for route in ROUTES:
                rid = route["id"]
                segs = self.route_segs.get(rid, [])
                f.write(f"    {rid}: {segs},\n")
            f.write("}\n")

        print(f"Saved {CITIES_OUT} and {SEGMENTS_OUT}")
        self.root.after(2000, self.root.destroy)


# ── geometry helper ───────────────────────────────────────────────────────────

def _rot_rect(cx, cy, w, h, angle_deg):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [(cx + x*ca - y*sa, cy + x*sa + y*ca) for x, y in corners]


root = tk.Tk()
app = Calibrator(root)
root.mainloop()
