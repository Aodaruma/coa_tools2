"""Compile persisted rig-control definitions to Blender artifacts."""

from __future__ import annotations

import math

from mathutils import Vector

from .artifacts import (
    ensure_control_bones,
    ensure_control_constraints,
    ensure_control_name_text,
    ensure_control_widgets,
    ensure_rig_instance_id,
)
from .drivers import ensure_binding_driver
from .states import ensure_state_drivers, sync_state_control_geometry


class RigCompileError(RuntimeError):
    pass


def compile_control(armature, control, origin=None):
    if armature is None or armature.type != "ARMATURE":
        raise RigCompileError("Rig controls require an Armature SpriteObject.")
    supported_types = {
        "SLIDER_1D",
        "POINT_2D_RECT",
        "POINT_2D_CIRCLE",
        "DIAL",
    }
    if control.control_type not in supported_types:
        raise RigCompileError(f"Unsupported rig control: {control.control_type}.")
    if control.control_type == "DIAL" and control.angle_min >= control.angle_max:
        raise RigCompileError("Dial minimum angle must be less than its maximum.")
    if (
        control.control_type == "DIAL"
        and control.angle_max - control.angle_min > math.tau
    ):
        raise RigCompileError("Dial angle range cannot exceed one full turn.")
    if control.state_mode != "NONE":
        sync_state_control_geometry(control)
    ensure_rig_instance_id(armature)
    origin = Vector(control.origin if origin is None else origin)
    control.origin = origin
    display_pose, control_pose, name_pose = ensure_control_bones(
        armature,
        control,
        origin,
    )
    ensure_control_name_text(armature, name_pose, control)
    ensure_control_constraints(armature, display_pose, control_pose, control)
    ensure_control_widgets(display_pose, control_pose, control)
    for binding in control.bindings:
        ensure_binding_driver(armature, control, binding)
    state_driver_count = ensure_state_drivers(armature, control)
    control.needs_rebuild = False
    return {
        "display_bone": display_pose.name,
        "control_bone": control_pose.name,
        "name_bone": name_pose.name,
        "bindings": len(control.bindings),
        "state_drivers": state_driver_count,
    }
