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
        # Note: lakes_points and rivers_points are now lists of separate polylines
        # e.g., lakes_points = [[points for lake 1], [points for lake 2], ...]
        self.coastline_points = []
        self.lakes_points = []  # List of separate lakes
        self.rivers_points = []  # List of separate rivers
        self.current_stroke = []  # Points being drawn for current lake/river
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
                
                # Handle lakes - could be flat list (old) or list of lists (new)
                lakes_data = data.get('lakes', [])
                if lakes_data and isinstance(lakes_data[0], list) and isinstance(lakes_data[0][0], (list, tuple)):
                    self.lakes_points = lakes_data  # Already list of lists
                elif lakes_data:
                    self.lakes_points = []  # Empty, it was a flat list from old format
                
                # Handle rivers
                rivers_data = data.get('rivers', [])
                if rivers_data and isinstance(rivers_data[0], list) and isinstance(rivers_data[0][0], (list, tuple)):
                    self.rivers_points = rivers_data  # Already list of lists
                elif rivers_data:
                    self.rivers_points = []  # Empty
                
                print(f"✓ Loaded existing trace:")
                print(f"  - Coastline: {len(self.coastline_points)} points")
                print(f"  - Lakes: {len(self.lakes_points)} polylines")
                print(f"  - Rivers: {len(self.rivers_points)} polylines")
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
        """Start drawing a new stroke"""
        self.drawing = True
        self.current_stroke = []  # Start fresh
        x = event.x
        y = event.y
        if 0 <= x < 1024 and 0 <= y < 683:
            self.current_stroke.append((x, y))
    
    def on_mouse_drag(self, event):
        """Continue drawing current stroke"""
        if not self.drawing:
            return
        
        x = event.x
        y = event.y
        if 0 <= x < 1024 and 0 <= y < 683:
            if len(self.current_stroke) > 0:
                # Draw line from last point to current
                last_x, last_y = self.current_stroke[-1]
                color = self._get_mode_color(self.mode)
                self.draw_obj.line([(last_x, last_y), (x, y)], fill=color, width=3)
            
            self.current_stroke.append((x, y))
            self._update_canvas_image()
    
    def on_mouse_up(self, event):
        """Finish current stroke and save it"""
        if self.drawing and len(self.current_stroke) > 1:
            # Save completed stroke
            points_list = self._get_current_points()
            points_list.append(self.current_stroke[:])  # Add as separate polyline
        self.drawing = False
        self.current_stroke = []
    
    def undo(self):
        """Remove last polyline from current mode"""
        points = self._get_current_points()
        if points:
            points.pop()  # Remove last polyline
            self._redraw_all()
    
    def clear(self):
        """Clear everything"""
        if messagebox.askyesno("Clear", "Clear all drawings?"):
            self.coastline_points = []
            self.lakes_points = []
            self.rivers_points = []
            self.current_stroke = []
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
        
        # Redraw lakes (each is a separate polyline)
        color = self._get_mode_color('lakes')
        for lake in self.lakes_points:
            if len(lake) > 1:
                for i in range(len(lake) - 1):
                    x1, y1 = lake[i]
                    x2, y2 = lake[i + 1]
                    self.draw_obj.line([(x1, y1), (x2, y2)], fill=color, width=2)
        
        # Redraw rivers (each is a separate polyline)
        color = self._get_mode_color('rivers')
        for river in self.rivers_points:
            if len(river) > 1:
                for i in range(len(river) - 1):
                    x1, y1 = river[i]
                    x2, y2 = river[i + 1]
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
        
        num_lakes = len(self.lakes_points)
        num_rivers = len(self.rivers_points)
        counts = f"Coastline: {len(self.coastline_points)} | Lakes: {num_lakes} | Rivers: {num_rivers}"
        messagebox.showinfo("Saved", f"All features saved!\n\n{counts}\n\n- coastline_trace.json\n- static/images/board.svg (updated)")
    
    def _generate_svg_from_trace(self):
        """Generate SVG using all traced features"""
        if not self.coastline_points:
            return
        
        # Create polygon from coastline points
        coastline_str = ' '.join([f'{x},{y}' for x, y in self.coastline_points])
        
        # Create separate polylines for each lake
        lakes_elements = ""
        if self.lakes_points:
            lakes_elements = '  <!-- Traced lakes -->\n'
            for lake in self.lakes_points:
                if len(lake) > 1:
                    lake_str = ' '.join([f'{x},{y}' for x, y in lake])
                    lakes_elements += f'  <polyline points="{lake_str}" fill="#1a3a52" stroke="#2a5280" stroke-width="3" opacity="0.8"/>\n'
        
        # Create separate polylines for each river
        rivers_elements = ""
        if self.rivers_points:
            rivers_elements = '  <!-- Traced rivers -->\n'
            for river in self.rivers_points:
                if len(river) > 1:
                    river_str = ' '.join([f'{x},{y}' for x, y in river])
                    rivers_elements += f'  <polyline points="{river_str}" fill="none" stroke="#4a90e2" stroke-width="2" opacity="0.6" stroke-linecap="round"/>\n'
        
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
        print(f"  - Lakes: {len(self.lakes_points)} polylines")
        print(f"  - Rivers: {len(self.rivers_points)} polylines")

if __name__ == '__main__':
    root = tk.Tk()
    app = CoastlineTracer(root)
    root.mainloop()
