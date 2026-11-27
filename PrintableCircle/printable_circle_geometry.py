"""Pure-maths geometry for the capped circle and teardrop profiles (no Fusion imports).

The capped circle is a circle of diameter D whose top is replaced by a flat line of
half-width k*D, tangent to the circle at its top point, joined back to the
circle by two lines that are tangent to it.

The teardrop has no flat: its two tangent lines carry on until they meet at a
point above the circle.

All coordinates are 2D sketch coordinates. "Up" is sketch +Y rotated
counterclockwise by theta.
"""

import math
from dataclasses import dataclass

RATIO_MIN = 0.05
RATIO_MAX = 0.45
DEFAULT_RATIO = 0.207  # about 45° side walls; exactly 45° is (sqrt(2) - 1) / 2

# Teardrop side-wall angle from vertical, in degrees.
OVERHANG_MIN_DEG = 15.0
OVERHANG_MAX_DEG = 75.0
DEFAULT_OVERHANG_DEG = 45.0


@dataclass(frozen=True)
class CappedGeometry:
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


@dataclass(frozen=True)
class TeardropGeometry:
    center: tuple
    apex: tuple
    tangent_left: tuple
    tangent_right: tuple
    bottom: tuple
    radius: float
    apex_height: float  # centre to the point
    overhang_deg: float  # side-wall angle measured from vertical


def wrap_turn(angle_rad):
    """Map an angle to the range [0, 2*pi), so a full turn reads as zero."""
    angle = math.fmod(angle_rad, 2 * math.pi)
    if angle < 0:
        angle += 2 * math.pi
    if angle < 1e-9 or 2 * math.pi - angle < 1e-9:
        return 0.0
    return angle


def _to_sketch(center, theta_rad):
    """A function mapping local (x, y) to sketch coordinates."""
    cx, cy = center
    s, c = math.sin(theta_rad), math.cos(theta_rad)
    # right = (c, s); up = (-s, c)
    return lambda x, y: (cx + x * c - y * s, cy + x * s + y * c)


def tangent_point_local(radius, half_width):
    """Right-hand tangent point (x, y) in the capped circle's local frame.

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

    r = diameter / 2.0
    w = diameter * ratio
    to_sketch = _to_sketch(center, theta_rad)

    tx, ty = tangent_point_local(r, w)
    return CappedGeometry(
        center=tuple(center),
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


def teardrop_apex_height(radius, overhang_rad):
    """Distance from the centre to the teardrop's point."""
    return radius / math.sin(overhang_rad)


def compute_teardrop(center, diameter, overhang_rad, theta_rad=0.0):
    """A teardrop whose side walls lean overhang_rad away from vertical."""
    if diameter <= 0:
        raise ValueError("diameter must be positive")
    overhang_deg = math.degrees(overhang_rad)
    if not (OVERHANG_MIN_DEG - 1e-9 <= overhang_deg <= OVERHANG_MAX_DEG + 1e-9):
        raise ValueError(
            f"overhang must be between {OVERHANG_MIN_DEG} and {OVERHANG_MAX_DEG} degrees"
        )

    r = diameter / 2.0
    to_sketch = _to_sketch(center, theta_rad)
    # A wall leaning by the overhang angle touches the circle at that same
    # angle above the horizontal.
    tx, ty = r * math.cos(overhang_rad), r * math.sin(overhang_rad)
    height = teardrop_apex_height(r, overhang_rad)
    return TeardropGeometry(
        center=tuple(center),
        apex=to_sketch(0.0, height),
        tangent_left=to_sketch(-tx, ty),
        tangent_right=to_sketch(tx, ty),
        bottom=to_sketch(0.0, -r),
        radius=r,
        apex_height=height,
        overhang_deg=overhang_deg,
    )
