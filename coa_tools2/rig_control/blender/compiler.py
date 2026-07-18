"""Compile persisted rig-control definitions to Blender artifacts."""

from __future__ import annotations

from mathutils import Vector

from .artifacts import (
    ensure_control_bones,
    ensure_control_widgets,
    ensure_limit_location,
    ensure_rig_instance_id,
)
from .drivers import ensure_binding_driver


class RigCompileError(RuntimeError):
    pass


def compile_control(armature, control, origin=(0.0, 0.0, 0.0)):
    if armature is None or armature.type != "ARMATURE":
        raise RigCompileError("Rig controls require an Armature SpriteObject.")
    if control.control_type != "SLIDER_1D":
        raise RigCompileError(
            f"Phase 1 only supports SLIDER_1D, got {control.control_type}."
        )
    ensure_rig_instance_id(armature)
    display_pose, control_pose = ensure_control_bones(
        armature,
        control,
        Vector(origin),
    )
    ensure_limit_location(control_pose, control)
    ensure_control_widgets(display_pose, control_pose, control)
    for binding in control.bindings:
        ensure_binding_driver(armature, control, binding)
    control.needs_rebuild = False
    return {
        "display_bone": display_pose.name,
        "control_bone": control_pose.name,
        "bindings": len(control.bindings),
    }
