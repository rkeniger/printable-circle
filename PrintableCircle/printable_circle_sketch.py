"""Writes fully constrained capped circles and teardrops into a Fusion sketch."""

import math

import adsk.core
import adsk.fusion

from . import printable_circle_geometry as sg


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


def _orient(sketch, center_point, axis, length, theta, link_to):
    """Fix the direction of the axis (centre to top), which is `length` long.

    Returns (reference line, angle dimension); both are None unless this shape
    carries its own rotation dimension.
    """
    gc = sketch.geometricConstraints
    if abs(math.sin(theta)) < 1e-9:
        gc.addVertical(axis)
        return None, None
    if link_to is not None:
        gc.addParallel(axis, link_to["axis"])
        return None, None
    c = center_point.geometry
    ref = sketch.sketchCurves.sketchLines.addByTwoPoints(center_point, _p((c.x, c.y + length)))
    ref.isConstruction = True
    gc.addVertical(ref)
    gc.addEqual(ref, axis)
    # Put the text on the bisector between the two lines to choose the right sector.
    half = theta / 2.0
    tp = (c.x - 0.6 * length * math.sin(half), c.y + 0.6 * length * math.cos(half))
    angle_dim = sketch.sketchDimensions.addAngularDimension(ref, axis, _p(tp))
    return ref, angle_dim


def _diameter_dimension(sketch, arc, center, radius, theta):
    text = (center.x + 0.75 * radius * math.cos(theta - math.pi / 4),
            center.y + 0.75 * radius * math.sin(theta - math.pi / 4))
    return sketch.sketchDimensions.addDiameterDimension(arc, _p(text))


def _set_rotation(angle_dim, theta):
    if angle_dim is not None:
        angle_dim.parameter.expression = f"{round(abs(math.degrees(theta)), 6)} deg"


def build(sketch, center_point, diameter, ratio, theta=0.0, link_to=None):
    """Draw a capped circle centred on center_point (a SketchPoint in this sketch).

    diameter is in Fusion internal units (cm), theta in radians, measured
    counterclockwise from sketch +Y to the direction the flat faces.
    Pass an earlier result as link_to to make this capped circle follow that one:
    its diameter and half-width dimensions reference the first one's, and its
    axis is kept parallel to the first one's axis.
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

        ref, angle_dim = _orient(sketch, center_point, axis, r, theta, link_to)

        dia_dim = _diameter_dimension(sketch, arc, c, r, theta)
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

    if link_to is not None:
        dia_dim.parameter.expression = link_to["diameter_dim"].parameter.name
        hw_dim.parameter.expression = link_to["half_width_dim"].parameter.name
    else:
        dia_dim.parameter.value = diameter
        hw_dim.parameter.expression = f"{dia_dim.parameter.name} * {round(ratio, 6)}"
    _set_rotation(angle_dim, theta)

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


def build_teardrop(sketch, center_point, diameter, overhang, theta=0.0, link_to=None):
    """Draw a teardrop centred on center_point (a SketchPoint in this sketch).

    overhang is the side-wall angle from vertical, in radians. The other
    arguments are as for build(). A linked teardrop takes its diameter and
    overhang from the first one and keeps its axis parallel to the first one's.
    Returns a dict of the created entities.
    """
    theta = _normalise_angle(theta)
    c = center_point.geometry
    geo = sg.compute_teardrop((c.x, c.y), diameter, overhang, theta)
    r = geo.radius

    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    gc = sketch.geometricConstraints
    dims = sketch.sketchDimensions

    sketch.isComputeDeferred = True
    try:
        left = lines.addByTwoPoints(_p(geo.apex), _p(geo.tangent_left))
        right = lines.addByTwoPoints(left.startSketchPoint, _p(geo.tangent_right))
        arc = arcs.addByCenterStartEnd(center_point, left.endSketchPoint, right.endSketchPoint)
        if arc.centerSketchPoint != center_point:
            gc.addCoincident(arc.centerSketchPoint, center_point)

        axis = lines.addByTwoPoints(center_point, left.startSketchPoint)
        axis.isConstruction = True

        gc.addTangent(left, arc)
        gc.addTangent(right, arc)

        ref, angle_dim = _orient(sketch, center_point, axis, geo.apex_height, theta, link_to)

        dia_dim = _diameter_dimension(sketch, arc, c, r, theta)
        # The overhang is the angle at the point between the axis and a side wall.
        # The text goes on their bisector, just below the point.
        up = (-math.sin(theta), math.cos(theta))
        across = (math.cos(theta), math.sin(theta))
        reach = 0.5 * r
        dx, dy = reach * math.sin(overhang / 2), -reach * math.cos(overhang / 2)
        oh_text = (geo.apex[0] + dx * across[0] + dy * up[0],
                   geo.apex[1] + dx * across[1] + dy * up[1])
        oh_dim = dims.addAngularDimension(axis, right, _p(oh_text))
    finally:
        sketch.isComputeDeferred = False

    if link_to is not None:
        dia_dim.parameter.expression = link_to["diameter_dim"].parameter.name
        oh_dim.parameter.expression = link_to["overhang_dim"].parameter.name
    else:
        dia_dim.parameter.value = diameter
        oh_dim.parameter.expression = f"{round(math.degrees(overhang), 6)} deg"
    _set_rotation(angle_dim, theta)

    return {
        "left": left,
        "right": right,
        "arc": arc,
        "axis": axis,
        "ref": ref,
        "diameter_dim": dia_dim,
        "overhang_dim": oh_dim,
        "angle_dim": angle_dim,
    }
