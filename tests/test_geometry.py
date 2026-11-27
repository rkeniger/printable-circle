import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "PrintableCircle"))

import printable_circle_geometry as g  # noqa: E402


def close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


class TestGeometry(unittest.TestCase):
    def test_matches_reference_sketch(self):
        # Sketch1 in Fusion: D = 50 mm, tangent points at (+-20, 15), flat +-12.5 at y = 25
        geo = g.compute((0.0, 0.0), 50.0, 0.25)
        self.assertTrue(close(geo.tangent_right, (20.0, 15.0)))
        self.assertTrue(close(geo.tangent_left, (-20.0, 15.0)))
        self.assertTrue(close(geo.top_left, (-12.5, 25.0)))
        self.assertTrue(close(geo.top_right, (12.5, 25.0)))
        self.assertAlmostEqual(geo.overhang_deg, 36.8698976, places=6)

    def test_side_line_is_tangent(self):
        for ratio in (0.05, 0.25, 0.45):
            geo = g.compute((3.0, -2.0), 17.0, ratio, math.radians(33))
            cx, cy = geo.center
            tx, ty = geo.tangent_right
            px, py = geo.top_right
            radial = (tx - cx, ty - cy)
            side = (px - tx, py - ty)
            self.assertAlmostEqual(radial[0] * side[0] + radial[1] * side[1], 0.0, places=9)
            self.assertAlmostEqual(math.hypot(*radial), geo.radius, places=9)

    def test_rotation(self):
        geo = g.compute((0.0, 0.0), 10.0, 0.25, math.radians(90))
        self.assertTrue(close(geo.top_mid, (-5.0, 0.0)))

    def test_overhang_independent_of_size(self):
        self.assertAlmostEqual(
            g.compute((0, 0), 1.0, 0.3).overhang_deg,
            g.compute((0, 0), 500.0, 0.3).overhang_deg,
        )

    def test_wrap_turn(self):
        self.assertEqual(g.wrap_turn(2 * math.pi), 0.0)
        self.assertEqual(g.wrap_turn(-2 * math.pi), 0.0)
        self.assertEqual(g.wrap_turn(0.0), 0.0)
        self.assertAlmostEqual(g.wrap_turn(math.radians(450)), math.radians(90))
        self.assertAlmostEqual(g.wrap_turn(math.radians(-90)), math.radians(270))

    def test_ratio_limits(self):
        with self.assertRaises(ValueError):
            g.compute((0, 0), 10.0, 0.5)
        with self.assertRaises(ValueError):
            g.compute((0, 0), 10.0, 0.0)


class TestTeardrop(unittest.TestCase):
    def test_45_degrees(self):
        geo = g.compute_teardrop((0.0, 0.0), 20.0, math.radians(45))
        root2 = math.sqrt(2)
        self.assertTrue(close(geo.apex, (0.0, 10.0 * root2)))
        self.assertTrue(close(geo.tangent_right, (10.0 / root2, 10.0 / root2)))
        self.assertTrue(close(geo.tangent_left, (-10.0 / root2, 10.0 / root2)))
        self.assertTrue(close(geo.bottom, (0.0, -10.0)))

    def test_side_line_is_tangent_and_leans_by_overhang(self):
        for degrees in (15, 30, 45, 75):
            geo = g.compute_teardrop((3.0, -2.0), 17.0, math.radians(degrees), math.radians(33))
            cx, cy = geo.center
            tx, ty = geo.tangent_right
            ax, ay = geo.apex
            radial = (tx - cx, ty - cy)
            side = (ax - tx, ay - ty)
            axis = (ax - cx, ay - cy)
            self.assertAlmostEqual(radial[0] * side[0] + radial[1] * side[1], 0.0, places=9)
            self.assertAlmostEqual(math.hypot(*radial), geo.radius, places=9)
            cos_lean = (side[0] * axis[0] + side[1] * axis[1]) / (math.hypot(*side) * math.hypot(*axis))
            self.assertAlmostEqual(math.degrees(math.acos(cos_lean)), degrees, places=7)

    def test_matches_capped_walls(self):
        # A teardrop is a capped circle with its side walls extended until they meet.
        cap = g.compute((0.0, 0.0), 10.0, 0.25)
        tear = g.compute_teardrop((0.0, 0.0), 10.0, math.radians(cap.overhang_deg))
        self.assertTrue(close(tear.tangent_right, cap.tangent_right))

    def test_rotation(self):
        geo = g.compute_teardrop((0.0, 0.0), 10.0, math.radians(30), math.radians(90))
        self.assertTrue(close(geo.apex, (-10.0, 0.0)))

    def test_overhang_limits(self):
        with self.assertRaises(ValueError):
            g.compute_teardrop((0, 0), 10.0, math.radians(10))
        with self.assertRaises(ValueError):
            g.compute_teardrop((0, 0), 10.0, math.radians(80))


if __name__ == "__main__":
    unittest.main()
