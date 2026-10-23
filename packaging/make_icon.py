"""Draw the 256x256 app icon (a ruler under a measured circle) to image-measure.png.

Usage: python3 packaging/make_icon.py [output path]
"""

import sys

from PIL import Image, ImageDraw

S = 256
out = sys.argv[1] if len(sys.argv) > 1 else "image-measure.png"

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=48, fill="#2c2c2e")

# Measured circle with its radius line and center dot.
d.ellipse((60, 36, 196, 172), outline="#0a84ff", width=10)
d.line((128, 104, 196, 104), fill="#ffd60a", width=6)
d.ellipse((120, 96, 136, 112), fill="#ffd60a")

# Ruler with tick marks along its top edge.
d.rounded_rectangle((32, 186, 224, 226), radius=6, fill="#ff453a")
for i, x in enumerate(range(44, 220, 16)):
    d.line((x, 186, x, 198 if i % 2 else 206), fill="#1c1c1e", width=3)

img.save(out)
