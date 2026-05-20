#!/usr/bin/env python3
"""
Interactive tool to trace European coastlines over the Europe board image.
Draw the land outline, inland seas, and rivers, then export to SVG.

Run from the project root:
    python scripts/board/trace_europe.py

Keys:
    1 = Coastline mode (land polygon)
    2 = Seas mode     (Mediterranean, Black Sea, etc. — filled water shapes)
    3 = Rivers mode   (thin lines)
    Z = Undo last stroke
    C = Clear all (asks confirmation)
    S = Save JSON + generate SVG
    Q = Quit
"""

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw, ImageTk
import json
import os
import sys

BOARD_W, BOARD_H = 1024, 681

# Locate europe_board.png — check a few candidate paths
def find_board_image():
    candidates = [
        'assets/europe_board.png',
        'static/images/europe_board.png',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

JSON_PATH = os.path.join(os.path.dirname(__file__), 'europe_trace.json')
SVG_OUT   = 'static/images/europe_board.svg'


class EuropeTracer:
    def __init__(self, root):
        self.root = root
        self.root.title("Europe Board Tracer — Coastline / Seas / Rivers")
        self.root.configure(bg='#1a1410')

        img_path = find_board_image()
        if not img_path:
            messagebox.showerror("Error", "Could not find europe_board.png.\nExpected at assets/europe_board.png")
            sys.exit(1)

        self.board_img = Image.open(img_path).convert('RGBA')
        # Resize to exact board dimensions if needed
        if self.board_img.size != (BOARD_W, BOARD_H):
            self.board_img = self.board_img.resize((BOARD_W, BOARD_H), Image.Resampling.LANCZOS)

        # Transparent overlay for drawn strokes
        self.overlay = Image.new('RGBA', (BOARD_W, BOARD_H), (0, 0, 0, 0))
        self.draw_obj = ImageDraw.Draw(self.overlay)

        # Data
        self.coastline = []   # list of [ (x,y), ... ] — one entry per land mass / island
        self.seas = []        # list of [ (x,y), ... ] strokes (filled polys when closed)
        self.rivers = []      # list of [ (x,y), ... ] thin lines
        self.current_stroke = []
        self.mode = 'coastline'
        self.drawing = False

        self._load()

        # ── Canvas ──────────────────────────────────────────────────────────
        top = tk.Frame(root, bg='#1a1410')
        top.pack(fill=tk.X, padx=6, pady=4)

        tk.Label(top, text="Europe Board Tracer", bg='#1a1410', fg='#c8a84b',
                 font=('Courier New', 11, 'bold')).pack(side=tk.LEFT)

        self.status_lbl = tk.Label(top, text='', bg='#1a1410', fg='#a09070',
                                   font=('Courier New', 9))
        self.status_lbl.pack(side=tk.RIGHT, padx=6)

        self.canvas = tk.Canvas(root, bg='#0a0a0a', cursor='crosshair',
                                width=BOARD_W, height=BOARD_H, highlightthickness=0)
        self.canvas.pack(padx=6, pady=2)

        self.photo = None
        self.canvas_img_id = self.canvas.create_image(0, 0, anchor='nw')
        self._redraw_all()

        self.canvas.bind('<Button-1>',       self._on_down)
        self.canvas.bind('<B1-Motion>',      self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_up)

        # ── Controls ─────────────────────────────────────────────────────────
        ctrl = tk.Frame(root, bg='#1a1410')
        ctrl.pack(fill=tk.X, padx=6, pady=6)

        self.mode_btns = {}
        for label, key, mkey in [
            ('1 Coastline', '1', 'coastline'),
            ('2 Seas',      '2', 'seas'),
            ('3 Rivers',    '3', 'rivers'),
        ]:
            b = tk.Button(ctrl, text=label, font=('Courier New', 9),
                          command=lambda m=mkey: self.set_mode(m),
                          bg='#2a2218', fg='#c8a84b', relief='flat',
                          padx=8, pady=4, bd=0)
            b.pack(side=tk.LEFT, padx=3)
            self.mode_btns[mkey] = b

        for label, cmd in [
            ('Z Undo', self.undo),
            ('C Clear', self.clear),
            ('S Save', self.save),
            ('Q Quit', root.quit),
        ]:
            tk.Button(ctrl, text=label, font=('Courier New', 9), command=cmd,
                      bg='#2a2218', fg='#e0d8c8', relief='flat',
                      padx=8, pady=4, bd=0).pack(side=tk.LEFT, padx=3)

        hints = tk.Label(root,
            text='Coastline = full land border polygon  |  Seas = Mediterranean/Black Sea etc (one stroke per sea)  |  Rivers = thin lines',
            bg='#1a1410', fg='#4a4038', font=('Courier New', 8))
        hints.pack(pady=2)

        root.bind('1', lambda e: self.set_mode('coastline'))
        root.bind('2', lambda e: self.set_mode('seas'))
        root.bind('3', lambda e: self.set_mode('rivers'))
        root.bind('z', lambda e: self.undo())
        root.bind('c', lambda e: self.clear())
        root.bind('s', lambda e: self.save())
        root.bind('q', lambda e: root.quit())

        self._update_mode_btns()
        self._update_status()

    # ── Drawing events ────────────────────────────────────────────────────────

    def _on_down(self, e):
        self.drawing = True
        self.current_stroke = []
        self._add_point(e.x, e.y)

    def _on_drag(self, e):
        if not self.drawing:
            return
        x, y = e.x, e.y
        if not (0 <= x < BOARD_W and 0 <= y < BOARD_H):
            return
        if self.current_stroke:
            lx, ly = self.current_stroke[-1]
            color = self._mode_color(self.mode)
            w = 1.5 if self.mode == 'rivers' else 3
            self.draw_obj.line([(lx, ly), (x, y)], fill=color, width=int(w))
        self.current_stroke.append((x, y))
        self._flush_canvas()

    def _on_up(self, e):
        if self.drawing and len(self.current_stroke) > 1:
            stroke = self.current_stroke[:]
            if self.mode == 'coastline':
                self.coastline.append(stroke)  # each drag = one land mass / island
            elif self.mode == 'seas':
                self.seas.append(stroke)
            elif self.mode == 'rivers':
                self.rivers.append(stroke)
        self.drawing = False
        self.current_stroke = []
        self._update_status()

    def _add_point(self, x, y):
        if 0 <= x < BOARD_W and 0 <= y < BOARD_H:
            self.current_stroke.append((x, y))

    # ── Mode ─────────────────────────────────────────────────────────────────

    def set_mode(self, mode):
        self.mode = mode
        self._update_mode_btns()

    def _update_mode_btns(self):
        for m, b in self.mode_btns.items():
            b.config(bg='#c8a84b' if m == self.mode else '#2a2218',
                     fg='#000000' if m == self.mode else '#c8a84b')

    def _mode_color(self, mode):
        return {
            'coastline': (200, 170, 120, 210),
            'seas':      ( 30, 140, 220, 200),
            'rivers':    ( 80, 180, 240, 180),
        }.get(mode, (200, 200, 200, 200))

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _redraw_all(self):
        self.overlay = Image.new('RGBA', (BOARD_W, BOARD_H), (0, 0, 0, 0))
        self.draw_obj = ImageDraw.Draw(self.overlay)

        # Coastline (one polygon per land mass)
        c = self._mode_color('coastline')
        for land in self.coastline:
            if len(land) > 1:
                for i in range(len(land) - 1):
                    self.draw_obj.line([land[i], land[i+1]], fill=c, width=3)

        # Seas
        c = self._mode_color('seas')
        for sea in self.seas:
            if len(sea) > 1:
                for i in range(len(sea) - 1):
                    self.draw_obj.line([sea[i], sea[i+1]], fill=c, width=3)

        # Rivers
        c = self._mode_color('rivers')
        for river in self.rivers:
            if len(river) > 1:
                for i in range(len(river) - 1):
                    self.draw_obj.line([river[i], river[i+1]], fill=c, width=2)

        self._flush_canvas()

    def _flush_canvas(self):
        combined = self.board_img.copy()
        combined.paste(self.overlay, (0, 0), self.overlay)
        self.photo = ImageTk.PhotoImage(combined)
        self.canvas.itemconfig(self.canvas_img_id, image=self.photo)

    # ── Edit ─────────────────────────────────────────────────────────────────

    def undo(self):
        if self.mode == 'coastline' and self.coastline:
            self.coastline.pop()
        elif self.mode == 'seas' and self.seas:
            self.seas.pop()
        elif self.mode == 'rivers' and self.rivers:
            self.rivers.pop()
        self._redraw_all()
        self._update_status()

    def clear(self):
        if messagebox.askyesno("Clear", "Clear all drawings?"):
            self.coastline = []
            self.seas = []
            self.rivers = []
            self.current_stroke = []
            self._redraw_all()
            self._update_status()

    # ── Persist ───────────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(JSON_PATH):
            return
        try:
            with open(JSON_PATH, 'r') as f:
                data = json.load(f)
            self.coastline = [[tuple(p) for p in land] for land in data.get('coastline', [])]
            self.seas      = [[tuple(p) for p in s] for s in data.get('seas', [])]
            self.rivers    = [[tuple(p) for p in r] for r in data.get('rivers', [])]
            print(f"Loaded: coastline={len(self.coastline)} pts, "
                  f"seas={len(self.seas)}, rivers={len(self.rivers)}")
        except Exception as ex:
            print(f"Could not load {JSON_PATH}: {ex}")

    def save(self):
        if len(self.coastline) < 3:
            messagebox.showwarning("No coastline", "Trace at least a few coastline points first.")
            return

        # Save JSON
        data = {
            'coastline': self.coastline,
            'seas':      self.seas,
            'rivers':    self.rivers,
        }
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
        with open(JSON_PATH, 'w') as f:
            json.dump(data, f)

        # Generate SVG
        self._generate_svg()

        counts = (f"Coastline: {len(self.coastline)} pts  |  "
                  f"Seas: {len(self.seas)}  |  Rivers: {len(self.rivers)}")
        messagebox.showinfo("Saved", f"Saved!\n\n{counts}\n\n→ {JSON_PATH}\n→ {SVG_OUT}")

    def _generate_svg(self):
        land_svg = ''
        for land in self.coastline:
            if len(land) > 1:
                pts = ' '.join(f'{x},{y}' for x, y in land)
                land_svg += f'  <polygon points="{pts}" fill="#d4bc96" stroke="#8b7355" stroke-width="1.5"/>\n'

        seas_svg = ''
        for sea in self.seas:
            if len(sea) > 1:
                pts = ' '.join(f'{x},{y}' for x, y in sea)
                seas_svg += f'  <polyline points="{pts}" fill="#1a3a5a" stroke="#2a5a8a" stroke-width="3" opacity="0.85"/>\n'

        rivers_svg = ''
        for river in self.rivers:
            if len(river) > 1:
                pts = ' '.join(f'{x},{y}' for x, y in river)
                rivers_svg += f'  <polyline points="{pts}" fill="none" stroke="#4a8abf" stroke-width="1.5" opacity="0.7" stroke-linecap="round" stroke-linejoin="round"/>\n'

        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOARD_W} {BOARD_H}" width="{BOARD_W}" height="{BOARD_H}">
  <!-- Ocean background -->
  <rect width="{BOARD_W}" height="{BOARD_H}" fill="#1a3a52"/>

  <!-- Land masses (one polygon per island / mainland) -->
{land_svg}
{seas_svg}{rivers_svg}</svg>'''

        os.makedirs(os.path.dirname(SVG_OUT), exist_ok=True)
        with open(SVG_OUT, 'w') as f:
            f.write(svg)
        print(f"✓ Wrote {SVG_OUT}")

    def _update_status(self):
        self.status_lbl.config(
            text=f"coast:{len(self.coastline)} pts  seas:{len(self.seas)}  rivers:{len(self.rivers)}"
        )


if __name__ == '__main__':
    # Must run from project root so relative paths work
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    os.chdir(project_root)

    root = tk.Tk()
    root.resizable(False, False)
    app = EuropeTracer(root)
    root.mainloop()
