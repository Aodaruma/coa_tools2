#!/usr/bin/env python3
"""Background Blender integration test for Phase 3 control presets."""

from __future__ import annotations

import math
import sys

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def create_shape_target(armature):
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    target = bpy.context.active_object
    target.name = "Phase3Face"
    target.parent = armature
    target.shape_key_add(name="Basis")
    keys = {}
    for name in ("RectX", "RectY", "CircleX", "Dial"):
        keys[name] = target.shape_key_add(name=name)
    return target, keys


def assert_widget(control, armature):
    tip = armature.pose.bones[control.control_bone].custom_shape
    base = armature.pose.bones[control.display_bone].custom_shape
    assert tip is not None and base is not None
    assert len(tip.data.vertices) > 0
    assert len(base.data.vertices) > 0


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    target, keys = create_shape_target(armature)

    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Face XY",
        control_type="POINT_2D_RECT",
        width=4.0,
        height=3.0,
        source_component="X",
        create_initial_binding=True,
        target_object_name=target.name,
        shape_key="RectX",
    )
    assert result == {"FINISHED"}
    rectangle = armature.coa_tools2_rig.rig_controls[-1]
    assert_widget(rectangle, armature)
    result = bpy.ops.coa_tools2.add_rig_binding(
        "EXEC_DEFAULT",
        source_component="Y",
        target_kind="SHAPE_KEY_VALUE",
        target_object_name=target.name,
        target_name="RectY",
    )
    assert result == {"FINISHED"}
    rect_pose = armature.pose.bones[rectangle.control_bone]
    rect_limit = rect_pose.constraints.get(
        f"COA_{rectangle.control_uuid[:8]}_LimitLocation"
    )
    assert rect_limit is not None
    assert rect_limit.max_x == 4.0 and rect_limit.max_y == 3.0
    rect_pose.location.x = 4.0
    rect_pose.location.y = 3.0
    update_scene()
    assert abs(keys["RectX"].value - 1.0) < 1e-5
    assert abs(keys["RectY"].value - 1.0) < 1e-5

    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Eye Circle",
        control_type="POINT_2D_CIRCLE",
        radius=2.0,
        source_component="X",
        create_initial_binding=True,
        target_object_name=target.name,
        shape_key="CircleX",
    )
    assert result == {"FINISHED"}
    circle = armature.coa_tools2_rig.rig_controls[-1]
    assert_widget(circle, armature)
    circle_pose = armature.pose.bones[circle.control_bone]
    distance = circle_pose.constraints.get(
        f"COA_{circle.control_uuid[:8]}_LimitDistance"
    )
    assert distance is not None and abs(distance.distance - 2.0) < 1e-6
    circle_pose.location.x = -2.0
    update_scene()
    assert abs(keys["CircleX"].value - 0.0) < 1e-5
    circle_pose.location.x = 2.0
    update_scene()
    assert abs(keys["CircleX"].value - 1.0) < 1e-5

    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Head Dial",
        control_type="DIAL",
        radius=2.5,
        angle_min=-math.pi * 0.5,
        angle_max=math.pi * 0.5,
        create_initial_binding=True,
        target_object_name=target.name,
        shape_key="Dial",
    )
    assert result == {"FINISHED"}
    dial = armature.coa_tools2_rig.rig_controls[-1]
    assert_widget(dial, armature)
    dial_pose = armature.pose.bones[dial.control_bone]
    rotation_limit = dial_pose.constraints.get(
        f"COA_{dial.control_uuid[:8]}_LimitRotation"
    )
    assert rotation_limit is not None
    dial_pose.rotation_mode = "XYZ"
    dial_pose.rotation_euler.z = -math.pi * 0.5
    update_scene()
    assert abs(keys["Dial"].value - 0.0) < 1e-5, keys["Dial"].value
    dial_pose.rotation_euler.z = math.pi * 0.5
    update_scene()
    assert abs(keys["Dial"].value - 1.0) < 1e-5, keys["Dial"].value

    bpy.ops.coa_tools2.validate_rig()
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0

    from coa_tools2.rig_control.blender.compiler import compile_control

    counts_before = (
        len(armature.data.bones),
        len(bpy.data.objects),
        len(target.data.shape_keys.animation_data.drivers),
    )
    for control in armature.coa_tools2_rig.rig_controls:
        compile_control(armature, control)
    counts_after = (
        len(armature.data.bones),
        len(bpy.data.objects),
        len(target.data.shape_keys.animation_data.drivers),
    )
    assert counts_after == counts_before, (counts_before, counts_after)

    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig Phase 3 test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Rig Phase 3 test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
