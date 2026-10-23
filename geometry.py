"""Plane geometry helpers used by the image measuring app.

Points are (x, y) pairs. The functions work in any consistent unit; the app
calls them with image pixel coordinates or canvas pixel coordinates.
"""

import math


def dist(a, b):
    """Return the Euclidean distance between points a and b."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def circle_from_3_points(a, b, c):
    """Return (center, radius) of the circle through points a, b and c.

    Returns None when the three points are (nearly) collinear, because no
    finite circle passes through them.
    """
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    # Twice the signed triangle area; scale the tolerance with the point spread.
    span = max(dist(a, b), dist(b, c), dist(a, c), 1e-12)
    if abs(d) < 1e-9 * span * span:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    center = (ux, uy)
    return center, dist(center, a)


def angle_deg(a, vertex, b):
    """Return the angle a-vertex-b in degrees, between 0 and 180."""
    v1 = (a[0] - vertex[0], a[1] - vertex[1])
    v2 = (b[0] - vertex[0], b[1] - vertex[1])
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    if cross == 0 and dot == 0:
        return 0.0
    return math.degrees(math.atan2(abs(cross), dot))


def polygon_area(pts):
    """Return the area enclosed by the closed polygon pts (shoelace formula)."""
    n = len(pts)
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def polyline_length(pts, closed=False):
    """Return the summed segment length of pts, including the closing segment if closed."""
    total = sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    if closed and len(pts) > 2:
        total += dist(pts[-1], pts[0])
    return total


def point_segment_distance(p, a, b):
    """Return the shortest distance from point p to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return dist(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return dist(p, (a[0] + t * dx, a[1] + t * dy))


def point_polyline_distance(p, pts, closed=False):
    """Return the shortest distance from point p to the polyline pts."""
    if len(pts) == 1:
        return dist(p, pts[0])
    segments = list(zip(pts, pts[1:]))
    if closed and len(pts) > 2:
        segments.append((pts[-1], pts[0]))
    return min(point_segment_distance(p, a, b) for a, b in segments)


def snap_angle(origin, p, step_deg=45):
    """Rotate p around origin to the nearest multiple of step_deg, keeping its distance."""
    r = dist(origin, p)
    if r == 0:
        return p
    ang = math.atan2(p[1] - origin[1], p[0] - origin[0])
    step = math.radians(step_deg)
    ang = round(ang / step) * step
    return (origin[0] + r * math.cos(ang), origin[1] + r * math.sin(ang))


def scale_from_references(refs):
    """Return real units per pixel from a list of (pixel_length, real_length) pairs.

    The result is total real length divided by total pixel length, so longer
    reference lines carry more weight. Pairs with a non-positive length are
    skipped. Returns None when no usable pair is left.
    """
    usable = [(px, real) for px, real in refs if px > 0 and real > 0]
    if not usable:
        return None
    return sum(real for _, real in usable) / sum(px for px, _ in usable)
