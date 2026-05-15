"""
Draw bounding boxes around sample board elements.
Saves templates.json for the auto-detection script.

Targets: 1 city dot, then one train car slot of each color.
Click and drag to draw each box. Enter/Space to confirm, Backspace to redo.
"""
import tkinter as tk
from PIL import Image, ImageTk
import json

IMAGE_PATH = "static/images/board.png"
OUTPUT     = "templates.json"

TARGETS = [
    ("city_dot",    "a CITY DOT (the small orange circle)"),
    ("car_gray",    "a GRAY train car slot"),
    ("car_yellow",  "a YELLOW train car slot"),
    ("car_blue",    "a BLUE train car slot"),
    ("car_red",     "a RED train car slot"),
    ("car_green",   "a GREEN train car slot"),
    ("car_orange",  "an ORANGE train car slot"),
    ("car_white",   "a WHITE train car slot"),
    ("car_purple",  "a PURPLE train car slot"),
    ("car_black",   "a BLACK train car slot"),
]

TARGET_COLOR = {
    "city_dot":   "#f59e0b",
    "car_gray":   "#9ca3af",
    "car_yellow": "#EAB308",
    "car_blue":   "#3B82F6",
    "car_red":    "#EF4444",
    "car_green":  "#22C55E",
    "car_orange": "#F97316",
    "car_white":  "#e2e8f0",
    "car_purple": "#A855F7",
    "car_black":  "#6B7280",
}


class BoxDrawer:
    def __init__(self, root):
        self.root = root
        self.idx = 0
        self.boxes = {}
        self.drag_start = None
        self.current_rect = None

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        img = Image.open(IMAGE_PATH)
        self.orig_w, self.orig_h = img.size
        self.scale = min((sw - 20) / self.orig_w, (sh - 64) / self.orig_h)
        dw = int(self.orig_w * self.scale)
        dh = int(self.orig_h * self.scale)
        self.photo = ImageTk.PhotoImage(img.resize((dw, dh), Image.LANCZOS))

        root.title("Template Drawer")
        root.configure(bg="#1a1a2e")
        root.resizable(False, False)

        bar = tk.Frame(root, bg="#1a1a2e", height=64)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.lbl = tk.Label(bar, text="", font=("Arial", 13, "bold"),
                             bg="#1a1a2e", fg="#f59e0b", anchor="w")
        self.lbl.pack(side="left", padx=14, pady=10)
        self.lbl_r = tk.Label(bar, text="", font=("Arial", 11),
                               bg="#1a1a2e", fg="#9ca3af", anchor="e")
        self.lbl_r.pack(side="right", padx=14)

        self.canvas = tk.Canvas(root, width=dw, height=dh,
                                cursor="crosshair", bg="black",
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        self.canvas.bind("<ButtonPress-1>",   self.on_press)
        self.canvas.bind("<B1-Motion>",       self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<Return>",    self.confirm)
        root.bind("<space>",     self.confirm)
        root.bind("<BackSpace>", self.redo)

        self.update_prompt()

    def _to_orig(self, x, y):
        return round(x / self.scale), round(y / self.scale)

    def update_prompt(self):
        if self.idx >= len(TARGETS):
            self.finish()
            return
        key, desc = TARGETS[self.idx]
        color = TARGET_COLOR[key]
        self.lbl.config(
            text=f"[{self.idx+1}/{len(TARGETS)}]  Draw box around {desc}",
            fg=color)
        self.lbl_r.config(text="drag to draw  ·  Enter = confirm  ·  Backspace = redo")

    def on_press(self, e):
        self.drag_start = (e.x, e.y)
        if self.current_rect:
            self.canvas.delete(self.current_rect)
            self.current_rect = None

    def on_drag(self, e):
        if not self.drag_start:
            return
        if self.current_rect:
            self.canvas.delete(self.current_rect)
        x0, y0 = self.drag_start
        key = TARGETS[self.idx][0]
        color = TARGET_COLOR[key]
        self.current_rect = self.canvas.create_rectangle(
            x0, y0, e.x, e.y,
            outline=color, width=2, dash=(4, 2))

    def on_release(self, e):
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        x1, y1 = e.x, e.y
        # normalize so x0<x1, y0<y1
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        if abs(x1-x0) < 4 or abs(y1-y0) < 4:
            return
        ox0, oy0 = self._to_orig(x0, y0)
        ox1, oy1 = self._to_orig(x1, y1)
        key = TARGETS[self.idx][0]
        self.boxes[key] = [ox0, oy0, ox1, oy1]
        # redraw solid
        if self.current_rect:
            self.canvas.delete(self.current_rect)
        color = TARGET_COLOR[key]
        self.current_rect = self.canvas.create_rectangle(
            x0, y0, x1, y1, outline=color, width=2)
        self.canvas.create_text(
            (x0+x1)/2, y0-6,
            text=key, fill=color, font=("Arial", 9, "bold"))
        self.lbl_r.config(text="✓ drawn — Enter to confirm, Backspace to redo")

    def confirm(self, _=None):
        key = TARGETS[self.idx][0]
        if key not in self.boxes:
            return
        self.current_rect = None
        self.drag_start = None
        self.idx += 1
        self.update_prompt()

    def redo(self, _=None):
        key = TARGETS[self.idx][0]
        self.boxes.pop(key, None)
        if self.current_rect:
            self.canvas.delete(self.current_rect)
            self.current_rect = None
        self.drag_start = None
        self.lbl_r.config(text="drag to draw  ·  Enter = confirm  ·  Backspace = redo")

    def finish(self):
        self.lbl.config(text="All done! Saving templates.json…", fg="#22c55e")
        with open(OUTPUT, "w") as f:
            json.dump(self.boxes, f, indent=2)
        print(f"Saved {OUTPUT}:")
        for k, v in self.boxes.items():
            print(f"  {k}: {v}")
        self.root.after(1500, self.root.destroy)


root = tk.Tk()
app = BoxDrawer(root)
root.mainloop()
