#!/usr/bin/env python3
"""Image Measure: measure lengths, radii, angles and areas on an image.

Open an image and draw one or more reference lines over features of known
size, typing the real length of each. The references set the scale in units
per pixel. The measuring tools (line, circles, angle, rectangle, polygon)
then report their results in those units. Without a reference, results are
in pixels.

Usage: python3 image_measure.py [image]
"""

import copy
import json
import math
import os
import sys
import tkinter as tk
from dataclasses import asdict, dataclass
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

import geometry as geo


@dataclass
class Tool:
    key: str
    label: str
    shortcut: str
    # Number of clicks that complete the shape; 0 means "until the user closes it".
    points: int
    hint: str


TOOLS = [
    Tool("select", "Select", "v", 0,
         "Click a shape to select it. Drag a handle or the shape to move it. "
         "Drag empty space to pan. Del deletes. Double-click a reference to edit its length."),
    Tool("ref", "Reference", "r", 2,
         "Click (or drag) the two ends of a feature of known length, then type the length."),
    Tool("line", "Line", "l", 2, "Click (or drag) start and end. Hold Shift to snap to 45°."),
    Tool("circle", "Circle (center)", "c", 2, "Click the center, then a point on the edge."),
    Tool("circle3", "Circle (3 pts)", "3", 3, "Click three points on the edge of the circle."),
    Tool("angle", "Angle", "a", 3, "Click the end of the first arm, the vertex, then the end of the second arm."),
    Tool("rect", "Rectangle", "b", 2, "Click (or drag) two opposite corners."),
    Tool("polygon", "Polygon", "p", 0,
         "Click the corners. Enter, double-click or right-click closes the polygon."),
]
TOOLS_BY_KEY = {t.key: t for t in TOOLS}

KIND_NAMES = {t.key: t.label for t in TOOLS}

COLORS = {
    "ref": "#ff453a",
    "line": "#32d74b",
    "circle": "#0a84ff",
    "circle3": "#0a84ff",
    "angle": "#ff9f0a",
    "rect": "#bf5af2",
    "polygon": "#64d2ff",
    "path": "#ffffff",
}
SELECTED_COLOR = "#ffd60a"

# Distance in canvas pixels within which a click grabs a shape or a handle.
HIT_TOLERANCE = 8

MIN_ZOOM, MAX_ZOOM = 0.02, 64.0


@dataclass
class Shape:
    """A drawn shape. Points are [x, y] in image pixel coordinates."""

    kind: str
    pts: list
    # Real length typed by the user. Only "ref" shapes use it.
    value: float | None = None


def fmt(v):
    """Format v with about 4 significant digits and without an exponent."""
    if v == 0 or not math.isfinite(v):
        return f"{v:g}"
    digits = max(0, min(6, 3 - math.floor(math.log10(abs(v)))))
    return f"{v:.{digits}f}"


# ---------------------------------------------------------------- painters
#
# A painter draws primitives in output pixels. CanvasPainter draws on the Tk
# canvas, PILPainter draws on a full-resolution image for export. render_shape
# uses either one, so the screen and the exported file look the same.


class CanvasPainter:
    """Draws primitives on a Tk canvas, all tagged with one tag."""

    def __init__(self, canvas, tag):
        self.c = canvas
        self.tag = tag
        # Size factor for fixed-size decorations such as arcs and label offsets.
        self.ui = 1.0

    def line(self, pts, color, width, closed=False, dash=None):
        if closed:
            pts = list(pts) + [pts[0]]
        if len(pts) < 2:
            return
        flat = [v for p in pts for v in p]
        extra = {"dash": dash} if dash else {}
        # A black stroke under the colored one keeps lines visible on any background.
        self.c.create_line(*flat, fill="black", width=width + 2, tags=self.tag,
                           capstyle="round", joinstyle="round", **extra)
        self.c.create_line(*flat, fill=color, width=width, tags=self.tag,
                           capstyle="round", joinstyle="round", **extra)

    def circle(self, c, r, color, width):
        box = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        self.c.create_oval(*box, outline="black", width=width + 2, tags=self.tag)
        self.c.create_oval(*box, outline=color, width=width, tags=self.tag)

    def arc(self, c, r, start, sweep, color, width):
        """Draw an arc. Angles are degrees, clockwise from +x, as in y-down image coordinates."""
        box = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        # Tk measures angles counterclockwise, so both angles flip sign.
        self.c.create_arc(*box, start=-start, extent=-sweep, style="arc",
                          outline=color, width=width, tags=self.tag)

    def dot(self, p, color, r=3):
        self.c.create_oval(p[0] - r, p[1] - r, p[0] + r, p[1] + r,
                           fill=color, outline="black", tags=self.tag)

    def text(self, p, s, color):
        t = self.c.create_text(p[0], p[1], text=s, fill="white",
                               font=("TkDefaultFont", 10, "bold"), tags=self.tag)
        x0, y0, x1, y1 = self.c.bbox(t)
        bg = self.c.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill="#1c1c1e",
                                     outline=color, tags=self.tag)
        self.c.tag_raise(t, bg)


class PILPainter:
    """Draws primitives on a PIL image. Widths and sizes are multiplied by ui."""

    def __init__(self, image, ui):
        self.d = ImageDraw.Draw(image)
        self.ui = ui
        self.font = self._load_font(max(10, round(13 * ui)))

    @staticmethod
    def _load_font(size):
        """Return a TrueType font with the ² and × glyphs, or Pillow's built-in font."""
        for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            # Pillow older than 10.1 has only a fixed-size default font.
            return ImageFont.load_default()

    def _w(self, width):
        return max(1, round(width * self.ui))

    def line(self, pts, color, width, closed=False, dash=None):
        pts = [tuple(p) for p in pts]
        if closed:
            pts.append(pts[0])
        if len(pts) < 2:
            return
        w = self._w(width)
        self.d.line(pts, fill="black", width=w + self._w(2), joint="curve")
        self.d.line(pts, fill=color, width=w, joint="curve")

    def circle(self, c, r, color, width):
        box = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        w = self._w(width)
        self.d.ellipse(box, outline="black", width=w + self._w(2))
        self.d.ellipse(box, outline=color, width=w)

    def arc(self, c, r, start, sweep, color, width):
        box = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        lo, hi = sorted((start, start + sweep))
        self.d.arc(box, lo, hi, fill=color, width=self._w(width))

    def dot(self, p, color, r=3):
        r = r * self.ui
        self.d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=color, outline="black")

    def text(self, p, s, color):
        x0, y0, x1, y1 = self.d.textbbox(p, s, font=self.font, anchor="mm")
        pad = 3 * self.ui
        self.d.rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), fill="#1c1c1e",
                         outline=color, width=self._w(1))
        self.d.text(p, s, fill="white", font=self.font, anchor="mm")


def render_shape(painter, shape, to_out, color, label, width=2):
    """Draw shape with painter. to_out maps an image point to an output point."""
    pts = [to_out(p) for p in shape.pts]
    kind = shape.kind
    ui = painter.ui
    anchor = None

    if kind in ("ref", "line", "path"):
        painter.line(pts, color, width)
        for p in pts:
            painter.dot(p, color)
        if kind != "path" and len(pts) == 2:
            (x0, y0), (x1, y1) = pts
            length = math.hypot(x1 - x0, y1 - y0) or 1.0
            # Place the label beside the midpoint, offset along the line normal.
            nx, ny = -(y1 - y0) / length, (x1 - x0) / length
            anchor = ((x0 + x1) / 2 + nx * 14 * ui, (y0 + y1) / 2 + ny * 14 * ui)

    elif kind == "circle":
        c, e = pts
        painter.circle(c, geo.dist(c, e), color, width)
        painter.line([c, e], color, 1, dash=(4, 3))
        painter.dot(c, color)
        painter.dot(e, color)
        anchor = c

    elif kind == "circle3":
        fit = geo.circle_from_3_points(*pts)
        if fit is None:
            painter.line(pts, color, width)
            anchor = pts[1]
        else:
            center, r = fit
            painter.circle(center, r, color, width)
            painter.dot(center, color, 2)
            anchor = center
        for p in pts:
            painter.dot(p, color)

    elif kind == "angle":
        a, v, b = pts
        painter.line([a, v, b], color, width)
        for p in pts:
            painter.dot(p, color)
        a1 = math.degrees(math.atan2(a[1] - v[1], a[0] - v[0]))
        a2 = math.degrees(math.atan2(b[1] - v[1], b[0] - v[0]))
        # Signed sweep from arm a to arm b along the shorter way, in (-180, 180].
        sweep = (a2 - a1 + 180) % 360 - 180
        r = min(30 * ui, 0.5 * min(geo.dist(v, a), geo.dist(v, b)))
        if r > 2:
            painter.arc(v, r, a1, sweep, color, max(1, width - 1))
        mid = math.radians(a1 + sweep / 2)
        off = max(r, 10 * ui) + 22 * ui
        anchor = (v[0] + off * math.cos(mid), v[1] + off * math.sin(mid))

    elif kind == "rect":
        (x0, y0), (x1, y1) = pts
        painter.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], color, width, closed=True)
        painter.dot((x0, y0), color)
        painter.dot((x1, y1), color)
        anchor = ((x0 + x1) / 2, (y0 + y1) / 2)

    elif kind == "polygon":
        painter.line(pts, color, width, closed=len(pts) > 2)
        for p in pts:
            painter.dot(p, color)
        anchor = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    if label and anchor:
        painter.text(anchor, label, color)


# ---------------------------------------------------------------- app


class App:
    def __init__(self, root, image_path=None):
        self.root = root
        self.image = None
        self.image_path = None
        self.shapes = []
        self.undo_stack = []
        # Points already placed for the shape being drawn, in image coordinates.
        self.pending = []
        # Last mouse position in image coordinates, used for the live preview.
        self.mouse = None
        # Index into self.shapes of the selected shape, or None.
        self.selected = None
        # View transform: canvas = image * zoom + offset.
        self.zoom = 1.0
        self.ox = 0.0
        self.oy = 0.0
        # State of the current mouse drag (pan, point move or shape move), or None.
        self.drag = None
        # Canvas position of the last left-button press, to tell clicks from drags.
        self.press_at = None
        self._photo = None
        # True while refresh() rebuilds the shape list, so selection events from it are ignored.
        self._syncing_tree = False

        self.tool = tk.StringVar(value="ref")
        self.unit = tk.StringVar(value="mm")
        self.status = tk.StringVar()

        self._build_ui()
        self._bind()
        self.set_tool("ref")
        self.refresh()
        if image_path:
            self.root.after(50, lambda: self.load_image(image_path))

    # ------------------------------------------------------------ UI setup

    def _build_ui(self):
        self.root.title("Image Measure")
        self.root.geometry("1280x800")

        bar = ttk.Frame(self.root, padding=4)
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Open image…", command=self.open_image).pack(side="left")
        ttk.Button(bar, text="Save…", command=self.save_json).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Load…", command=self.load_json).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Export PNG…", command=self.export_png).pack(side="left", padx=(4, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, text="Unit:").pack(side="left")
        ttk.Entry(bar, textvariable=self.unit, width=6).pack(side="left", padx=(2, 0))
        self.unit.trace_add("write", lambda *_: self.refresh())
        ttk.Button(bar, text="Fit (F)", command=self.fit_view).pack(side="left", padx=(8, 0))

        tools = ttk.Frame(self.root, padding=(4, 0, 4, 4))
        tools.pack(side="top", fill="x")
        for t in TOOLS:
            ttk.Radiobutton(tools, text=f"{t.label} ({t.shortcut.upper()})", value=t.key,
                            variable=self.tool, style="Toolbutton",
                            command=lambda k=t.key: self.set_tool(k)).pack(side="left", padx=1)

        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(side="top", fill="both", expand=True)

        self.canvas = tk.Canvas(body, background="#2c2c2e", highlightthickness=0, cursor="crosshair")
        body.add(self.canvas, weight=1)

        side = ttk.Frame(body, padding=4)
        body.add(side, weight=0)
        self.scale_label = ttk.Label(side, wraplength=330, justify="left")
        self.scale_label.pack(side="top", fill="x", pady=(0, 4))
        self.tree = ttk.Treeview(side, columns=("kind", "value"), show="headings",
                                 selectmode="browse", height=20)
        self.tree.heading("kind", text="Shape")
        self.tree.heading("value", text="Measurement")
        self.tree.column("kind", width=110, stretch=False)
        self.tree.column("value", width=230)
        self.tree.pack(side="top", fill="both", expand=True)
        btns = ttk.Frame(side)
        btns.pack(side="top", fill="x", pady=(4, 0))
        ttk.Button(btns, text="Delete", command=self.delete_selected).pack(side="left")
        ttk.Button(btns, text="Edit length", command=self.edit_reference).pack(side="left", padx=4)
        ttk.Button(btns, text="Undo", command=self.undo).pack(side="left")
        ttk.Button(btns, text="Clear all", command=self.clear_all).pack(side="right")

        ttk.Label(self.root, textvariable=self.status, anchor="w", padding=(6, 2),
                  relief="sunken").pack(side="bottom", fill="x")

    def _bind(self):
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Motion>", self.on_move)
        c.bind("<ButtonPress-3>", self.on_right)
        c.bind("<ButtonPress-2>", self.start_pan)
        c.bind("<B2-Motion>", self.do_pan)
        c.bind("<ButtonRelease-2>", lambda e: setattr(self, "drag", None))
        c.bind("<MouseWheel>", lambda e: self.zoom_at(e.x, e.y, 1.2 if e.delta > 0 else 1 / 1.2))
        c.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.2))
        c.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 1 / 1.2))
        c.bind("<Leave>", lambda e: self.clear_mouse())

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-Button-1>", lambda e: self.edit_reference())

        r = self.root
        r.bind("<Key>", self.on_key)
        r.bind("<Control-o>", lambda e: self.open_image())
        r.bind("<Control-s>", lambda e: self.save_json())
        r.bind("<Control-l>", lambda e: self.load_json())
        r.bind("<Control-e>", lambda e: self.export_png())
        r.bind("<Control-z>", lambda e: self.undo())

    # ------------------------------------------------------------ files

    def open_image(self):
        path = filedialog.askopenfilename(
            title="Open image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp"),
                       ("All files", "*")])
        if path:
            self.load_image(path)

    def load_image(self, path, keep_shapes=False):
        try:
            img = Image.open(path)
            # Phone photos store their orientation in EXIF; apply it so the image is upright.
            img = ImageOps.exif_transpose(img)
            img.load()
        except Exception as exc:
            messagebox.showerror("Open image", f"Cannot open {path}:\n{exc}")
            return False
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        self.image = img
        self.image_path = os.path.abspath(path)
        if not keep_shapes:
            self.shapes = []
            self.undo_stack = []
            self.selected = None
        self.pending = []
        self.root.title(f"Image Measure: {os.path.basename(path)}  ({img.width}×{img.height} px)")
        self.root.update_idletasks()
        self.fit_view()
        self.refresh()
        return True

    def save_json(self):
        if not self.image_path:
            messagebox.showinfo("Save", "Open an image first.")
            return
        base = os.path.splitext(self.image_path)[0]
        path = filedialog.asksaveasfilename(
            title="Save measurements", defaultextension=".json",
            initialfile=os.path.basename(base) + ".measure.json",
            initialdir=os.path.dirname(self.image_path),
            filetypes=[("Measurements", "*.json")])
        if not path:
            return
        data = {
            "image": self.image_path,
            "unit": self.unit.get(),
            "units_per_px": self.units_per_px(),
            "shapes": [asdict(s) | {"measurement": self.measure(s)[1]} for s in self.shapes],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.status.set(f"Saved {path}")

    def load_json(self):
        path = filedialog.askopenfilename(title="Load measurements",
                                          filetypes=[("Measurements", "*.json"), ("All files", "*")])
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
            shapes = [Shape(s["kind"], [list(p) for p in s["pts"]], s.get("value"))
                      for s in data["shapes"]]
        except Exception as exc:
            messagebox.showerror("Load", f"Cannot read {path}:\n{exc}")
            return
        img_path = data.get("image")
        if img_path and img_path != self.image_path:
            if not os.path.exists(img_path) or not self.load_image(img_path):
                messagebox.showwarning(
                    "Load", f"Image {img_path} not found. The shapes are placed on the current image.")
        self.push_undo()
        self.shapes = shapes
        self.selected = None
        self.unit.set(data.get("unit", self.unit.get()))
        self.refresh()

    def export_png(self):
        if self.image is None:
            messagebox.showinfo("Export", "Open an image first.")
            return
        base = os.path.splitext(self.image_path)[0]
        path = filedialog.asksaveasfilename(
            title="Export annotated image", defaultextension=".png",
            initialfile=os.path.basename(base) + "_measured.png",
            initialdir=os.path.dirname(self.image_path),
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if path:
            self.render_annotated().save(path)
            self.status.set(f"Exported {path}")

    def render_annotated(self):
        """Return a full-resolution RGB copy of the image with all shapes drawn on it."""
        out = self.image.convert("RGB")
        # Scale strokes and text with the image so they stay readable on large photos.
        ui = max(1.0, max(out.size) / 1000)
        painter = PILPainter(out, ui)
        for s in self.shapes:
            render_shape(painter, s, tuple, COLORS[s.kind], self.measure(s)[0])
        return out

    # ------------------------------------------------------------ scale and measurements

    def unit_name(self):
        return self.unit.get().strip() or "units"

    def references(self):
        return [s for s in self.shapes if s.kind == "ref" and s.value]

    def units_per_px(self):
        return geo.scale_from_references([(geo.dist(*s.pts), s.value) for s in self.references()])

    def measure(self, s):
        """Return (short canvas label, longer list text) for shape s in the current units."""
        upp = self.units_per_px()
        u = self.unit_name() if upp else "px"
        k = upp or 1.0
        pts = s.pts

        if s.kind == "ref":
            px = geo.dist(*pts)
            if not s.value:
                return f"{fmt(px)} px", f"{fmt(px)} px (no length set)"
            text = f"{fmt(s.value)} {self.unit_name()} = {fmt(px)} px"
            if upp and len(self.references()) > 1:
                # How far this reference's own scale is from the combined scale.
                dev = (s.value / px / upp - 1) * 100 if px else 0.0
                text += f"  ({dev:+.1f}%)"
            return f"{fmt(s.value)} {self.unit_name()}", text

        if s.kind == "line":
            length = geo.dist(*pts) * k
            return f"{fmt(length)} {u}", f"L {fmt(length)} {u}"

        if s.kind in ("circle", "circle3"):
            if s.kind == "circle":
                r = geo.dist(*pts)
            else:
                fit = geo.circle_from_3_points(*pts)
                if fit is None:
                    return "collinear", "points are collinear"
                r = fit[1]
            r *= k
            return (f"R {fmt(r)} {u}",
                    f"R {fmt(r)}  Ø {fmt(2 * r)}  A {fmt(math.pi * r * r)} {u}²")

        if s.kind == "angle":
            deg = geo.angle_deg(*pts)
            return f"{deg:.1f}°", f"{deg:.2f}°  (180° − θ = {180 - deg:.2f}°)"

        if s.kind == "rect":
            (x0, y0), (x1, y1) = pts
            w, h = abs(x1 - x0) * k, abs(y1 - y0) * k
            return (f"{fmt(w)} × {fmt(h)} {u}",
                    f"W {fmt(w)}  H {fmt(h)}  diag {fmt(math.hypot(w, h))}  A {fmt(w * h)} {u}²")

        if s.kind == "polygon":
            area = geo.polygon_area(pts) * k * k
            per = geo.polyline_length(pts, closed=True) * k
            return f"A {fmt(area)} {u}²", f"A {fmt(area)} {u}²  perimeter {fmt(per)} {u}"

        return "", ""

    # ------------------------------------------------------------ view

    def to_canvas(self, p):
        return (p[0] * self.zoom + self.ox, p[1] * self.zoom + self.oy)

    def to_image(self, x, y):
        return [(x - self.ox) / self.zoom, (y - self.oy) / self.zoom]

    def fit_view(self):
        if self.image is None:
            return
        w, h = max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)
        iw, ih = self.image.size
        self.zoom = min(w / iw, h / ih) * 0.95
        self.ox = (w - iw * self.zoom) / 2
        self.oy = (h - ih * self.zoom) / 2
        self.redraw()

    def zoom_at(self, x, y, factor):
        if self.image is None:
            return
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        # Keep the image point under the cursor fixed while zooming.
        ix, iy = self.to_image(x, y)
        self.zoom = new_zoom
        self.ox = x - ix * new_zoom
        self.oy = y - iy * new_zoom
        self.redraw()

    def start_pan(self, event):
        self.drag = {"type": "pan", "x": event.x, "y": event.y, "ox": self.ox, "oy": self.oy}

    def do_pan(self, event):
        if self.drag and self.drag["type"] == "pan":
            self.ox = self.drag["ox"] + event.x - self.drag["x"]
            self.oy = self.drag["oy"] + event.y - self.drag["y"]
            self.redraw()

    # ------------------------------------------------------------ drawing

    def redraw(self):
        self.redraw_image()
        self.redraw_overlay()

    def redraw_image(self):
        self.canvas.delete("image")
        if self.image is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        iw, ih = self.image.size
        # Only the visible part of the image is cropped and resized, so deep zoom stays fast.
        x0 = max(0, math.floor(-self.ox / self.zoom))
        y0 = max(0, math.floor(-self.oy / self.zoom))
        x1 = min(iw, math.ceil((cw - self.ox) / self.zoom))
        y1 = min(ih, math.ceil((ch - self.oy) / self.zoom))
        if x1 <= x0 or y1 <= y0:
            return
        size = (max(1, round((x1 - x0) * self.zoom)), max(1, round((y1 - y0) * self.zoom)))
        # Nearest-neighbour at high zoom shows the real pixels, which helps precise clicking.
        resample = Image.Resampling.NEAREST if self.zoom >= 2 else Image.Resampling.BILINEAR
        view = self.image.crop((x0, y0, x1, y1)).resize(size, resample)
        self._photo = ImageTk.PhotoImage(view)
        cx, cy = self.to_canvas((x0, y0))
        self.canvas.create_image(cx, cy, image=self._photo, anchor="nw", tags="image")
        self.canvas.tag_lower("image")

    def redraw_overlay(self):
        self.canvas.delete("overlay")
        painter = CanvasPainter(self.canvas, "overlay")
        for i, s in enumerate(self.shapes):
            selected = i == self.selected
            color = SELECTED_COLOR if selected else COLORS[s.kind]
            render_shape(painter, s, self.to_canvas, color, self.measure(s)[0],
                         width=3 if selected else 2)
        if self.selected is not None and self.tool.get() == "select":
            for p in self.shapes[self.selected].pts:
                x, y = self.to_canvas(p)
                self.canvas.create_rectangle(x - 5, y - 5, x + 5, y + 5, outline="black",
                                             fill=SELECTED_COLOR, tags="overlay")
        self.draw_preview()

    def preview_shape(self):
        """Return the shape being drawn, completed by the mouse position, or None."""
        if not self.pending or self.mouse is None:
            return None
        key = self.tool.get()
        pts = self.pending + [self.mouse]
        needed = TOOLS_BY_KEY[key].points
        if key == "polygon":
            return Shape("polygon" if len(pts) > 2 else "path", pts)
        if len(pts) < needed:
            return Shape("path", pts)
        return Shape(key, pts)

    def draw_preview(self):
        self.canvas.delete("preview")
        shape = self.preview_shape()
        if shape is None:
            return
        label, text = self.measure(shape)
        render_shape(CanvasPainter(self.canvas, "preview"), shape, self.to_canvas,
                     SELECTED_COLOR, label)
        if text:
            self.status.set(text)

    def refresh(self):
        """Rebuild the shape list and the scale summary, then redraw the overlay."""
        self._syncing_tree = True
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.shapes):
            self.tree.insert("", "end", iid=str(i),
                             values=(f"{i + 1}. {KIND_NAMES[s.kind]}", self.measure(s)[1]))
        if self.selected is not None and self.selected < len(self.shapes):
            self.tree.selection_set(str(self.selected))
            self.tree.see(str(self.selected))
        else:
            self.selected = None
        self._syncing_tree = False

        upp = self.units_per_px()
        n = len(self.references())
        if upp:
            u = self.unit_name()
            self.scale_label.config(text=(
                f"Scale: {fmt(upp)} {u}/px  ({fmt(1 / upp)} px/{u})\n"
                f"from {n} reference line{'s' if n != 1 else ''}"))
        else:
            self.scale_label.config(text=(
                "No reference yet: results are in pixels.\n"
                "Use the Reference tool on a feature of known length."))
        self.redraw_overlay()

    # ------------------------------------------------------------ hit testing

    def shape_distance(self, s, p):
        """Return the distance in canvas pixels from canvas point p to the outline of s."""
        pts = [self.to_canvas(q) for q in s.pts]
        if s.kind == "circle":
            return abs(geo.dist(p, pts[0]) - geo.dist(pts[0], pts[1]))
        if s.kind == "circle3":
            fit = geo.circle_from_3_points(*pts)
            if fit:
                return abs(geo.dist(p, fit[0]) - fit[1])
        if s.kind == "rect":
            (x0, y0), (x1, y1) = pts
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return geo.point_polyline_distance(p, pts, closed=s.kind in ("rect", "polygon"))

    def hit_handle(self, x, y):
        """Return (shape index, point index) of the handle at canvas (x, y), or None.

        The selected shape is checked first so its handles win over overlapping ones.
        """
        order = list(range(len(self.shapes) - 1, -1, -1))
        if self.selected is not None:
            order.remove(self.selected)
            order.insert(0, self.selected)
        for i in order:
            for j, q in enumerate(self.shapes[i].pts):
                if geo.dist((x, y), self.to_canvas(q)) <= HIT_TOLERANCE:
                    return i, j
        return None

    def hit_shape(self, x, y):
        """Return the index of the shape nearest to canvas (x, y) within tolerance, or None.

        The selected shape wins whenever it is within tolerance, so overlapping shapes
        can still be dragged after picking one in the list.
        """
        sel = self.selected
        if sel is not None and self.shape_distance(self.shapes[sel], (x, y)) <= HIT_TOLERANCE:
            return sel
        best, best_d = None, HIT_TOLERANCE
        for i, s in enumerate(self.shapes):
            d = self.shape_distance(s, (x, y))
            if d <= best_d:
                best, best_d = i, d
        return best

    # ------------------------------------------------------------ mouse

    def event_point(self, event):
        """Return the image point under the mouse, snapped to 45° steps when Shift is held."""
        p = self.to_image(event.x, event.y)
        shift = event.state & 0x0001
        if shift and self.pending and self.tool.get() not in ("rect", "circle3"):
            p = list(geo.snap_angle(self.pending[-1], p))
        return p

    def on_press(self, event):
        self.canvas.focus_set()
        self.press_at = (event.x, event.y)
        ctrl = event.state & 0x0004
        if self.image is None:
            self.open_image()
            return
        if ctrl:
            # A Ctrl-drag pans, so its release must not place a point.
            self.press_at = None
            self.start_pan(event)
            return
        if self.tool.get() == "select":
            self.select_press(event)
            return
        self.add_point(self.event_point(event))

    def select_press(self, event):
        handle = self.hit_handle(event.x, event.y)
        if handle:
            i, j = handle
            self.selected = i
            self.drag = {"type": "point", "i": i, "j": j, "moved": False}
        else:
            i = self.hit_shape(event.x, event.y)
            self.selected = i
            if i is None:
                self.start_pan(event)
            else:
                self.drag = {"type": "move", "i": i, "start": self.to_image(event.x, event.y),
                             "orig": copy.deepcopy(self.shapes[i].pts), "moved": False}
        self.refresh()

    def on_drag(self, event):
        d = self.drag
        if d is None:
            self.on_move(event)
            return
        if d["type"] == "pan":
            self.do_pan(event)
            return
        if not d["moved"]:
            # Save the undo state once, at the start of the drag.
            self.push_undo()
            d["moved"] = True
        p = self.to_image(event.x, event.y)
        shape = self.shapes[d["i"]]
        if d["type"] == "point":
            shape.pts[d["j"]] = p
        else:
            dx, dy = p[0] - d["start"][0], p[1] - d["start"][1]
            shape.pts = [[x + dx, y + dy] for x, y in d["orig"]]
        self.refresh()

    def on_release(self, event):
        self.drag = None
        start = self.press_at
        self.press_at = None
        # Press-drag-release with a two-point tool places the second point at release.
        if (start and self.tool.get() != "select" and len(self.pending) == 1
                and TOOLS_BY_KEY[self.tool.get()].points == 2
                and geo.dist(start, (event.x, event.y)) > 5):
            self.add_point(self.event_point(event))

    def on_double(self, event):
        key = self.tool.get()
        if key == "polygon":
            self.finish_polygon()
        elif key == "select":
            i = self.hit_shape(event.x, event.y)
            if i is not None and self.shapes[i].kind == "ref":
                self.selected = i
                self.edit_reference()
        else:
            # The second press of a double-click only reaches this handler, so count it as a click.
            self.on_press(event)

    def on_right(self, event):
        if self.tool.get() == "polygon" and self.pending:
            self.finish_polygon()
        else:
            self.cancel_pending()

    def on_move(self, event):
        self.mouse = self.event_point(event)
        if self.image is not None and not self.pending:
            x, y = self.mouse
            self.status.set(f"x {x:.1f}  y {y:.1f} px   |   {TOOLS_BY_KEY[self.tool.get()].hint}")
        self.draw_preview()

    def clear_mouse(self):
        self.mouse = None
        self.draw_preview()

    # ------------------------------------------------------------ editing

    def set_tool(self, key):
        self.tool.set(key)
        self.pending = []
        self.canvas.config(cursor="arrow" if key == "select" else "crosshair")
        self.status.set(TOOLS_BY_KEY[key].hint)
        self.redraw_overlay()

    def add_point(self, p):
        self.pending.append(p)
        needed = TOOLS_BY_KEY[self.tool.get()].points
        if needed and len(self.pending) >= needed:
            self.finish_shape(Shape(self.tool.get(), self.pending))
        else:
            self.draw_preview()

    def finish_polygon(self):
        if len(self.pending) >= 3:
            self.finish_shape(Shape("polygon", self.pending))
        else:
            self.status.set("A polygon needs at least 3 points.")

    def finish_shape(self, shape):
        """Validate shape and add it, asking for the real length of a reference."""
        self.pending = []
        pts = shape.pts
        if shape.kind in ("ref", "line", "circle", "rect") and geo.dist(pts[0], pts[1]) < 1e-6:
            self.status.set("Zero-length shape ignored.")
        elif shape.kind == "circle3" and geo.circle_from_3_points(*pts) is None:
            self.status.set("The three points are collinear; no circle passes through them.")
        elif shape.kind == "polygon" and geo.polygon_area(pts) < 1e-9:
            self.status.set("Polygon has no area; ignored.")
        else:
            if shape.kind == "ref":
                value = simpledialog.askfloat(
                    "Reference length",
                    f"Real length of this line in {self.unit_name()} "
                    f"({fmt(geo.dist(*pts))} px):",
                    parent=self.root, minvalue=1e-12)
                if value is None:
                    self.redraw_overlay()
                    return
                shape.value = value
            self.push_undo()
            self.shapes.append(shape)
            self.selected = len(self.shapes) - 1
            self.status.set(f"{KIND_NAMES[shape.kind]}: {self.measure(shape)[1]}")
        self.refresh()

    def cancel_pending(self):
        self.pending = []
        self.draw_preview()
        self.redraw_overlay()

    def push_undo(self):
        self.undo_stack.append(copy.deepcopy(self.shapes))
        del self.undo_stack[:-200]

    def undo(self):
        if self.pending:
            self.pending.pop()
            self.redraw_overlay()
            return
        if self.undo_stack:
            self.shapes = self.undo_stack.pop()
            self.selected = None
            self.refresh()

    def delete_selected(self):
        if self.selected is None:
            return
        self.push_undo()
        del self.shapes[self.selected]
        self.selected = None
        self.refresh()

    def clear_all(self):
        if self.shapes and messagebox.askyesno("Clear all", "Remove all shapes?"):
            self.push_undo()
            self.shapes = []
            self.selected = None
            self.refresh()

    def edit_reference(self):
        if self.selected is None or self.shapes[self.selected].kind != "ref":
            self.status.set("Select a reference line to edit its length.")
            return
        s = self.shapes[self.selected]
        value = simpledialog.askfloat(
            "Reference length", f"Real length of this line in {self.unit_name()}:",
            parent=self.root, initialvalue=s.value, minvalue=1e-12)
        if value is not None:
            self.push_undo()
            s.value = value
            self.refresh()

    def on_tree_select(self, _event):
        if self._syncing_tree:
            return
        sel = self.tree.selection()
        new = int(sel[0]) if sel else None
        if new != self.selected:
            self.selected = new
            self.redraw_overlay()

    # ------------------------------------------------------------ keyboard

    def on_key(self, event):
        # Leave typing in the unit field and the shape list alone.
        if isinstance(event.widget, (tk.Entry, ttk.Entry)) or event.state & 0x0004:
            return
        key = event.keysym
        if key == "Escape":
            self.cancel_pending()
        elif key in ("Delete", "BackSpace"):
            if self.pending:
                self.undo()
            else:
                self.delete_selected()
        elif key in ("Return", "KP_Enter") and self.tool.get() == "polygon":
            self.finish_polygon()
        elif key.lower() == "f":
            self.fit_view()
        elif key in ("plus", "equal", "KP_Add"):
            self.zoom_at(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, 1.25)
        elif key in ("minus", "KP_Subtract"):
            self.zoom_at(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, 1 / 1.25)
        else:
            for t in TOOLS:
                if key.lower() == t.shortcut:
                    self.set_tool(t.key)
                    break


def main():
    root = tk.Tk()
    App(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
