#!/usr/bin/env python3
"""Background Blender integration test for the Phase 1 slider vertical slice."""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

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
    assert armature.type == "ARMATURE"

    bpy.ops.mesh.primitive_plane_add(size=2.0)
    mesh_object = bpy.context.active_object
    mesh_object.name = "Phase1Face"
    mesh_object.parent = armature
    mesh_object.shape_key_add(name="Basis")
    shape_key = mesh_object.shape_key_add(name="Smile")

    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Smile",
        axis="X",
        width=4.0,
        create_initial_binding=True,
    )
    assert result == {"FINISHED"}
    assert len(armature.coa_tools2_rig.rig_controls) == 1
    control = armature.coa_tools2_rig.rig_controls[0]
    assert abs(control.tip_radius - control.node_radius * 2.0) < 1e-6
    assert abs(control.name_offset - 0.75) < 1e-6
    assert control.live_preview
    assert control.control_bone in armature.pose.bones
    assert control.display_bone in armature.pose.bones
    assert control.name_bone in armature.pose.bones
    assert control.name_text_object in bpy.data.objects
    name_text = bpy.data.objects[control.name_text_object]
    assert name_text.type == "FONT"
    assert name_text.data.body == "Smile"
    assert name_text.parent == armature
    assert name_text.parent_type == "BONE"
    assert name_text.parent_bone == control.name_bone
    assert name_text.hide_render
    update_scene()
    expected_name_z = (
        control.origin[2]
        - max(control.tip_radius, control.node_radius)
        - control.name_offset
    )
    assert abs(name_text.matrix_world.translation.x - control.origin[0]) < 1e-6
    assert abs(name_text.matrix_world.translation.z - expected_name_z) < 1e-5
    for bone_name in (
        control.control_bone,
        control.display_bone,
        control.name_bone,
    ):
        bone_color = getattr(armature.data.bones[bone_name], "color", None)
        if bone_color is not None:
            assert bone_color.palette == "DEFAULT"
    assert not armature.data.bones[control.control_bone].use_deform
    assert not armature.data.bones[control.display_bone].use_deform
    assert not armature.data.bones[control.name_bone].use_deform
    assert armature.pose.bones[control.control_bone].custom_shape is not None
    assert armature.pose.bones[control.display_bone].custom_shape is not None
    assert not armature.data.bones[control.display_bone].hide_select

    from coa_tools2.rig_control.blender.compiler import compile_control
    from coa_tools2.rig_control.blender.properties import (
        flush_auto_rebuilds_now,
    )

    counts_before = (
        len(armature.data.bones),
        len(bpy.data.objects),
        len(mesh_object.data.shape_keys.animation_data.drivers),
    )
    compile_control(armature, control)
    counts_after = (
        len(armature.data.bones),
        len(bpy.data.objects),
        len(mesh_object.data.shape_keys.animation_data.drivers),
    )
    assert counts_after == counts_before

    control.width = 5.0
    assert control.needs_rebuild
    flush_auto_rebuilds_now()
    assert not control.needs_rebuild
    assert not control.auto_rebuild_error
    auto_limit = armature.pose.bones[control.control_bone].constraints.get(
        f"COA_{control.control_uuid[:8]}_LimitLocation"
    )
    assert auto_limit is not None and auto_limit.max_x == 5.0
    control.width = 4.0
    flush_auto_rebuilds_now()
    assert auto_limit.max_x == 4.0

    control.live_preview = False
    control.width = 5.5
    assert control.needs_rebuild
    flush_auto_rebuilds_now()
    assert control.needs_rebuild
    assert auto_limit.max_x == 4.0
    assert bpy.ops.coa_tools2.update_rig_control() == {"FINISHED"}
    assert not control.needs_rebuild
    assert auto_limit.max_x == 5.5

    control.width = 4.0
    assert control.needs_rebuild
    control.live_preview = True
    flush_auto_rebuilds_now()
    assert not control.needs_rebuild
    assert auto_limit.max_x == 4.0

    for bone_name, palette in (
        (control.display_bone, "THEME03"),
        (control.control_bone, "THEME04"),
    ):
        for owner in (
            armature.data.bones[bone_name],
            armature.pose.bones[bone_name],
        ):
            bone_color = getattr(owner, "color", None)
            if bone_color is not None:
                bone_color.palette = palette
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}
    for bone_name in (control.control_bone, control.display_bone):
        for owner in (
            armature.data.bones[bone_name],
            armature.pose.bones[bone_name],
        ):
            bone_color = getattr(owner, "color", None)
            if bone_color is not None:
                assert bone_color.palette == "DEFAULT"

    control.label = "Smile Control"
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}
    assert bpy.data.objects[control.name_text_object].data.body == "Smile Control"
    control.show_name = False
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}
    assert bpy.data.objects[control.name_text_object].hide_get()
    control.show_name = True
    result = bpy.ops.coa_tools2.update_rig_control()
    assert result == {"FINISHED"}
    assert not bpy.data.objects[control.name_text_object].hide_get()

    pose_bone = armature.pose.bones[control.control_bone]
    pose_bone.location.x = 0.0
    update_scene()
    assert abs(shape_key.value - 0.0) < 1e-5, shape_key.value
    pose_bone.location.x = 2.0
    update_scene()
    assert abs(shape_key.value - 0.5) < 1e-5, shape_key.value
    pose_bone.location.x = 4.0
    update_scene()
    assert abs(shape_key.value - 1.0) < 1e-5, shape_key.value

    pose_bone.keyframe_insert("location", frame=1, group=pose_bone.name)
    assert armature.animation_data is not None
    assert armature.animation_data.action is not None
    action = armature.animation_data.action
    if bpy.app.version < (4, 4, 0):
        paths = {curve.data_path for curve in action.fcurves}
    else:
        paths = {
            curve.data_path
            for layer in action.layers
            for strip in layer.strips
            for slot in action.slots
            for curve in strip.channelbag(slot).fcurves
        }
    assert any(control.control_bone in path for path in paths)

    bpy.context.scene.cursor.location = (6.0, 0.0, 0.0)
    bpy.context.view_layer.objects.active = armature
    result = bpy.ops.coa_tools2.add_rig_control(
        "EXEC_DEFAULT",
        label="Vertical",
        axis="Y",
        width=4.0,
        create_initial_binding=False,
    )
    assert result == {"FINISHED"}
    vertical = armature.coa_tools2_rig.rig_controls[-1]
    vertical_display = armature.pose.bones[vertical.display_bone]
    assert (
        abs(vertical_display.custom_shape_rotation_euler.z - math.pi * 0.5)
        < 1e-6
    )
    vertical_pose = armature.pose.bones[vertical.control_bone]
    vertical_limit = vertical_pose.constraints.get(
        f"COA_{vertical.control_uuid[:8]}_LimitLocation"
    )
    assert vertical_limit is not None
    assert vertical_limit.use_max_y and vertical_limit.max_y == vertical.width
    vertical_pose.location.y = vertical.width
    update_scene()
    assert abs(vertical_pose.location.y - vertical.width) < 1e-6
    from coa_tools2.rig_control.blender.ui import (
        sync_control_index_from_active_bone,
    )

    armature.data.bones.active = armature.data.bones[control.display_bone]
    assert sync_control_index_from_active_bone(
        armature,
        armature.coa_tools2_rig,
    )
    assert armature.coa_tools2_rig.rig_controls_index == 0
    armature.data.bones.active = armature.data.bones[vertical.control_bone]
    assert sync_control_index_from_active_bone(
        armature,
        armature.coa_tools2_rig,
    )
    assert armature.coa_tools2_rig.rig_controls_index == 1
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)

    with tempfile.TemporaryDirectory() as tempdir:
        filepath = Path(tempdir) / "phase1.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(filepath))
        assert filepath.exists()

    addon_utils.disable("coa_tools2", default_set=False)
    print("COA rig Phase 1 test OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Rig Phase 1 test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
