# Image Measure

A small Tkinter app for measuring things in an image: lengths, radii, angles, rectangles and polygon areas.

## Run

```
pip install -r requirements.txt   # Tkinter ships with Python; on Debian/Ubuntu: apt install python3-tk
python3 image_measure.py [image]
```

## Workflow

1. **Open** an image (Ctrl+O).
2. Pick the **Reference** tool (R). Draw a line over something whose real size you know, then type its length. Set the unit in the toolbar (default `mm`).
   You can add several references; the scale is their length-weighted average, and each one shows how far it is from that average (a large % means the image is distorted or a click was off).
3. Measure with:
   | Tool | Key | Clicks | Result |
   |---|---|---|---|
   | Line | L | start, end (or drag) | length |
   | Circle (center) | C | center, edge point | radius, diameter, area |
   | Circle (3 pts) | 3 | three points on the edge | radius, diameter, area |
   | Angle | A | arm end, vertex, arm end | angle in degrees |
   | Rectangle | B | two corners (or drag) | width, height, diagonal, area |
   | Polygon | P | corners; Enter / double-click / right-click to close | area, perimeter |

   With no reference, results are in pixels.

## Controls

- **Select** (V): click a shape or its row in the list. Drag a square handle to move a point, or drag the shape to move it. Del deletes. Double-click a reference to change its length.
- Zoom with the mouse wheel or `+`/`-`. Pan by dragging with the middle button, with Ctrl+left drag, or by dragging empty space in Select mode. `F` fits the image to the window.
- Hold **Shift** while placing a point to snap to 0°/45°/90°.
- **Esc** cancels the shape in progress. **Ctrl+Z** undoes (removes the last placed point while drawing).
- **Save** / **Load** (Ctrl+S / Ctrl+L) store the shapes in a JSON file next to the image. **Export PNG** (Ctrl+E) writes the image with all annotations at full resolution.

## Tests

```
python3 -m unittest test_geometry
```
