"""
Click every train car slot of each color. Space/Enter = next color. Backspace = undo.
Also click all 36 city dots at the end.
Saves color_points.json.
"""
import tkinter as tk
from PIL import Image, ImageTk
import json

IMAGE_PATH = "static/images/board.png"
OUTPUT     = "color_points.json"

TARGETS = [
    ("gray",   "ALL GRAY car slots",        "#9ca3af"),
    ("yellow", "ALL YELLOW car slots",      "#EAB308"),
    ("blue",   "ALL BLUE car slots",        "#3B82F6"),
    ("red",    "ALL RED car slots",         "#EF4444"),
    ("green",  "ALL GREEN car slots",       "#22C55E"),
    ("orange", "ALL ORANGE car slots",      "#F97316"),
    ("white",  "ALL WHITE car slots",       "#e2e8f0"),
    ("pink",   "ALL PINK/PURPLE car slots", "#A855F7"),
    ("black",  "ALL BLACK car slots",       "#6B7280"),
    ("city",   "ALL 36 CITY DOTS",          "#f59e0b"),
]

class MultiPicker:
    def __init__(self, root):
        self.root  = root
        self.idx   = 0
        self.data  = {t[0]: [] for t in TARGETS}
        self.marks = []   # canvas item ids for current color

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        img = Image.open(IMAGE_PATH)
        self.orig_w, self.orig_h = img.size
        self.scale = min((sw - 20) / self.orig_w, (sh - 72) / self.orig_h)
        dw = int(self.orig_w  * self.scale)
        dh = int(self.orig_h  * self.scale)
        self.photo = ImageTk.PhotoImage(img.resize((dw, dh), Image.LANCZOS))

        root.title("Car Clicker")
        root.configure(bg="#1a1a2e")
        root.resizable(False, False)

        bar = tk.Frame(root, bg="#1a1a2e", height=72)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.lbl = tk.Label(bar, text="", font=("Arial", 13, "bold"),
                             bg="#1a1a2e", anchor="w")
        self.lbl.pack(side="left", padx=14, pady=8)
        self.count_lbl = tk.Label(bar, text="0 clicks", font=("Arial", 12),
                                   bg="#1a1a2e", fg="#9ca3af", anchor="e")
        self.count_lbl.pack(side="right", padx=14)

        self.canvas = tk.Canvas(root, width=dw, height=dh,
                                cursor="crosshair", bg="black",
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<Button-1>", self.on_click)
        root.bind("<Return>",    self.next_color)
        root.bind("<space>",     self.next_color)
        root.bind("<BackSpace>", self.undo)

        self.update_prompt()

    def update_prompt(self):
        if self.idx >= len(TARGETS):
            self.finish()
            return
        key, desc, color = TARGETS[self.idx]
        n = len(self.data[key])
        self.lbl.config(
            text=f"[{self.idx+1}/{len(TARGETS)}]  Click {desc}  —  Space/Enter when done",
            fg=color)
        self.count_lbl.config(text=f"{n} clicks")

    def on_click(self, event):
        if self.idx >= len(TARGETS):
            return
        ox = round(event.x / self.scale)
        oy = round(event.y / self.scale)
        key, _, color = TARGETS[self.idx]
        self.data[key].append([ox, oy])

        r = 4
        m = self.canvas.create_oval(event.x-r, event.y-r,
                                     event.x+r, event.y+r,
                                     fill=color, outline="")
        self.marks.append(m)
        n = len(self.data[key])
        self.count_lbl.config(text=f"{n} clicks")

    def undo(self, _=None):
        key = TARGETS[self.idx][0]
        if not self.data[key]:
            return
        self.data[key].pop()
        if self.marks:
            self.canvas.delete(self.marks.pop())
        self.count_lbl.config(text=f"{len(self.data[key])} clicks")

    def next_color(self, _=None):
        key = TARGETS[self.idx][0]
        if not self.data[key]:
            return   # require at least one click
        self.marks = []
        self.idx += 1
        self.update_prompt()

    def finish(self):
        self.lbl.config(text="Saving color_points.json…", fg="#22c55e")
        with open(OUTPUT, "w") as f:
            json.dump(self.data, f, indent=2)
        totals = {k: len(v) for k, v in self.data.items()}
        print(f"Saved {OUTPUT}:", totals)
        self.root.after(1500, self.root.destroy)

root = tk.Tk()
app  = MultiPicker(root)
root.mainloop()
