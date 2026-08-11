#!/usr/bin/env python3
"""Blender integration test for real 3D mechanism IK with flat presentation."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy
from mathutils import Vector


def _bone(edit_bones, name, head, tail, parent=None):
    bone = edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = parent is not None
    return bone


def main():
    import coa_tools2
    from coa_tools2.rig_control.blender.selection import select_pose_bones

    coa_tools2.register()
    bpy.ops.coa_tools2.create_sprite_object()
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    upper = _bone(bones, "upper", (0, 0, 0), (1, 0, 0))
    lower = _bone(bones, "lower", upper.tail, (2, 0.15, 0), upper)
    hand = _bone(bones, "hand", lower.tail, (2.6, 0.15, 0), lower)
    bpy.ops.object.mode_set(mode="POSE")
    select_pose_bones(armature, {"upper", "lower", "hand"}, "hand")
    assert bpy.ops.coa_tools2.add_semantic_rig(
        "EXEC_DEFAULT", label="Arm Reach", initial_dimensions=3
    ) == {"FINISHED"}
    component = armature.coa_tools2_rig.rig_components[0]
    assert bpy.ops.coa_tools2.add_semantic_stage(
        "EXEC_DEFAULT", stage_type="CHAIN_IK", label="Arm IK"
    ) == {"FINISHED"}
    ik_stage = component.semantic_stages[-1]
    ik_stage.chain_length = 2
    ik_stage.use_pole = True
    ik_stage.allow_stretch = False
    component.semantic_stages_index = len(component.semantic_stages) - 1
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}

    control = armature.pose.bones[ik_stage.control_bone]
    control.location.z = 0.50  # Art-frame local Z is actual 3D depth.
    control.location.y -= 0.40  # Pull inward so the no-stretch chain can reach.
    bpy.context.view_layer.update()

    mechanism = tuple(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.role.startswith(f"semantic:{ik_stage.stage_uuid}:mechanism_bone:")
    )
    projected = tuple(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.role.startswith(f"semantic:{ik_stage.stage_uuid}:projected_joint:")
    )
    presentation = tuple(
        artifact.bone_name
        for artifact in component.artifacts
        if artifact.role.startswith(f"semantic:{ik_stage.stage_uuid}:presentation_bone:")
    )
    assert len(mechanism) == len(presentation) == 3
    assert len(projected) == 4
    mechanism = tuple(sorted(mechanism))
    projected = tuple(sorted(projected))
    presentation = tuple(sorted(presentation))

    target_error = (
        armature.pose.bones[mechanism[2]].head - control.head
    ).length
    assert target_error < 1.0e-4, target_error
    assert abs(armature.pose.bones[mechanism[2]].head.y) > 0.1

    art = armature.pose.bones[ik_stage.art_frame_bone]
    art_inverse = art.matrix.inverted()
    for name in projected:
        local = art_inverse @ armature.pose.bones[name].head
        assert abs(local.z) < 1.0e-5, (name, local.z)
    art_normal = art.matrix.to_3x3().col[2].normalized()
    for name in presentation:
        normal = armature.pose.bones[name].matrix.to_3x3().col[2].normalized()
        assert normal.dot(art_normal) > 0.99999
    for name in ("upper", "lower", "hand"):
        normal = armature.pose.bones[name].matrix.to_3x3().col[2].normalized()
        assert normal.dot(art_normal) > 0.99999

    counts = (len(armature.data.bones), len(component.artifacts))
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert counts == (len(armature.data.bones), len(component.artifacts))
    print("PHASE7B_PROJECTED_IK_OK", target_error, len(component.artifacts))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
