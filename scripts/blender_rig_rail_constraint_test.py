#!/usr/bin/env python3
"""Regression test for one-axis, free-area, grid-rail, and dial controls."""

from __future__ import annotations

import math
import sys

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def evaluated_local_xy(pose_bone):
    rest_head = pose_bone.bone.head_local
    translation = pose_bone.matrix.translation
    return translation.x - rest_head.x, translation.z - rest_head.z


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")

    from coa_tools2.rig_control.blender.artifacts import rail_constraint_name
    from coa_tools2.rig_control.schema import dial_point, dial_rest_angle

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object

    bpy.context.scene.cursor.location = (-6.0, 0.0, 3.0)
    assert bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Strict 1D",
        control_type="SLIDER_1D",
        axis="X",
        width=4.0,
    ) == {"FINISHED"}
    slider = armature.coa_tools2_rig.rig_controls[-1]
    slider_pose = armature.pose.bones[slider.control_bone]
    slider_pose.location.x = 2.0
    slider_pose.location.y = 1.5
    update_scene()
    slider_x, slider_y = evaluated_local_xy(slider_pose)
    assert abs(slider_x - 2.0) < 1e-5
    assert abs(slider_y) < 1e-5

    bpy.context.scene.cursor.location = (0.0, 0.0, 3.0)
    assert bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Free Rectangle",
        control_type="POINT_2D_RECT",
        rectangle_mode="FREE",
        width=4.0,
        height=4.0,
    ) == {"FINISHED"}
    free = armature.coa_tools2_rig.rig_controls[-1]
    free_pose = armature.pose.bones[free.control_bone]
    assert free_pose.constraints.get(rail_constraint_name(free.control_uuid)) is None
    free_pose.location.x = 1.0
    free_pose.location.y = 1.0
    update_scene()
    free_x, free_y = evaluated_local_xy(free_pose)
    assert abs(free_x - 1.0) < 1e-5
    assert abs(free_y - 1.0) < 1e-5

    bpy.context.scene.cursor.location = (6.0, 0.0, 3.0)
    assert bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Grid Rectangle",
        control_type="POINT_2D_RECT",
        rectangle_mode="GRID",
        grid_columns=3,
        grid_rows=3,
        width=4.0,
        height=4.0,
    ) == {"FINISHED"}
    grid = armature.coa_tools2_rig.rig_controls[-1]
    grid_pose = armature.pose.bones[grid.control_bone]
    grid_constraint = grid_pose.constraints.get(
        rail_constraint_name(grid.control_uuid)
    )
    assert grid_constraint is not None and grid_constraint.type == "SHRINKWRAP"
    grid_pose.location.x = 0.3
    grid_pose.location.y = 1.0
    update_scene()
    grid_x, grid_y = evaluated_local_xy(grid_pose)
    assert abs(grid_x) < 0.02, (grid_x, grid_y)
    assert abs(grid_y - 1.0) < 0.02, (grid_x, grid_y)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    target = bpy.context.active_object
    target.name = "RailConstraintTarget"
    target.parent = armature
    target.shape_key_add(name="Basis")
    dial_key = target.shape_key_add(name="Dial")
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")

    bpy.context.scene.cursor.location = (0.0, 0.0, -3.0)
    assert bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Rail Dial",
        control_type="DIAL",
        radius=2.0,
        angle_min=-math.pi * 0.5,
        angle_max=math.pi * 0.5,
        create_initial_binding=True,
        target_object_name=target.name,
        shape_key=dial_key.name,
    ) == {"FINISHED"}
    dial = armature.coa_tools2_rig.rig_controls[-1]
    dial_pose = armature.pose.bones[dial.control_bone]
    dial_constraint = dial_pose.constraints.get(
        rail_constraint_name(dial.control_uuid)
    )
    assert dial_constraint is not None and dial_constraint.type == "SHRINKWRAP"

    rest_angle = dial_rest_angle(dial.angle_min, dial.angle_max)
    rest_x, rest_y = dial_point(dial.radius, rest_angle)
    for angle, expected_value in (
        (dial.angle_min, 0.0),
        (0.0, 0.5),
        (dial.angle_max, 1.0),
    ):
        point_x, point_y = dial_point(dial.radius * 0.5, angle)
        dial_pose.location.x = point_x - rest_x
        dial_pose.location.y = point_y - rest_y
        update_scene()
        final_x, final_y = evaluated_local_xy(dial_pose)
        final_point = (rest_x + final_x, rest_y + final_y)
        assert abs(math.hypot(*final_point) - dial.radius) < 0.02, final_point
        assert abs(dial_key.value - expected_value) < 0.01, (
            angle,
            dial_key.value,
        )

    bpy.ops.coa_tools2.validate_rig()
    assert len(armature.coa_tools2_rig.rig_validation_issues) == 0
    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig rail-constraint test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig rail-constraint test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
