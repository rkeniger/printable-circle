"""Printable Circle: a sketch tool that draws a circle with a flat or pointed top, so the
profile can be 3D printed upright on an FDM printer without supports."""

import json
import math
import os
import traceback

import adsk.core
import adsk.fusion

from . import printable_circle_geometry as sg
from . import printable_circle_sketch as ss

CMD_ID = "PrintableCircleSketchCommand"
CMD_NAME = "Printable Circle"
CMD_TOOLTIP = (
    "Circle with tangent side walls and a flat top (capped) or a point "
    "(teardrop), so it prints upright without supports."
)
HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(HERE, "resources")
SETTINGS_FILE = os.path.join(HERE, "settings.json")

# Where the button goes: (panel id, dropdown id or None, control to sit after)
PLACEMENTS = [
    ("SketchCreatePanel", "CircleDropDown", "CircleThreeTangent"),
    ("SolidCreatePanel", None, "SketchCreate"),
]

# Shape names as shown in the dialog, keyed by the name stored in settings.
SHAPES = {"capped": "Capped", "teardrop": "Teardrop"}

DEFAULTS = {
    "shape": "capped",
    "diameter": 1.0,  # cm
    "ratio": sg.DEFAULT_RATIO,
    "overhang": math.radians(sg.DEFAULT_OVERHANG_DEG),  # rad
    "angle": 0.0,  # rad
}
OVERHANG_MIN = math.radians(sg.OVERHANG_MIN_DEG)
OVERHANG_MAX = math.radians(sg.OVERHANG_MAX_DEG)

_app = None
_ui = None
_handlers = []
_manip_event = None
_manip_handler = None
MANIP_EVENT_ID = "PrintableCircleManipulatorUpdate"
_state = {}


# ---------------------------------------------------------------- settings
def _load_settings():
    values = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as f:
            for key, value in json.load(f).items():
                if key == "shape":
                    values[key] = str(value)
                elif key in DEFAULTS:
                    values[key] = float(value)
    except (OSError, ValueError, TypeError, AttributeError):
        values = dict(DEFAULTS)
    if values["shape"] not in SHAPES:
        values["shape"] = DEFAULTS["shape"]
    values["ratio"] = min(max(values["ratio"], sg.RATIO_MIN), sg.RATIO_MAX)
    values["overhang"] = min(max(values["overhang"], OVERHANG_MIN), OVERHANG_MAX)
    # Dragging the dial a full turn stores 360°, which draws the same as 0°.
    values["angle"] = sg.wrap_turn(values["angle"])
    if values["diameter"] <= 0:
        values["diameter"] = DEFAULTS["diameter"]
    return values


def _save_settings(values):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(values, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- helpers
def _design():
    return adsk.fusion.Design.cast(_app.activeProduct)


def _active_sketch():
    design = _design()
    if design is None:
        return None
    return adsk.fusion.Sketch.cast(design.activeEditObject)


def _shape(inputs):
    item = adsk.core.DropDownCommandInput.cast(inputs.itemById("shape")).selectedItem
    teardrop = item is not None and item.name == SHAPES["teardrop"]
    return "teardrop" if teardrop else "capped"


def _read_inputs(inputs):
    return {
        "shape": _shape(inputs),
        "diameter": adsk.core.DistanceValueCommandInput.cast(inputs.itemById("diameter")).value,
        "ratio": adsk.core.FloatSpinnerCommandInput.cast(inputs.itemById("ratio")).value,
        "overhang": adsk.core.ValueCommandInput.cast(inputs.itemById("overhang")).value,
        "angle": adsk.core.AngleValueCommandInput.cast(inputs.itemById("angle")).value,
    }


def _target_sketch(inputs):
    """The sketch to draw into. Creates one on the selected plane if needed."""
    sketch = _state.get("sketch")
    if sketch is not None and sketch.isValid:
        return sketch
    plane_input = inputs.itemById("plane")
    if plane_input is None or plane_input.selectionCount == 0:
        return None
    return _design().activeComponent.sketches.add(plane_input.selection(0).entity)


def _sketch_point(sketch, entity):
    point = adsk.fusion.SketchPoint.cast(entity)
    if point is not None and point.parentSketch == sketch:
        return point
    projected = sketch.project(entity)
    for i in range(projected.count):
        p = adsk.fusion.SketchPoint.cast(projected.item(i))
        if p is not None:
            return p
    raise RuntimeError("Could not use the selected centre point.")


def _center_points(sketch, inputs):
    """The selected centre points, in selection order."""
    center_input = inputs.itemById("center")
    # Collect the entities first: projecting into the sketch can disturb the selection.
    entities = [center_input.selection(i).entity for i in range(center_input.selectionCount)]
    points = []
    for entity in entities:
        point = _sketch_point(sketch, entity)
        # Two selections can land on the same spot, e.g. a vertex and a point on it.
        if not any(point.geometry.isEqualTo(other.geometry) for other in points):
            points.append(point)
    return points


def _frame(sketch, center):
    """The centre and the sketch X and Y directions in model space, as tuples."""
    c = center.geometry
    o = sketch.sketchToModelSpace(c)
    px = sketch.sketchToModelSpace(adsk.core.Point3D.create(c.x + 1, c.y, c.z))
    py = sketch.sketchToModelSpace(adsk.core.Point3D.create(c.x, c.y + 1, c.z))
    r = lambda values: tuple(round(v, 7) for v in values)
    return (
        r((o.x, o.y, o.z)),
        r((px.x - o.x, px.y - o.y, px.z - o.z)),
        r((py.x - o.x, py.y - o.y, py.z - o.z)),
    )


def _set_manipulators_enabled(inputs, enabled):
    for input_id in ("diameter", "angle"):
        item = inputs.itemById(input_id)
        if item.isEnabled != enabled:
            item.isEnabled = enabled


def _apply_frame(inputs, frame):
    """Put the drag arrow and rotation dial at the centre, flat on the sketch plane."""
    o, x, y = frame
    origin = adsk.core.Point3D.create(*o)
    x_dir = adsk.core.Vector3D.create(*x)
    y_dir = adsk.core.Vector3D.create(*y)
    minus_x = adsk.core.Vector3D.create(-x[0], -x[1], -x[2])
    dia = adsk.core.DistanceValueCommandInput.cast(inputs.itemById("diameter"))
    ang = adsk.core.AngleValueCommandInput.cast(inputs.itemById("angle"))
    dia.setManipulator(origin, x_dir)
    # Angle 0 points along sketch +Y; positive turns counterclockwise (toward -X).
    ang.setManipulator(origin, y_dir, minus_x)
    _set_manipulators_enabled(inputs, True)
    # Placing the dial makes Fusion show a rotation of 0° as 360°. Put it back.
    if ang.value != 0 and sg.wrap_turn(ang.value) == 0:
        ang.value = 0.0
    _state["applied_frame"] = frame


def _request_manipulator_update(sketch, center):
    """Fusion ignores setManipulator calls made inside executePreview, and a
    sketch made on a picked plane only exists during the preview. So the preview
    records the frame and a custom event applies it once the preview is done."""
    frame = _frame(sketch, center)
    if frame != _state.get("applied_frame"):
        _state["frame"] = frame
        _app.fireCustomEvent(MANIP_EVENT_ID)


def _overhang_ok(inputs, values):
    overhang_input = adsk.core.ValueCommandInput.cast(inputs.itemById("overhang"))
    return (
        overhang_input.isValidExpression
        and OVERHANG_MIN - 1e-9 <= values["overhang"] <= OVERHANG_MAX + 1e-9
    )


def _show_shape_inputs(inputs):
    """Show only the wall control that belongs to the chosen shape."""
    teardrop = _shape(inputs) == "teardrop"
    inputs.itemById("ratio").isVisible = not teardrop
    inputs.itemById("overhang").isVisible = teardrop


def _update_info(inputs):
    info = adsk.core.TextBoxCommandInput.cast(inputs.itemById("info"))
    values = _read_inputs(inputs)
    units = _design().unitsManager
    # formattedText renders HTML; plain .text shows tags literally.
    if values["shape"] == "teardrop":
        if not _overhang_ok(inputs, values):
            info.formattedText = (
                f"Overhang must be {sg.OVERHANG_MIN_DEG:g}° to {sg.OVERHANG_MAX_DEG:g}°"
            )
            return
        radius = values["diameter"] / 2
        rise = sg.teardrop_apex_height(radius, values["overhang"]) - radius
        info.formattedText = (
            f"Overhang: {math.degrees(values['overhang']):.1f}°<br>"
            f"Point: {units.formatInternalValue(round(rise, 3))} above"
        )
        return
    bridge = units.formatInternalValue(2 * values["ratio"] * values["diameter"])
    overhang = sg.overhang_from_vertical_deg(values["ratio"])
    info.formattedText = f"Overhang: {overhang:.1f}°<br>Bridge: {bridge}"


def _build(inputs, preview=False):
    values = _read_inputs(inputs)
    sketch = _target_sketch(inputs)
    if sketch is None:
        return False
    centers = _center_points(sketch, inputs)
    if not centers:
        return False
    # The first shape carries the driving dimensions; the rest follow it.
    first = None
    for center in centers:
        if values["shape"] == "teardrop":
            result = ss.build_teardrop(
                sketch, center, values["diameter"], values["overhang"], values["angle"], link_to=first
            )
        else:
            result = ss.build(
                sketch, center, values["diameter"], values["ratio"], values["angle"], link_to=first
            )
        first = first or result
    if preview:
        _request_manipulator_update(sketch, centers[0])
    _state["values"] = values
    return True


# ---------------------------------------------------------------- handlers
class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
            inputs = cmd.commandInputs
            values = _load_settings()
            _state.clear()
            _state["sketch"] = _active_sketch()

            if _state["sketch"] is None:
                plane = inputs.addSelectionInput(
                    "plane", "Plane", "Select a plane or planar face to sketch on"
                )
                plane.addSelectionFilter("PlanarFaces")
                plane.addSelectionFilter("ConstructionPlanes")
                plane.setSelectionLimits(1, 1)

            center = inputs.addSelectionInput(
                "center", "Centres", "Select one or more centre points"
            )
            center.addSelectionFilter("SketchPoints")
            center.addSelectionFilter("ConstructionPoints")
            center.addSelectionFilter("Vertices")
            center.setSelectionLimits(1, 0)  # at least one, no upper limit

            shape = inputs.addDropDownCommandInput(
                "shape", "Shape", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for key, label in SHAPES.items():
                shape.listItems.add(label, key == values["shape"])
            shape.tooltip = "Capped has a flat top. Teardrop's side walls meet at a point."

            dia = inputs.addDistanceValueCommandInput(
                "diameter", "Diameter", adsk.core.ValueInput.createByReal(values["diameter"])
            )
            dia.minimumValue = 0
            dia.isMinimumValueInclusive = False

            inputs.addFloatSpinnerCommandInput(
                "ratio", "Diameter Ratio", "", sg.RATIO_MIN, sg.RATIO_MAX, 0.01, values["ratio"]
            ).tooltip = "Half the flat's width, as a fraction of the diameter. 0.25 gives a flat half as wide as the circle."

            inputs.addValueInput(
                "overhang", "Overhang", "deg", adsk.core.ValueInput.createByReal(values["overhang"])
            ).tooltip = (
                "Side-wall angle from vertical, "
                f"{sg.OVERHANG_MIN_DEG:g}° to {sg.OVERHANG_MAX_DEG:g}°. 45° prints without supports."
            )
            _show_shape_inputs(inputs)

            ang = inputs.addAngleValueCommandInput(
                "angle", "Rotation", adsk.core.ValueInput.createByReal(values["angle"])
            )
            ang.tooltip = "Rotation of the top away from sketch +Y, counterclockwise."

            info = inputs.addTextBoxCommandInput("info", "", "", 2, True)
            info.tooltip = (
                "Overhang is the side-wall angle from vertical. Bridge is the length of "
                "the flat top. Point is how far the teardrop's tip sits above the circle."
            )
            _update_info(inputs)

            # Nothing is drawn until a centre is picked. The drag arrow and dial
            # stay hidden until then, which means disabling their inputs.
            _state["inputs"] = inputs
            _set_manipulators_enabled(inputs, False)

            for event, handler in (
                (cmd.executePreview, ExecutePreviewHandler()),
                (cmd.execute, ExecuteHandler()),
                (cmd.inputChanged, InputChangedHandler()),
                (cmd.validateInputs, ValidateInputsHandler()),
                (cmd.destroy, DestroyHandler()),
            ):
                event.add(handler)
                _handlers.append(handler)
        except Exception:
            _ui.messageBox("Printable Circle failed to start:\n" + traceback.format_exc())


class ManipulatorEventHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        try:
            inputs = _state.get("inputs")
            frame = _state.get("frame")
            if inputs is None or frame is None or inputs.itemById("center").selectionCount == 0:
                return
            if frame != _state.get("applied_frame"):
                _apply_frame(inputs, frame)
        except Exception:
            _app.log("Printable Circle manipulator update failed:\n" + traceback.format_exc())


class ExecutePreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        event_args = adsk.core.CommandEventArgs.cast(args)
        try:
            # The preview is exactly the final result, so let OK keep it.
            event_args.isValidResult = _build(event_args.command.commandInputs, preview=True)
        except Exception:
            event_args.isValidResult = False
            _app.log("Printable Circle preview failed:\n" + traceback.format_exc())


class ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        event_args = adsk.core.CommandEventArgs.cast(args)
        try:
            if not _build(event_args.command.commandInputs):
                event_args.executeFailed = True
                event_args.executeFailedMessage = "Select a plane to sketch on."
        except Exception:
            event_args.executeFailed = True
            event_args.executeFailedMessage = traceback.format_exc()


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        event_args = adsk.core.InputChangedEventArgs.cast(args)
        inputs = event_args.inputs
        try:
            changed = event_args.input.id
            if changed == "shape":
                _show_shape_inputs(inputs)
                _update_info(inputs)
            elif changed in ("diameter", "ratio", "overhang"):
                _update_info(inputs)
            elif changed == "center":
                if inputs.itemById("center").selectionCount == 0:
                    _set_manipulators_enabled(inputs, False)
                    _state.pop("applied_frame", None)
                    _state.pop("frame", None)
            elif changed == "plane":
                plane = inputs.itemById("plane")
                if plane.selectionCount:
                    inputs.itemById("center").hasFocus = True
        except Exception:
            pass


class ValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        event_args = adsk.core.ValidateInputsEventArgs.cast(args)
        inputs = event_args.inputs
        values = _read_inputs(inputs)
        plane = inputs.itemById("plane")
        event_args.areInputsValid = (
            values["diameter"] > 0
            and (
                _overhang_ok(inputs, values)
                if values["shape"] == "teardrop"
                else sg.RATIO_MIN - 1e-9 <= values["ratio"] <= sg.RATIO_MAX + 1e-9
            )
            and (plane is None or plane.selectionCount == 1)
        )


class DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        event_args = adsk.core.CommandEventArgs.cast(args)
        if (
            event_args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason
            and "values" in _state
        ):
            values = dict(_state["values"])
            values["angle"] = sg.wrap_turn(values["angle"])
            _save_settings(values)
        _state.clear()
        # Drop the per-command handlers; keep the CommandCreated one (index 0).
        del _handlers[1:]


# ---------------------------------------------------------------- add-in lifecycle
def _remove_ui():
    for panel_id, dropdown_id, _ in PLACEMENTS:
        panel = _ui.allToolbarPanels.itemById(panel_id)
        if panel is None:
            continue
        controls = panel.controls
        if dropdown_id:
            dropdown = controls.itemById(dropdown_id)
            controls = dropdown.controls if dropdown else None
        if controls:
            control = controls.itemById(CMD_ID)
            if control:
                control.deleteMe()
    cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        cmd_def.deleteMe()


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _remove_ui()

        global _manip_event, _manip_handler
        _app.unregisterCustomEvent(MANIP_EVENT_ID)
        _manip_event = _app.registerCustomEvent(MANIP_EVENT_ID)
        _manip_handler = ManipulatorEventHandler()
        _manip_event.add(_manip_handler)

        cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_TOOLTIP, RESOURCES)
        handler = CommandCreatedHandler()
        cmd_def.commandCreated.add(handler)
        _handlers.append(handler)

        for panel_id, dropdown_id, after_id in PLACEMENTS:
            panel = _ui.allToolbarPanels.itemById(panel_id)
            if panel is None:
                continue
            controls = panel.controls
            if dropdown_id:
                dropdown = controls.itemById(dropdown_id)
                if dropdown is None:
                    continue
                controls = dropdown.controls
            controls.addCommand(cmd_def, after_id, False)
    except Exception:
        if _ui:
            _ui.messageBox("Printable Circle add-in failed to load:\n" + traceback.format_exc())


def stop(context):
    try:
        _remove_ui()
        _handlers.clear()
        _app.unregisterCustomEvent(MANIP_EVENT_ID)
    except Exception:
        if _ui:
            _ui.messageBox("Printable Circle add-in failed to unload:\n" + traceback.format_exc())
