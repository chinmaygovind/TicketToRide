#!/usr/bin/env python3
"""
Interactive city coordinate fixer.
Shows each city and prompts you to click its correct location on the board.
Saves corrected coordinates to city_coords.py.
"""
import tkinter as tk
from PIL import Image, ImageTk
import json
import os

IMAGE_PATH = "static/images/board.png"
OUTPUT     = "city_coords.py"

CITIES = [
    "Vancouver", "Seattle", "Portland", "San Francisco", "Los Angeles",
    "Las Vegas", "Salt Lake City", "Helena", "Calgary", "Winnipeg",
    "Denver", "Omaha", "Duluth", "Sault St. Marie", "Kansas City",
    "Chicago", "Saint Louis", "Oklahoma City", "Dallas", "Houston",
    "Little Rock", "New Orleans", "Nashville", "Atlanta", "Raleigh",
    "Charleston", "Miami", "Washington", "Pittsburgh", "New York",
    "Boston", "Montreal", "Toronto", "Santa Fe", "Phoenix", "El Paso",
]

class CityCorrectionTool:
    def __init__(self, root):
        self.root = root
        root.title("City Coordinate Corrector")
        root.configure(bg="#1a1a2e")
        
        # Load board image
        img = Image.open(IMAGE_PATH)
        self.orig_w, self.orig_h = img.size
        
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        self.scale = min((sw - 20) / self.orig_w, (sh - 100) / self.orig_h)
        dw = int(self.orig_w * self.scale)
        dh = int(self.orig_h * self.scale)
        
        self.photo = ImageTk.PhotoImage(img.resize((dw, dh), Image.LANCZOS))
        
        # Load current coordinates
        from city_coords import CITIES as current_coords
        self.coords = {k: list(v) for k, v in current_coords.items()}
        
        # UI elements
        bar = tk.Frame(root, bg="#1a1a2e", height=80)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        
        self.lbl = tk.Label(bar, text="", font=("Arial", 14, "bold"),
                            bg="#1a1a2e", fg="#FFD700", anchor="w", padx=14, pady=8)
        self.lbl.pack(fill="x")
        
        info = tk.Label(bar, text="Click the correct location for the highlighted city  |  Space=Skip  |  Backspace=Undo",
                       font=("Arial", 10), bg="#1a1a2e", fg="#999", anchor="w", padx=14)
        info.pack(fill="x")
        
        self.canvas = tk.Canvas(root, width=dw, height=dh,
                               cursor="crosshair", bg="black", highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<Button-1>", self.on_click)
        
        root.bind("<space>", self.skip_city)
        root.bind("<BackSpace>", self.undo)
        root.protocol("WM_DELETE_WINDOW", self.save_and_close)
        
        self.city_idx = 0
        self.history = []
        self.current_mark = None
        
        self.update_display()
    
    def update_display(self):
        if self.city_idx >= len(CITIES):
            self.lbl.config(text="✓ All cities corrected! Press Ctrl+W to save and close.", fg="#22ff22")
            return
        
        city = CITIES[self.city_idx]
        self.lbl.config(text=f"[{self.city_idx + 1}/{len(CITIES)}]  Click location for: {city}")
        
        # Draw current coordinates as a reference marker
        if city in self.coords:
            x, y = self.coords[city]
            sx, sy = int(x * self.scale), int(y * self.scale)
            
            # Remove old mark
            if self.current_mark:
                self.canvas.delete(self.current_mark)
            
            # Draw current position (green if being edited, gray if not)
            self.current_mark = self.canvas.create_oval(
                sx - 6, sy - 6, sx + 6, sy + 6,
                fill="#FFD700", outline="#FFFF00", width=2
            )
    
    def on_click(self, event):
        if self.city_idx >= len(CITIES):
            return
        
        # Convert screen coords back to original image coords
        ox = round(event.x / self.scale)
        oy = round(event.y / self.scale)
        
        city = CITIES[self.city_idx]
        old_pos = self.coords.get(city, None)
        self.history.append((city, old_pos))
        
        self.coords[city] = [ox, oy]
        self.city_idx += 1
        
        self.current_mark = None
        self.update_display()
    
    def skip_city(self, _=None):
        if self.city_idx < len(CITIES):
            self.city_idx += 1
            self.current_mark = None
            self.update_display()
    
    def undo(self, _=None):
        if not self.history:
            return
        city, old_pos = self.history.pop()
        if old_pos is not None:
            self.coords[city] = old_pos
        else:
            del self.coords[city]
        self.city_idx -= 1
        self.current_mark = None
        self.update_display()
    
    def save_and_close(self):
        with open(OUTPUT, 'w') as f:
            f.write("CITIES = {\n")
            for city in CITIES:
                if city in self.coords:
                    x, y = self.coords[city]
                    f.write(f'    "{city}":           ({x:3d}, {y:3d}),\n')
            f.write("}\n")
        print(f"Saved corrected cities to {OUTPUT}")
        self.root.destroy()

root = tk.Tk()
app = CityCorrectionTool(root)
root.mainloop()
