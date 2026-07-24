#!/usr/bin/env python3
"""Background Blender integration test for Phase 4 continuous StateData."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy


def update_scene():
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()


def activate_armature(armature):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")


def create_shape_target(armature, name, shape_names):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    target = bpy.context.active_object
    target.name = name
    target.parent = armature
    target.shape_key_add(name="Basis")
    keys = {shape_name: target.shape_key_add(name=shape_name) for shape_name in shape_names}
    activate_armature(armature)
    return target, keys


def assign_all_states(armature, control, target, prefix):
    for index, point in enumerate(control.state_points):
        control.state_points_index = index
        result = bpy.ops.coa_tools2.assign_rig_state_point(
            "EXEC_DEFAULT",
            target_object_name=target.name,
            shape_key=f"{prefix}_{point.column}_{point.row}",
        )
        assert result == {"FINISHED"}, (index, result)


def assert_values(keys, expected):
    update_scene()
    for name, value in expected.items():
        assert abs(keys[name].value - value) < 1e-5, (
            name,
            keys[name].value,
            value,
        )


def main():
    if addon_utils.enable("coa_tools2", default_set=False, persistent=False) is None:
        raise RuntimeError("Could not enable coa_tools2.")

    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object

    matrix_names = [
        f"Matrix_{column}_{row}"
        for row in range(2)
        for column in range(4)
    ]
    matrix_target, matrix_keys = create_shape_target(
        armature,
        "Phase4MatrixTarget",
        matrix_names,
    )
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Face State Matrix",
        control_type="POINT_2D_RECT",
        width=4.0,
        height=3.0,
        rectangle_mode="FREE",
        create_initial_binding=False,
    )
    assert result == {"FINISHED"}, result
    matrix = armature.coa_tools2_rig.rig_controls[-1]
    result = bpy.ops.coa_tools2.setup_rig_states(
        "EXEC_DEFAULT",
        mode="MATRIX_2D",
        columns=3,
        rows=2,
    )
    assert result == {"FINISHED"}, result
    assert matrix.state_mode == "MATRIX_2D"
    assert matrix.rectangle_mode == "FREE"
    assert (matrix.grid_columns, matrix.grid_rows) == (3, 2)
    assert len(matrix.state_points) == 6
    assign_all_states(armature, matrix, matrix_target, "Matrix")

    matrix_handle = armature.pose.bones[matrix.control_bone]
    matrix_handle.location.x = 1.0
    matrix_handle.location.y = 1.5
    assert_values(
        matrix_keys,
        {
            "Matrix_0_0": 0.25,
            "Matrix_1_0": 0.25,
            "Matrix_2_0": 0.0,
            "Matrix_0_1": 0.25,
            "Matrix_1_1": 0.25,
            "Matrix_2_1": 0.0,
        },
    )
    matrix.state_points_index = 5
    result = bpy.ops.coa_tools2.snap_rig_state_point()
    assert result == {"FINISHED"}
    assert abs(matrix_handle.location.x - 4.0) < 1e-6
    assert abs(matrix_handle.location.y - 3.0) < 1e-6

    result = bpy.ops.coa_tools2.setup_rig_states(
        "EXEC_DEFAULT",
        mode="MATRIX_2D",
        columns=4,
        rows=2,
    )
    assert result == {"FINISHED"}, result
    assert len(matrix.state_points) == 8
    for point in matrix.state_points:
        if point.column < 3:
            assert point.target_object == matrix_target
            assert point.target_name == f"Matrix_{point.column}_{point.row}"
        else:
            assert point.target_object is None

    try:
        bpy.ops.coa_tools2.setup_rig_states(
            "EXEC_DEFAULT",
            mode="MATRIX_2D",
            columns=2,
            rows=2,
            confirm_remove_assigned=False,
        )
    except RuntimeError as exc:
        assert "would remove 2 assigned state" in str(exc)
    else:
        raise AssertionError("Destructive state resize was not rejected.")
    assert len(matrix.state_points) == 8
    result = bpy.ops.coa_tools2.setup_rig_states(
        "EXEC_DEFAULT",
        mode="MATRIX_2D",
        columns=2,
        rows=2,
        confirm_remove_assigned=True,
    )
    assert result == {"FINISHED"}, result
    assert len(matrix.state_points) == 4
    matrix_drivers = matrix_target.data.shape_keys.animation_data.drivers
    assert len(matrix_drivers) == 4, len(matrix_drivers)

    linear_names = [f"Linear_{column}_0" for column in range(3)]
    linear_target, linear_keys = create_shape_target(
        armature,
        "Phase4LinearTarget",
        linear_names,
    )
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Mouth States",
        control_type="SLIDER_1D",
        axis="X",
        width=4.0,
        create_initial_binding=False,
    )
    assert result == {"FINISHED"}, result
    linear = armature.coa_tools2_rig.rig_controls[-1]
    result = bpy.ops.coa_tools2.setup_rig_states(
        "EXEC_DEFAULT",
        mode="LINEAR_1D",
        columns=3,
        rows=1,
    )
    assert result == {"FINISHED"}, result
    assert len(linear.state_points) == 3
    assign_all_states(armature, linear, linear_target, "Linear")
    linear_handle = armature.pose.bones[linear.control_bone]
    linear_handle.location.x = 1.0
    assert_values(
        linear_keys,
        {
            "Linear_0_0": 0.5,
            "Linear_1_0": 0.5,
            "Linear_2_0": 0.0,
        },
    )

    bpy.ops.coa_tools2.validate_rig()
    issues = [
        (issue.severity, issue.code, issue.message)
        for issue in armature.coa_tools2_rig.rig_validation_issues
    ]
    assert not issues, issues

    driver_counts_before = (
        len(matrix_target.data.shape_keys.animation_data.drivers),
        len(linear_target.data.shape_keys.animation_data.drivers),
    )
    bpy.ops.coa_tools2.repair_rig()
    driver_counts_after = (
        len(matrix_target.data.shape_keys.animation_data.drivers),
        len(linear_target.data.shape_keys.animation_data.drivers),
    )
    assert driver_counts_after == driver_counts_before

    validation_directory = tempfile.TemporaryDirectory(
        prefix="coa-rig-phase4-reload-"
    )
    blend_path = Path(validation_directory.name) / "phase4-state.blend"
    armature_name = armature.name
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    armature = bpy.data.objects[armature_name]
    controls = {
        control.label: control
        for control in armature.coa_tools2_rig.rig_controls
    }
    matrix = controls["Face State Matrix"]
    linear = controls["Mouth States"]
    assert len(matrix.state_points) == 4
    assert len(linear.state_points) == 3
    assert all(
        point.target_object is not None and point.target_name
        for point in (*matrix.state_points, *linear.state_points)
    )
    matrix_target = bpy.data.objects["Phase4MatrixTarget"]
    linear_target = bpy.data.objects["Phase4LinearTarget"]
    matrix_handle = armature.pose.bones[matrix.control_bone]
    matrix_handle.location.x = 2.0
    matrix_handle.location.y = 1.5
    assert_values(
        {
            key.name: key
            for key in matrix_target.data.shape_keys.key_blocks
            if key.name != "Basis"
        },
        {
            "Matrix_0_0": 0.25,
            "Matrix_1_0": 0.25,
            "Matrix_0_1": 0.25,
            "Matrix_1_1": 0.25,
        },
    )
    linear_handle = armature.pose.bones[linear.control_bone]
    linear_handle.location.x = 3.0
    assert_values(
        {
            key.name: key
            for key in linear_target.data.shape_keys.key_blocks
            if key.name != "Basis"
        },
        {
            "Linear_0_0": 0.0,
            "Linear_1_0": 0.5,
            "Linear_2_0": 0.5,
        },
    )
    bpy.ops.coa_tools2.validate_rig()
    assert not armature.coa_tools2_rig.rig_validation_issues

    addon_utils.disable("coa_tools2", default_set=False)
    validation_directory.cleanup()
    print("COA rig Phase 4 StateData test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Rig Phase 4 StateData test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
