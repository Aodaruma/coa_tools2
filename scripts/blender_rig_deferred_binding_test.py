#!/usr/bin/env python3
"""Test creating a control outline before assigning its axis bindings."""

from __future__ import annotations

import sys

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object

    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Deferred Face XY",
        control_type="POINT_2D_RECT",
        width=4.0,
        height=3.0,
    )
    assert result == {"FINISHED"}, result
    control = armature.coa_tools2_rig.rig_controls[0]
    assert len(control.bindings) == 0
    assert armature.pose.bones[control.control_bone].custom_shape is not None
    assert armature.pose.bones[control.display_bone].custom_shape is not None

    bpy.ops.coa_tools2.validate_rig()
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    target = bpy.context.active_object
    target.name = "DeferredBindingFace"
    target.parent = armature
    target.shape_key_add(name="Basis")
    horizontal = target.shape_key_add(name="Horizontal")
    vertical = target.shape_key_add(name="Vertical")

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")

    result = bpy.ops.coa_tools2.add_rig_binding(
        "EXEC_DEFAULT",
        source_component="X",
        target_kind="SHAPE_KEY_VALUE",
        target_object_name=target.name,
        target_name=horizontal.name,
    )
    assert result == {"FINISHED"}, result
    result = bpy.ops.coa_tools2.add_rig_binding(
        "EXEC_DEFAULT",
        source_component="Y",
        target_kind="SHAPE_KEY_VALUE",
        target_object_name=target.name,
        target_name=vertical.name,
    )
    assert result == {"FINISHED"}, result
    assert len(control.bindings) == 2
    assert {binding.source_component for binding in control.bindings} == {"X", "Y"}

    handle = armature.pose.bones[control.control_bone]
    handle.location.x = 4.0
    handle.location.y = 3.0
    update_scene()
    assert abs(horizontal.value - 1.0) < 1e-5, horizontal.value
    assert abs(vertical.value - 1.0) < 1e-5, vertical.value

    bpy.ops.coa_tools2.validate_rig()
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0

    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig deferred-binding test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Deferred-binding test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
