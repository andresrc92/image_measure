import math
import unittest

import geometry as geo


class GeometryTest(unittest.TestCase):
    def test_circle_from_3_points(self):
        center, r = geo.circle_from_3_points((10, 0), (0, 10), (-10, 0))
        self.assertAlmostEqual(center[0], 0)
        self.assertAlmostEqual(center[1], 0)
        self.assertAlmostEqual(r, 10)

    def test_circle_collinear(self):
        self.assertIsNone(geo.circle_from_3_points((0, 0), (1, 1), (2, 2)))

    def test_angle(self):
        self.assertAlmostEqual(geo.angle_deg((1, 0), (0, 0), (0, 1)), 90)
        self.assertAlmostEqual(geo.angle_deg((1, 0), (0, 0), (-1, 0)), 180)
        self.assertAlmostEqual(geo.angle_deg((1, 0), (0, 0), (1, 1)), 45)

    def test_polygon(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4)]
        self.assertAlmostEqual(geo.polygon_area(square), 16)
        self.assertAlmostEqual(geo.polyline_length(square, closed=True), 16)
        self.assertAlmostEqual(geo.polyline_length(square), 12)

    def test_segment_distance(self):
        self.assertAlmostEqual(geo.point_segment_distance((5, 3), (0, 0), (10, 0)), 3)
        self.assertAlmostEqual(geo.point_segment_distance((13, 4), (0, 0), (10, 0)), 5)

    def test_snap(self):
        x, y = geo.snap_angle((0, 0), (10, 1))
        self.assertAlmostEqual(y, 0)
        self.assertAlmostEqual(x, math.hypot(10, 1))

    def test_scale(self):
        self.assertIsNone(geo.scale_from_references([]))
        self.assertAlmostEqual(geo.scale_from_references([(100, 10)]), 0.1)
        # Length-weighted: (10 + 30) / (100 + 200)
        self.assertAlmostEqual(geo.scale_from_references([(100, 10), (200, 30)]), 40 / 300)


if __name__ == "__main__":
    unittest.main()
