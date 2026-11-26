"""Squircle: a sketch tool that draws a circle with a flat top, so the profile
can be 3D printed upright on an FDM printer without supports."""

import json
import math
import os
import traceback

import adsk.core
import adsk.fusion

from . import squircle_geometry as sg
from . import squircle_sketch as ss

CMD_ID = "SquircleSketchCommand"
CMD_NAME = "Squircle"
CMD_TOOLTIP = (
    "Circle with a flat top and tangent side walls, so it prints upright "
    "without supports."
)
HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(HERE, "resources")
SETTINGS_FILE = os.path.join(HERE, "settings.json")

# Where the button goes: (panel id, dropdown id or None, control to sit after)
PLACEMENTS = [
    ("SketchCreatePanel", "CircleDropDown", "CircleThreeTangent"),
    ("SolidCreatePanel", None, "SketchCreate"),
]

DEFAULTS = {"diameter": 1.0, "ratio": sg.DEFAULT_RATIO, "angle": 0.0}  # cm, -, rad

_app = None
_ui = None
_handlers = []
_manip_event = None
_manip_handler = None
MANIP_EVENT_ID = "SquircleManipulatorUpdate"
_state = {}


# ---------------------------------------------------------------- settings
def _load_settings():
    values = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as f:
            values.update({k: float(v) for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError, TypeError):
        pass
    values["ratio"] = min(max(values["ratio"], sg.RATIO_MIN), sg.RATIO_MAX)
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


def _read_inputs(inputs):
    return {
        "diameter": adsk.core.DistanceValueCommandInput.cast(inputs.itemById("diameter")).value,
        "ratio": adsk.core.FloatSpinnerCommandInput.cast(inputs.itemById("ratio")).value,
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


def _center_point(sketch, inputs):
    center_input = inputs.itemById("center")
    if center_input.selectionCount == 0:
        return sketch.originPoint
    entity = center_input.selection(0).entity
    point = adsk.fusion.SketchPoint.cast(entity)
    if point is not None and point.parentSketch == sketch:
        return point
    projected = sketch.project(entity)
    for i in range(projected.count):
        p = adsk.fusion.SketchPoint.cast(projected.item(i))
        if p is not None:
            return p
    raise RuntimeError("Could not use the selected centre point.")


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
    _state["applied_frame"] = frame


def _request_manipulator_update(sketch, center):
    """Fusion ignores setManipulator calls made inside executePreview, and a
    sketch made on a picked plane only exists during the preview. So the preview
    records the frame and a custom event applies it once the preview is done."""
    frame = _frame(sketch, center)
    if frame != _state.get("applied_frame"):
        _state["frame"] = frame
        _app.fireCustomEvent(MANIP_EVENT_ID)


def _update_info(inputs):
    info = adsk.core.TextBoxCommandInput.cast(inputs.itemById("info"))
    values = _read_inputs(inputs)
    units = _design().unitsManager
    bridge = units.formatInternalValue(2 * values["ratio"] * values["diameter"])
    overhang = sg.overhang_from_vertical_deg(values["ratio"])
    # formattedText renders HTML; plain .text shows tags literally.
    info.formattedText = f"Overhang: {overhang:.1f}°<br>Bridge: {bridge}"


def _build(inputs, preview=False):
    values = _read_inputs(inputs)
    sketch = _target_sketch(inputs)
    if sketch is None:
        return False
    center = _center_point(sketch, inputs)
    ss.build(sketch, center, values["diameter"], values["ratio"], values["angle"])
    if preview:
        _request_manipulator_update(sketch, center)
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
                "center", "Centre", "Select a centre point (defaults to the sketch origin)"
            )
            center.addSelectionFilter("SketchPoints")
            center.addSelectionFilter("ConstructionPoints")
            center.addSelectionFilter("Vertices")
            center.setSelectionLimits(0, 1)

            dia = inputs.addDistanceValueCommandInput(
                "diameter", "Diameter", adsk.core.ValueInput.createByReal(values["diameter"])
            )
            dia.minimumValue = 0
            dia.isMinimumValueInclusive = False

            inputs.addFloatSpinnerCommandInput(
                "ratio", "Diameter Ratio", "", sg.RATIO_MIN, sg.RATIO_MAX, 0.01, values["ratio"]
            ).tooltip = "Half the flat's width, as a fraction of the diameter. 0.25 gives a flat half as wide as the circle."

            ang = inputs.addAngleValueCommandInput(
                "angle", "Rotation", adsk.core.ValueInput.createByReal(values["angle"])
            )
            ang.tooltip = "Rotation of the flat away from sketch +Y, counterclockwise."

            info = inputs.addTextBoxCommandInput("info", "", "", 2, True)
            info.tooltip = "Overhang is the side-wall angle from vertical. Bridge is the length of the flat top."
            _update_info(inputs)

            # Without a sketch, the manipulators are placed once the preview runs.
            _state["inputs"] = inputs
            if _state["sketch"] is not None:
                _apply_frame(inputs, _frame(_state["sketch"], _state["sketch"].originPoint))

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
            _ui.messageBox("Squircle failed to start:\n" + traceback.format_exc())


class ManipulatorEventHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        try:
            inputs = _state.get("inputs")
            frame = _state.get("frame")
            if inputs is not None and frame is not None and frame != _state.get("applied_frame"):
                _apply_frame(inputs, frame)
        except Exception:
            _app.log("Squircle manipulator update failed:\n" + traceback.format_exc())


class ExecutePreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        event_args = adsk.core.CommandEventArgs.cast(args)
        try:
            # The preview is exactly the final result, so let OK keep it.
            event_args.isValidResult = _build(event_args.command.commandInputs, preview=True)
        except Exception:
            event_args.isValidResult = False
            _app.log("Squircle preview failed:\n" + traceback.format_exc())


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
            if changed in ("diameter", "ratio"):
                _update_info(inputs)
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
            and sg.RATIO_MIN - 1e-9 <= values["ratio"] <= sg.RATIO_MAX + 1e-9
            and (plane is None or plane.selectionCount == 1)
        )


class DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        event_args = adsk.core.CommandEventArgs.cast(args)
        if (
            event_args.terminationReason == adsk.core.CommandTerminationReason.CompletedTerminationReason
            and "values" in _state
        ):
            _save_settings(_state["values"])
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
            _ui.messageBox("Squircle add-in failed to load:\n" + traceback.format_exc())


def stop(context):
    try:
        _remove_ui()
        _handlers.clear()
        _app.unregisterCustomEvent(MANIP_EVENT_ID)
    except Exception:
        if _ui:
            _ui.messageBox("Squircle add-in failed to unload:\n" + traceback.format_exc())
