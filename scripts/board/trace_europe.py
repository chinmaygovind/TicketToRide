#!/usr/bin/env python3
"""
Interactive tool to trace European coastlines over the Europe board image.
Draw the land outline, inland seas, and rivers, then export to SVG.

Run from the project root:
    python scripts/board/trace_europe.py

Keys:
    1 = Coastline mode (land polygon)
    2 = Seas mode     (Mediterranean, Black Sea, etc.)
    3 = Rivers mode   (thin lines)
    Space       = Start/commit keyboard-draw stroke at current cursor
    Arrow keys  = Move cursor 1px (Shift = 5px, Ctrl = 20px)
                  While drawing (mouse held OR keyboard mode), extends the stroke
    Enter       = Commit current keyboard-draw stroke
    Escape      = Cancel current in-progress stroke
    Right-click = select nearest stroke (highlights red)
    Delete      = remove selected stroke
    C = Clear all (asks confirmation)
    S = Save JSON + generate SVG
    Q = Quit

Corner buttons (↖ ↗ ↙ ↘):
    Jump cursor to that corner and immediately start a keyboard-draw stroke.
    Then use arrow keys to trace along the border; press Enter to commit.
"""

import math
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw, ImageTk
import json
import os
import sys

BOARD_W, BOARD_H = 1024, 681

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


def _dist_point_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / (dx*dx + dy*dy)))
    return math.hypot(px - (ax + t*dx), py - (ay + t*dy))

def _min_dist_to_stroke(px, py, stroke):
    if len(stroke) < 2:
        return float('inf')
    return min(
        _dist_point_to_segment(px, py, *stroke[i], *stroke[i+1])
        for i in range(len(stroke) - 1)
    )


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
        if self.board_img.size != (BOARD_W, BOARD_H):
            self.board_img = self.board_img.resize((BOARD_W, BOARD_H), Image.Resampling.LANCZOS)

        self.overlay = Image.new('RGBA', (BOARD_W, BOARD_H), (0, 0, 0, 0))
        self.draw_obj = ImageDraw.Draw(self.overlay)

        self.coastline = []
        self.seas = []
        self.rivers = []
        self.current_stroke = []
        self.mode = 'coastline'
        self.drawing = False       # True while mouse button is held
        self.kb_drawing = False    # True while in keyboard-draw mode
        self.selected = None       # (mode_name, index) of right-click selected stroke

        # Virtual cursor position (updated by mouse and arrow keys)
        self.cursor_x = 0
        self.cursor_y = 0

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

        # Cursor marker: a small crosshair drawn as canvas lines
        r = 6
        self.cursor_h = self.canvas.create_line(0, 0, 0, 0, fill='red', width=1, tags='cursor')
        self.cursor_v = self.canvas.create_line(0, 0, 0, 0, fill='red', width=1, tags='cursor')
        self.cursor_ring = self.canvas.create_oval(0, 0, 0, 0, outline='red', width=1, tags='cursor')
        self._update_cursor_display()

        self.canvas.bind('<Button-1>',        self._on_down)
        self.canvas.bind('<B1-Motion>',       self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_up)
        self.canvas.bind('<Button-3>',        self._on_right_click)
        self.canvas.bind('<Motion>',          self._on_mouse_move)

        # ── Controls ─────────────────────────────────────────────────────────
        ctrl = tk.Frame(root, bg='#1a1410')
        ctrl.pack(fill=tk.X, padx=6, pady=4)

        self.mode_btns = {}
        for label, mkey in [
            ('1 Coastline', 'coastline'),
            ('2 Seas',      'seas'),
            ('3 Rivers',    'rivers'),
        ]:
            b = tk.Button(ctrl, text=label, font=('Courier New', 9),
                          command=lambda m=mkey: self.set_mode(m),
                          bg='#2a2218', fg='#c8a84b', relief='flat',
                          padx=8, pady=4, bd=0)
            b.pack(side=tk.LEFT, padx=3)
            self.mode_btns[mkey] = b

        self.del_btn = tk.Button(ctrl, text='Del Selected', font=('Courier New', 9),
                                 command=self._delete_selected,
                                 bg='#2a2218', fg='#ef4444', relief='flat',
                                 padx=8, pady=4, bd=0, state=tk.DISABLED)
        self.del_btn.pack(side=tk.LEFT, padx=3)

        for label, cmd in [
            ('C Clear', self.clear),
            ('S Save',  self.save),
            ('Q Quit',  root.quit),
        ]:
            tk.Button(ctrl, text=label, font=('Courier New', 9), command=cmd,
                      bg='#2a2218', fg='#e0d8c8', relief='flat',
                      padx=8, pady=4, bd=0).pack(side=tk.LEFT, padx=3)

        # ── Corner jump buttons ───────────────────────────────────────────────
        corner_frame = tk.Frame(ctrl, bg='#1a1410')
        corner_frame.pack(side=tk.RIGHT, padx=8)

        tk.Label(corner_frame, text='Jump to corner:', bg='#1a1410', fg='#6a5a40',
                 font=('Courier New', 8)).pack(side=tk.LEFT, padx=(0, 4))

        for label, cx, cy in [
            ('↖', 0,          0),
            ('↗', BOARD_W-1,  0),
            ('↙', 0,          BOARD_H-1),
            ('↘', BOARD_W-1,  BOARD_H-1),
        ]:
            tk.Button(corner_frame, text=label, font=('Courier New', 11),
                      command=lambda x=cx, y=cy: self._jump_to_corner(x, y),
                      bg='#2a2218', fg='#c8a84b', relief='flat',
                      padx=6, pady=2, bd=0).pack(side=tk.LEFT, padx=2)

        hints = tk.Label(root,
            text='Arrows = move cursor 1px (Shift=5, Ctrl=20)  |  Space = start/commit kb stroke  |  Enter = commit  |  Esc = cancel  |  Corner buttons = jump + start stroke',
            bg='#1a1410', fg='#4a4038', font=('Courier New', 8))
        hints.pack(pady=2)

        # ── Key bindings ──────────────────────────────────────────────────────
        root.bind('1', lambda e: self.set_mode('coastline'))
        root.bind('2', lambda e: self.set_mode('seas'))
        root.bind('3', lambda e: self.set_mode('rivers'))
        root.bind('<Delete>',  lambda e: self._delete_selected())
        root.bind('c',         lambda e: self.clear())
        root.bind('s',         lambda e: self.save())
        root.bind('q',         lambda e: root.quit())
        root.bind('<space>',   lambda e: self._kb_toggle())
        root.bind('<Return>',  lambda e: self._kb_commit())
        root.bind('<Escape>',  lambda e: self._kb_cancel())
        root.bind('<Left>',    self._on_arrow)
        root.bind('<Right>',   self._on_arrow)
        root.bind('<Up>',      self._on_arrow)
        root.bind('<Down>',    self._on_arrow)

        self._update_mode_btns()
        self._update_status()

    # ── Cursor display ────────────────────────────────────────────────────────

    def _update_cursor_display(self):
        if not hasattr(self, 'cursor_h'):
            return
        x, y = self.cursor_x, self.cursor_y
        r = 6
        self.canvas.coords(self.cursor_h, x - r - 3, y, x + r + 3, y)
        self.canvas.coords(self.cursor_v, x, y - r - 3, x, y + r + 3)
        self.canvas.coords(self.cursor_ring, x - r, y - r, x + r, y + r)
        col = '#ff4444' if (self.drawing or self.kb_drawing) else '#ff8888'
        self.canvas.itemconfig(self.cursor_h,    fill=col)
        self.canvas.itemconfig(self.cursor_v,    fill=col)
        self.canvas.itemconfig(self.cursor_ring, outline=col)
        # Raise cursor above everything
        self.canvas.tag_raise('cursor')

    # ── Mouse events ─────────────────────────────────────────────────────────

    def _on_mouse_move(self, e):
        if not self.drawing:
            self.cursor_x = max(0, min(e.x, BOARD_W - 1))
            self.cursor_y = max(0, min(e.y, BOARD_H - 1))
            self._update_cursor_display()
            self._update_status()

    def _on_down(self, e):
        # Commit any open kb stroke before starting a mouse stroke
        if self.kb_drawing:
            self._kb_commit()
        self.drawing = True
        self.selected = None
        self.del_btn.config(state=tk.DISABLED)
        self.current_stroke = []
        self.cursor_x = max(0, min(e.x, BOARD_W - 1))
        self.cursor_y = max(0, min(e.y, BOARD_H - 1))
        self._add_point(self.cursor_x, self.cursor_y)
        self._update_cursor_display()

    def _on_drag(self, e):
        if not self.drawing:
            return
        x = max(0, min(e.x, BOARD_W - 1))
        y = max(0, min(e.y, BOARD_H - 1))
        self.cursor_x = x
        self.cursor_y = y
        if self.current_stroke:
            lx, ly = self.current_stroke[-1]
            if lx != x or ly != y:
                color = self._mode_color(self.mode)
                w = 2 if self.mode == 'rivers' else 3
                self.draw_obj.line([(lx, ly), (x, y)], fill=color, width=w)
        self.current_stroke.append((x, y))
        self._flush_canvas()
        self._update_cursor_display()
        self._update_status()

    def _on_up(self, e):
        if self.drawing and len(self.current_stroke) > 1:
            stroke = self.current_stroke[:]
            if self.mode == 'coastline':
                self.coastline.append(stroke)
            elif self.mode == 'seas':
                self.seas.append(stroke)
            elif self.mode == 'rivers':
                self.rivers.append(stroke)
        self.drawing = False
        self.current_stroke = []
        self._update_cursor_display()
        self._update_status()

    def _add_point(self, x, y):
        if 0 <= x < BOARD_W and 0 <= y < BOARD_H:
            self.current_stroke.append((x, y))

    # ── Arrow key movement ────────────────────────────────────────────────────

    def _on_arrow(self, e):
        # Determine step size: Ctrl=20, Shift=5, default=1
        state = e.state
        if state & 0x4:   # Ctrl
            step = 20
        elif state & 0x1: # Shift
            step = 5
        else:
            step = 1

        dx, dy = 0, 0
        if e.keysym == 'Left':  dx = -step
        elif e.keysym == 'Right': dx =  step
        elif e.keysym == 'Up':   dy = -step
        elif e.keysym == 'Down': dy =  step

        new_x = max(0, min(self.cursor_x + dx, BOARD_W - 1))
        new_y = max(0, min(self.cursor_y + dy, BOARD_H - 1))

        if self.drawing or self.kb_drawing:
            # Extend the current stroke to the new position
            if self.current_stroke:
                lx, ly = self.current_stroke[-1]
                if lx != new_x or ly != new_y:
                    color = self._mode_color(self.mode)
                    w = 2 if self.mode == 'rivers' else 3
                    self.draw_obj.line([(lx, ly), (new_x, new_y)], fill=color, width=w)
            else:
                self._add_point(new_x, new_y)
            self.current_stroke.append((new_x, new_y))
            self._flush_canvas()

        self.cursor_x = new_x
        self.cursor_y = new_y
        self._update_cursor_display()
        self._update_status()

    # ── Keyboard draw mode ────────────────────────────────────────────────────

    def _kb_toggle(self):
        """Space: start a kb stroke at cursor, or commit if one is in progress."""
        if self.kb_drawing:
            self._kb_commit()
        else:
            self._start_kb_stroke(self.cursor_x, self.cursor_y)

    def _start_kb_stroke(self, x, y):
        self.kb_drawing = True
        self.current_stroke = [(x, y)]
        self._update_cursor_display()
        self._update_status(f'KB-DRAW at ({x},{y}) — arrows to draw, Enter to commit, Esc to cancel')

    def _kb_commit(self):
        if self.kb_drawing and len(self.current_stroke) > 1:
            stroke = self.current_stroke[:]
            if self.mode == 'coastline':
                self.coastline.append(stroke)
            elif self.mode == 'seas':
                self.seas.append(stroke)
            elif self.mode == 'rivers':
                self.rivers.append(stroke)
        self.kb_drawing = False
        self.current_stroke = []
        self._update_cursor_display()
        self._update_status()

    def _kb_cancel(self):
        if self.drawing:
            self.drawing = False
        self.kb_drawing = False
        self.current_stroke = []
        self._redraw_all()
        self._update_cursor_display()
        self._update_status()

    # ── Corner jump ───────────────────────────────────────────────────────────

    def _jump_to_corner(self, x, y):
        """Jump cursor to a corner and start a keyboard-draw stroke from there."""
        # Commit any existing stroke first
        if self.kb_drawing:
            self._kb_commit()
        elif self.drawing:
            self._on_up(None)
        self.cursor_x = x
        self.cursor_y = y
        self._start_kb_stroke(x, y)
        self._update_cursor_display()

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_right_click(self, e):
        px, py = e.x, e.y
        best_mode, best_idx, best_dist = None, None, float('inf')

        for mode_name, strokes in [('coastline', self.coastline),
                                    ('seas',      self.seas),
                                    ('rivers',    self.rivers)]:
            for i, stroke in enumerate(strokes):
                d = _min_dist_to_stroke(px, py, stroke)
                if d < best_dist:
                    best_dist, best_mode, best_idx = d, mode_name, i

        if best_mode is not None and best_dist < 20:
            self.selected = (best_mode, best_idx)
            self.del_btn.config(state=tk.NORMAL)
            self._update_status(f"Selected: {best_mode} #{best_idx + 1}  —  Delete to remove")
        else:
            self.selected = None
            self.del_btn.config(state=tk.DISABLED)
            self._update_status()
        self._redraw_all()

    def _delete_selected(self):
        if not self.selected:
            return
        mode_name, idx = self.selected
        strokes = {'coastline': self.coastline, 'seas': self.seas, 'rivers': self.rivers}[mode_name]
        strokes.pop(idx)
        self.selected = None
        self.del_btn.config(state=tk.DISABLED)
        self._redraw_all()
        self._update_status()

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

        SEL_COLOR = (255, 60, 60, 255)

        for mode_name, strokes, w in [
            ('coastline', self.coastline, 3),
            ('seas',      self.seas,      3),
            ('rivers',    self.rivers,    2),
        ]:
            c = self._mode_color(mode_name)
            for i, stroke in enumerate(strokes):
                color = SEL_COLOR if self.selected == (mode_name, i) else c
                width = w + 2 if self.selected == (mode_name, i) else w
                if len(stroke) > 1:
                    for j in range(len(stroke) - 1):
                        self.draw_obj.line([stroke[j], stroke[j+1]], fill=color, width=width)

        # Draw in-progress kb stroke
        if self.kb_drawing and len(self.current_stroke) > 1:
            c = self._mode_color(self.mode)
            w = 2 if self.mode == 'rivers' else 3
            for j in range(len(self.current_stroke) - 1):
                self.draw_obj.line([self.current_stroke[j], self.current_stroke[j+1]], fill=c, width=w)

        self._flush_canvas()
        self._update_cursor_display()

    def _flush_canvas(self):
        combined = self.board_img.copy()
        combined.paste(self.overlay, (0, 0), self.overlay)
        self.photo = ImageTk.PhotoImage(combined)
        self.canvas.itemconfig(self.canvas_img_id, image=self.photo)

    # ── Edit ─────────────────────────────────────────────────────────────────

    def clear(self):
        if messagebox.askyesno("Clear", "Clear all drawings?"):
            self.coastline = []
            self.seas = []
            self.rivers = []
            self.current_stroke = []
            self.kb_drawing = False
            self.drawing = False
            self.selected = None
            self.del_btn.config(state=tk.DISABLED)
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
            self.seas      = [[tuple(p) for p in s]    for s    in data.get('seas',      [])]
            self.rivers    = [[tuple(p) for p in r]    for r    in data.get('rivers',    [])]
            print(f"Loaded: coastline={len(self.coastline)}, seas={len(self.seas)}, rivers={len(self.rivers)}")
        except Exception as ex:
            print(f"Could not load {JSON_PATH}: {ex}")

    def save(self):
        data = {'coastline': self.coastline, 'seas': self.seas, 'rivers': self.rivers}
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
        with open(JSON_PATH, 'w') as f:
            json.dump(data, f)
        self._generate_svg()
        counts = f"Coastline: {len(self.coastline)}  Seas: {len(self.seas)}  Rivers: {len(self.rivers)}"
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

  <!-- Land masses -->
{land_svg}
{seas_svg}{rivers_svg}</svg>'''

        os.makedirs(os.path.dirname(SVG_OUT), exist_ok=True)
        with open(SVG_OUT, 'w') as f:
            f.write(svg)
        print(f"✓ Wrote {SVG_OUT}")

    def _update_status(self, msg=None):
        if msg:
            self.status_lbl.config(text=msg, fg='#ef4444')
        else:
            mode_str = 'KB-DRAW' if self.kb_drawing else ('DRAWING' if self.drawing else 'ready')
            pos_str  = f'({self.cursor_x},{self.cursor_y})'
            counts   = f"coast:{len(self.coastline)}  seas:{len(self.seas)}  rivers:{len(self.rivers)}"
            self.status_lbl.config(
                fg='#f59e0b' if (self.kb_drawing or self.drawing) else '#a09070',
                text=f"{mode_str} {pos_str}  |  {counts}"
            )


if __name__ == '__main__':
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    os.chdir(project_root)

    root = tk.Tk()
    root.resizable(False, False)
    app = EuropeTracer(root)
    root.mainloop()
