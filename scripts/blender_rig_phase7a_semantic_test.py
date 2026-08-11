#!/usr/bin/env python3
"""Blender integration test for N-D Projected Transform + Recorded Pose Map."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


def main():
    import coa_tools2

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.data.edit_bones.new("face")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="POSE")
    from coa_tools2.rig_control.blender.selection import select_pose_bone

    select_pose_bone(armature, "face", exclusive=True)

    result = bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="Face Direction", initial_dimensions=3
    )
    assert result == {"FINISHED"}, result
    component = armature.coa_tools2_rig.rig_components[0]
    assert component.component_type == "SEMANTIC"
    assert [stage.stage_type for stage in component.semantic_stages] == [
        "PROJECTED_TRANSFORM", "POSE_MAP"
    ]
    projected, pose_map = component.semantic_stages
    assert projected.control_bone and projected.art_frame_bone
    assert projected.display_frame_bone != projected.art_frame_bone
    assert len(pose_map.inputs) == 3
    assert len(pose_map.inputs[2].terms) == 2
    control = armature.pose.bones[projected.control_bone]
    assert control.custom_shape_transform.name == projected.display_frame_bone
    depth = control.constraints.get(f"COA_COMP_{component.component_uuid[:8]}_Depth")
    assert depth is not None and depth.min_z == 0.0 and depth.max_z == 0.0

    mesh = bpy.data.meshes.new("FaceMesh")
    mesh.from_pydata(((-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)), (), ((0, 1, 2, 3),))
    sprite = bpy.data.objects.new("FaceSprite", mesh)
    bpy.context.scene.collection.objects.link(sprite)
    sprite.shape_key_add(name="Basis")
    key = sprite.shape_key_add(name="Turn")
    key.value = 0.2

    armature.coa_tools2_rig.rig_components_index = 0
    component.semantic_stages_index = 1
    result = bpy.ops.coa_tools2.add_semantic_output(
        "EXEC_DEFAULT",
        label="Face Turn",
        target_kind="SHAPE_KEY",
        target_object_name=sprite.name,
        target_name=key.name,
    )
    assert result == {"FINISHED"}, result
    assert key.id_data.animation_data is None or not key.id_data.animation_data.drivers

    control.location = (0.0, 0.0, 0.0)
    result = bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    key.value = 0.2
    result = bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result

    control.location.x = 1.0
    bpy.context.view_layer.update()
    result = bpy.ops.coa_tools2.begin_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    key.value = 0.8
    result = bpy.ops.coa_tools2.commit_semantic_sample("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert len(pose_map.samples) == 2

    control.location.x = 0.5
    bpy.context.view_layer.update()
    assert abs(key.value - 0.5) < 1.0e-4, key.value
    source = armature.pose.bones["face"]
    assert source.matrix_basis.is_identity

    before_bones = set(armature.data.bones)
    result = bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert set(armature.data.bones) == before_bones
    print("PHASE7A_SEMANTIC_OK", len(component.artifacts), key.value)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
