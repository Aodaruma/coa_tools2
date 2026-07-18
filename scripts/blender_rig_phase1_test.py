#!/usr/bin/env python3
"""Background Blender integration test for the Phase 1 slider vertical slice."""

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
    )
    assert result == {"FINISHED"}
    assert len(armature.coa_tools2.rig_controls) == 1
    control = armature.coa_tools2.rig_controls[0]
    assert control.control_bone in armature.pose.bones
    assert control.display_bone in armature.pose.bones
    assert not armature.data.bones[control.control_bone].use_deform
    assert not armature.data.bones[control.display_bone].use_deform
    assert armature.pose.bones[control.control_bone].custom_shape is not None
    assert armature.pose.bones[control.display_bone].custom_shape is not None

    from coa_tools2.rig_control.blender.compiler import compile_control

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
