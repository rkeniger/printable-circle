"""Pure-maths geometry for the capdrop profile (no Fusion imports).

The profile is a circle of diameter D whose top is replaced by a flat line of
half-width k*D, tangent to the circle at its top point, joined back to the
circle by two lines that are tangent to it.

All coordinates are 2D sketch coordinates. "Up" is sketch +Y rotated
counterclockwise by theta.
"""

import math
from dataclasses import dataclass

RATIO_MIN = 0.05
RATIO_MAX = 0.45
DEFAULT_RATIO = 0.207  # about 45° side walls; exactly 45° is (sqrt(2) - 1) / 2


@dataclass(frozen=True)
class CapdropGeometry:
    center: tuple
    top_mid: tuple
    top_left: tuple
    top_right: tuple
    tangent_left: tuple
    tangent_right: tuple
    bottom: tuple
    radius: float
    half_width: float
    overhang_deg: float  # side-wall angle measured from vertical


def tangent_point_local(radius, half_width):
    """Right-hand tangent point (x, y) in the capdrop's local frame.

    Local frame: circle centred at the origin, flat at y = radius.
    """
    dist = math.hypot(half_width, radius)
    phi = math.atan2(radius, half_width)
    alpha = math.acos(radius / dist)
    t = phi - alpha
    return (radius * math.cos(t), radius * math.sin(t))


def overhang_from_vertical_deg(ratio):
    """Side-wall angle from vertical. It depends only on the ratio."""
    tx, ty = tangent_point_local(1.0, 2.0 * ratio)  # diameter 2, so radius 1
    dx = tx - 2.0 * ratio
    dy = 1.0 - ty
    return math.degrees(math.atan2(dx, dy))


def compute(center, diameter, ratio, theta_rad=0.0):
    if diameter <= 0:
        raise ValueError("diameter must be positive")
    if not (RATIO_MIN - 1e-9 <= ratio <= RATIO_MAX + 1e-9):
        raise ValueError(f"ratio must be between {RATIO_MIN} and {RATIO_MAX}")

    cx, cy = center
    r = diameter / 2.0
    w = diameter * ratio
    s, c = math.sin(theta_rad), math.cos(theta_rad)

    def to_sketch(x, y):
        # right = (c, s); up = (-s, c)
        return (cx + x * c - y * s, cy + x * s + y * c)

    tx, ty = tangent_point_local(r, w)
    return CapdropGeometry(
        center=(cx, cy),
        top_mid=to_sketch(0.0, r),
        top_left=to_sketch(-w, r),
        top_right=to_sketch(w, r),
        tangent_left=to_sketch(-tx, ty),
        tangent_right=to_sketch(tx, ty),
        bottom=to_sketch(0.0, -r),
        radius=r,
        half_width=w,
        overhang_deg=overhang_from_vertical_deg(ratio),
    )
