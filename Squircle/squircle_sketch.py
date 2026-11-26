"""Writes a fully constrained squircle into a Fusion sketch."""

import math

import adsk.core
import adsk.fusion

from . import squircle_geometry as sg


def _p(xy):
    return adsk.core.Point3D.create(xy[0], xy[1], 0)


def _normalise_angle(theta):
    """Map an angle to the range (-pi, pi]."""
    theta = math.fmod(theta, 2 * math.pi)
    if theta <= -math.pi:
        theta += 2 * math.pi
    elif theta > math.pi:
        theta -= 2 * math.pi
    return theta


def build(sketch, center_point, diameter, ratio, theta=0.0):
    """Draw a squircle centred on center_point (a SketchPoint in this sketch).

    diameter is in Fusion internal units (cm), theta in radians, measured
    counterclockwise from sketch +Y to the direction the flat faces.
    Returns a dict of the created entities.
    """
    theta = _normalise_angle(theta)
    c = center_point.geometry
    geo = sg.compute((c.x, c.y), diameter, ratio, theta)
    r = geo.radius

    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    gc = sketch.geometricConstraints
    dims = sketch.sketchDimensions

    sketch.isComputeDeferred = True
    try:
        top = lines.addByTwoPoints(_p(geo.top_left), _p(geo.top_right))
        left = lines.addByTwoPoints(top.startSketchPoint, _p(geo.tangent_left))
        right = lines.addByTwoPoints(top.endSketchPoint, _p(geo.tangent_right))
        # Arcs always run counterclockwise, so going from the left tangent point to
        # the right one sweeps through the bottom of the circle.
        arc = arcs.addByCenterStartEnd(center_point, left.endSketchPoint, right.endSketchPoint)
        # Fusion creates a new centre point even when given a SketchPoint.
        if arc.centerSketchPoint != center_point:
            gc.addCoincident(arc.centerSketchPoint, center_point)

        axis = lines.addByTwoPoints(center_point, _p(geo.top_mid))
        axis.isConstruction = True

        gc.addMidPoint(axis.endSketchPoint, top)
        gc.addPerpendicular(axis, top)
        gc.addTangent(top, arc)
        gc.addTangent(left, arc)
        gc.addTangent(right, arc)

        # Orientation
        ref = None
        angle_dim = None
        if abs(math.sin(theta)) < 1e-9:
            gc.addVertical(axis)
        else:
            ref = lines.addByTwoPoints(center_point, _p((c.x, c.y + r)))
            ref.isConstruction = True
            gc.addVertical(ref)
            gc.addEqual(ref, axis)
            # Put the text on the bisector between the two lines to choose the right sector.
            half = theta / 2.0
            tp = (c.x - 0.6 * r * math.sin(half), c.y + 0.6 * r * math.cos(half))
            angle_dim = dims.addAngularDimension(ref, axis, _p(tp))

        # Dimensions
        dia_text = (c.x + 0.75 * r * math.cos(theta - math.pi / 4),
                    c.y + 0.75 * r * math.sin(theta - math.pi / 4))
        dia_dim = dims.addDiameterDimension(arc, _p(dia_text))
        up = (-math.sin(theta), math.cos(theta))
        hw_text = ((geo.top_mid[0] + geo.top_right[0]) / 2 + up[0] * 0.25 * r,
                   (geo.top_mid[1] + geo.top_right[1]) / 2 + up[1] * 0.25 * r)
        hw_dim = dims.addDistanceDimension(
            axis.endSketchPoint,
            top.endSketchPoint,
            adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
            _p(hw_text),
        )
    finally:
        sketch.isComputeDeferred = False

    dia_dim.parameter.value = diameter
    hw_dim.parameter.expression = f"{dia_dim.parameter.name} * {round(ratio, 6)}"
    if angle_dim is not None:
        angle_dim.parameter.expression = f"{round(abs(math.degrees(theta)), 6)} deg"

    return {
        "top": top,
        "left": left,
        "right": right,
        "arc": arc,
        "axis": axis,
        "ref": ref,
        "diameter_dim": dia_dim,
        "half_width_dim": hw_dim,
        "angle_dim": angle_dim,
    }
