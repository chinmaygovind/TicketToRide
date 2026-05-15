#!/usr/bin/env python3
"""
Interactive tool to trace North American coastlines over the original board image.
Draw the coastline outline, and convert it to SVG paths.
"""

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw, ImageTk
import json
import os

class CoastlineTracer:
    def __init__(self, root):
        self.root = root
        self.root.title("Coastline Tracer - Draw over the board image")
        self.root.geometry("1280x850")
        
        # Load the original board image
        try:
            self.board_img = Image.open('static/images/board.png')
            # Scale to fit window nicely
            self.display_img = self.board_img.copy()
            self.display_img.thumbnail((1024, 683), Image.Resampling.LANCZOS)
        except FileNotFoundError:
            messagebox.showerror("Error", "Could not find board.png in static/images/")
            return
        
        # PIL canvas for drawing (initialize BEFORE updating display)
        self.draw_canvas = Image.new('RGBA', (1024, 683), (0, 0, 0, 0))
        self.draw_obj = ImageDraw.Draw(self.draw_canvas)
        
        # Canvas for drawing
        self.canvas = tk.Canvas(root, bg='black', cursor='crosshair', width=1024, height=683)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Draw the board image on canvas
        self.photo = None  # Keep reference to prevent garbage collection
        self.canvas_image = self.canvas.create_image(0, 0, anchor='nw')
        
        # Points lists for different features
        self.coastline_points = []
        self.lakes_points = []
        self.rivers_points = []
        self.mode = 'lakes'  # Start in lakes mode
        self.drawing = False
        
        # Load existing coastline if available
        self._load_existing_trace()
        
        # Now update display after loading
        self._update_canvas_image()
        
        # Redraw all loaded traces
        self._redraw_all()
        
        # Bind mouse events
        self.canvas.bind('<Button-1>', self.on_mouse_down)
        self.canvas.bind('<B1-Motion>', self.on_mouse_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_mouse_up)
        
        # Instructions and buttons
        frame = tk.Frame(root, bg='#1a1a1a')
        frame.pack(fill=tk.X, padx=10, pady=10)
        
        status_text = f"Coastline loaded: {len(self.coastline_points)} points. Now add lakes and rivers!" if self.coastline_points else "Add coastline, lakes, and rivers"
        tk.Label(frame, text=status_text, bg='#1a1a1a').pack(anchor='w')
        tk.Label(frame, text="Click and drag to trace. Switch modes with buttons. Hold to draw continuously.", 
                bg='#1a1a1a').pack(anchor='w')
        tk.Label(frame, text="Keys: Z=Undo, C=Clear, S=Save all, Q=Quit | 1=Coastline, 2=Lakes, 3=Rivers", 
                bg='#1a1a1a', font=('Arial', 9)).pack(anchor='w')
        
        # Mode selection buttons
        mode_frame = tk.Frame(frame, bg='#1a1a1a')
        mode_frame.pack(anchor='w', pady=5)
        
        self.mode_buttons = {}
        for mode_name, mode_key in [('Coastline', '1'), ('Lakes', '2'), ('Rivers', '3')]:
            btn = tk.Button(mode_frame, text=f'{mode_name} ({mode_key})', 
                           command=lambda m=mode_name.lower(): self.set_mode(m),
                           bg='#c9a877', fg='black')
            btn.pack(side=tk.LEFT, padx=5)
            self.mode_buttons[mode_name.lower()] = btn
        
        self._update_mode_buttons()
        
        self._update_mode_buttons()
        
        button_frame = tk.Frame(frame, bg='#1a1a1a')
        button_frame.pack(anchor='w', pady=5)
        
        tk.Button(button_frame, text='Undo (Z)', command=self.undo, bg='#8b7355', fg='white').pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text='Clear (C)', command=self.clear, bg='#8b7355', fg='white').pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text='Save All (S)', command=self.save_all, bg='#c9a877', fg='black').pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text='Quit (Q)', command=root.quit, bg='#8b7355', fg='white').pack(side=tk.LEFT, padx=5)
        
        # Bind keyboard
        root.bind('z', lambda e: self.undo())
        root.bind('c', lambda e: self.clear())
        root.bind('s', lambda e: self.save_all())
        root.bind('q', lambda e: root.quit())
        root.bind('1', lambda e: self.set_mode('coastline'))
        root.bind('2', lambda e: self.set_mode('lakes'))
        root.bind('3', lambda e: self.set_mode('rivers'))
    
    def _update_canvas_image(self):
        """Update canvas with current board + drawing overlay"""
        # Combine board image with drawn overlay
        combined = self.board_img.copy()
        combined.paste(self.draw_canvas, (0, 0), self.draw_canvas)
        
        # Convert to PhotoImage
        self.photo = ImageTk.PhotoImage(combined)
        self.canvas.itemconfig(self.canvas_image, image=self.photo)
    
    def _load_existing_trace(self):
        """Load existing trace data from JSON if available"""
        try:
            with open('coastline_trace.json', 'r') as f:
                data = json.load(f)
            
            # Handle both old format (list) and new format (dict)
            if isinstance(data, list):
                # Old format: just coastline points
                self.coastline_points = data
                print(f"✓ Loaded coastline: {len(self.coastline_points)} points")
            elif isinstance(data, dict):
                # New format: {coastline, lakes, rivers}
                self.coastline_points = data.get('coastline', [])
                self.lakes_points = data.get('lakes', [])
                self.rivers_points = data.get('rivers', [])
                print(f"✓ Loaded existing trace:")
                print(f"  - Coastline: {len(self.coastline_points)} points")
                print(f"  - Lakes: {len(self.lakes_points)} points")
                print(f"  - Rivers: {len(self.rivers_points)} points")
        except FileNotFoundError:
            pass  # No existing trace file
    
    def set_mode(self, mode):
        """Switch drawing mode"""
        self.mode = mode
        self._update_mode_buttons()
        self._redraw_all()
    
    def _update_mode_buttons(self):
        """Update button appearance to show active mode"""
        for mode, btn in self.mode_buttons.items():
            if mode == self.mode:
                btn.config(bg='#ffd700', fg='black')  # Gold highlight for active
            else:
                btn.config(bg='#8b7355', fg='white')
    
    def _get_current_points(self):
        """Get the point list for current mode"""
        if self.mode == 'coastline':
            return self.coastline_points
        elif self.mode == 'lakes':
            return self.lakes_points
        elif self.mode == 'rivers':
            return self.rivers_points
    
    def _get_mode_color(self, mode):
        """Get the color for a specific mode"""
        if mode == 'coastline':
            return (205, 170, 125, 200)  # Tan
        elif mode == 'lakes':
            return (50, 150, 255, 200)   # Bright blue
        elif mode == 'rivers':
            return (100, 200, 255, 180)  # Light blue
    
    def on_mouse_down(self, event):
        """Start drawing"""
        self.drawing = True
        x = event.x
        y = event.y
        if 0 <= x < 1024 and 0 <= y < 683:
            points = self._get_current_points()
            points.append((x, y))
    
    def on_mouse_drag(self, event):
        """Continue drawing line"""
        if not self.drawing:
            return
        
        x = event.x
        y = event.y
        if 0 <= x < 1024 and 0 <= y < 683:
            points = self._get_current_points()
            if len(points) > 0:
                # Draw line from last point to current
                last_x, last_y = points[-1]
                color = self._get_mode_color(self.mode)
                self.draw_obj.line([(last_x, last_y), (x, y)], fill=color, width=3)
            
            points.append((x, y))
            self._update_canvas_image()
    
    def on_mouse_up(self, event):
        """Stop drawing"""
        self.drawing = False
    
    def undo(self):
        """Remove last point from current mode"""
        points = self._get_current_points()
        if points:
            points.pop()
            self._redraw_all()
    
    def clear(self):
        """Clear everything"""
        if messagebox.askyesno("Clear", "Clear all drawings?"):
            self.coastline_points = []
            self.lakes_points = []
            self.rivers_points = []
            self.draw_canvas = Image.new('RGBA', (1024, 683), (0, 0, 0, 0))
            self.draw_obj = ImageDraw.Draw(self.draw_canvas)
            self._update_canvas_image()
    
    def _redraw_all(self):
        """Redraw all points for all modes"""
        self.draw_canvas = Image.new('RGBA', (1024, 683), (0, 0, 0, 0))
        self.draw_obj = ImageDraw.Draw(self.draw_canvas)
        
        # Redraw coastline
        if len(self.coastline_points) > 1:
            color = self._get_mode_color('coastline')
            for i in range(len(self.coastline_points) - 1):
                x1, y1 = self.coastline_points[i]
                x2, y2 = self.coastline_points[i + 1]
                self.draw_obj.line([(x1, y1), (x2, y2)], fill=color, width=3)
        
        # Redraw lakes
        if len(self.lakes_points) > 1:
            color = self._get_mode_color('lakes')
            for i in range(len(self.lakes_points) - 1):
                x1, y1 = self.lakes_points[i]
                x2, y2 = self.lakes_points[i + 1]
                self.draw_obj.line([(x1, y1), (x2, y2)], fill=color, width=2)
        
        # Redraw rivers
        if len(self.rivers_points) > 1:
            color = self._get_mode_color('rivers')
            for i in range(len(self.rivers_points) - 1):
                x1, y1 = self.rivers_points[i]
                x2, y2 = self.rivers_points[i + 1]
                self.draw_obj.line([(x1, y1), (x2, y2)], fill=color, width=1.5)
        
        self._update_canvas_image()
    
    def save_all(self):
        """Save all traced features as JSON and generate SVG"""
        if len(self.coastline_points) < 3:
            messagebox.showwarning("No coastline", "Please trace at least 3 points for a valid coastline.")
            return
        
        # Save raw points
        data = {
            'coastline': self.coastline_points,
            'lakes': self.lakes_points,
            'rivers': self.rivers_points
        }
        with open('coastline_trace.json', 'w') as f:
            json.dump(data, f)
        
        # Generate SVG with all traced features
        self._generate_svg_from_trace()
        
        counts = f"Coastline: {len(self.coastline_points)} | Lakes: {len(self.lakes_points)} | Rivers: {len(self.rivers_points)}"
        messagebox.showinfo("Saved", f"All features saved!\n\n{counts}\n\n- coastline_trace.json\n- static/images/board.svg (updated)")
    
    def _generate_svg_from_trace(self):
        """Generate SVG using all traced features"""
        if not self.coastline_points:
            return
        
        # Create polygon from coastline points
        coastline_str = ' '.join([f'{x},{y}' for x, y in self.coastline_points])
        
        # Create polylines for lakes and rivers
        lakes_elements = ""
        if len(self.lakes_points) > 1:
            lakes_str = ' '.join([f'{x},{y}' for x, y in self.lakes_points])
            lakes_elements = f'  <!-- Traced lakes -->\n  <polyline points="{lakes_str}" fill="#1a3a52" stroke="#2a5280" stroke-width="3" opacity="0.8"/>\n'
        
        rivers_elements = ""
        if len(self.rivers_points) > 1:
            rivers_str = ' '.join([f'{x},{y}' for x, y in self.rivers_points])
            rivers_elements = f'  <!-- Traced rivers -->\n  <polyline points="{rivers_str}" fill="none" stroke="#4a90e2" stroke-width="2" opacity="0.6" stroke-linecap="round"/>\n'
        
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 683" width="1024" height="683">
  <!-- Ocean background -->
  <rect width="1024" height="683" fill="#1a3a52"/>
  
  <!-- Traced coastline -->
  <polygon points="{coastline_str}" fill="#d9c4a8" stroke="#8b7355" stroke-width="2"/>
  
{lakes_elements}{rivers_elements}</svg>'''
        
        os.makedirs('static/images', exist_ok=True)
        with open('static/images/board.svg', 'w') as f:
            f.write(svg_content)
        
        print(f"✓ Generated board.svg")
        print(f"  - Coastline: {len(self.coastline_points)} points")
        print(f"  - Lakes: {len(self.lakes_points)} points")
        print(f"  - Rivers: {len(self.rivers_points)} points")

if __name__ == '__main__':
    root = tk.Tk()
    app = CoastlineTracer(root)
    root.mainloop()
