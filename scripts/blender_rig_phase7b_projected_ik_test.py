#!/usr/bin/env python3
"""Blender integration test for real 3D mechanism IK with flat presentation."""

from __future__ import annotations

import math
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
    object_parent = bpy.data.objects.new("ProjectedIK_ObjectParent", None)
    bpy.context.scene.collection.objects.link(object_parent)
    object_parent.location = (2.0, -1.5, 0.75)
    object_parent.rotation_euler = (
        math.radians(17.0),
        math.radians(-11.0),
        math.radians(23.0),
    )
    object_parent.scale = (1.25, 1.25, 1.25)
    armature.parent = object_parent
    armature.location = (-0.4, 0.3, 0.2)
    armature.rotation_euler = (
        math.radians(-9.0),
        math.radians(13.0),
        math.radians(-7.0),
    )
    armature.scale = (0.9, 0.9, 0.9)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    rig_parent = _bone(bones, "rig_parent", (0, 0, -0.8), (0, 0, 0))
    upper = _bone(bones, "upper", rig_parent.tail, (-1, 0, 0), rig_parent)
    lower = _bone(bones, "lower", upper.tail, (-2, 0.15, 0), upper)
    hand = _bone(bones, "hand", lower.tail, (-2.6, 0.15, 0), lower)
    upper.roll = math.radians(61.0)
    lower.roll = math.radians(-37.0)
    hand.roll = math.radians(19.0)
    bpy.ops.object.mode_set(mode="POSE")
    parent_pose = armature.pose.bones[rig_parent.name]
    parent_pose.rotation_mode = "XYZ"
    parent_pose.rotation_euler = (
        math.radians(12.0),
        math.radians(-18.0),
        math.radians(27.0),
    )
    parent_pose.location = (0.25, -0.1, 0.2)
    bpy.context.view_layer.update()
    rest_joint = armature.pose.bones["lower"].head.copy()
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
    select_pose_bones(armature, {"upper", "lower", "hand"}, "hand")
    assert bpy.ops.coa_tools2.assign_semantic_stage_chain("EXEC_DEFAULT") == {
        "FINISHED"
    }
    assert [ref.bone_name for ref in ik_stage.source_bones] == [
        "upper", "lower", "hand"
    ]
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}

    control = armature.pose.bones[ik_stage.control_bone]
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

    stage_role = f"semantic:{ik_stage.stage_uuid}:"
    bend_center_artifact = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == stage_role + "pole_bend_center"
    )
    pole_distance_artifact = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == stage_role + "pole_distance_constraint"
    )
    pole = armature.pose.bones[ik_stage.pole_bone]
    bend_center = armature.pose.bones[bend_center_artifact.bone_name]
    pole_distance = pole.constraints[pole_distance_artifact.constraint_name]
    assert pole_distance.type == "LIMIT_DISTANCE"
    assert pole_distance.target == armature
    assert pole_distance.subtarget == bend_center.name
    assert pole_distance.limit_mode == "LIMITDIST_ONSURFACE"
    assert pole_distance.use_transform_limit
    pole_world = armature.matrix_world @ pole.head
    center_world = armature.matrix_world @ bend_center.head
    initial_pole_radius = (pole_world - center_world).length
    assert abs(initial_pole_radius - pole_distance.distance) < 1.0e-5, (
        initial_pole_radius,
        pole_distance.distance,
        pole_world,
        center_world,
    )

    # Affect Transform keeps the interactive pole on its spherical rail even
    # under mirrored rest bones, arbitrary rolls, a posed parent bone and a
    # transformed object hierarchy.
    pole_basis = pole.matrix_basis.copy()
    direction_before = (pole_world - center_world).normalized()
    pole.location += Vector((0.45, -0.35, 0.7))
    bpy.context.view_layer.update()
    pole_world = armature.matrix_world @ pole.head
    center_world = armature.matrix_world @ bend_center.head
    direction_after = (pole_world - center_world).normalized()
    assert abs((pole_world - center_world).length - pole_distance.distance) < 1.0e-4
    assert direction_before.dot(direction_after) < 0.999
    pole.matrix_basis = pole_basis
    bpy.context.view_layer.update()

    # The fitted pole angle must retain the pre-solver rest knee despite roll,
    # mirror and parent transforms.
    rest_joint_error = (
        armature.pose.bones[mechanism[1]].head - rest_joint
    ).length
    assert rest_joint_error < 1.0e-4, rest_joint_error

    control.location.z = 0.50  # Art-frame local Z is actual 3D depth.
    control.location.y -= 0.40  # Pull inward so the no-stretch chain can reach.
    bpy.context.view_layer.update()

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

    ik_artifact = next(
        artifact
        for artifact in component.artifacts
        if artifact.role == stage_role + "ik_constraint"
    )
    ik_constraint = armature.pose.bones[ik_artifact.bone_name].constraints[
        ik_artifact.constraint_name
    ]
    assert math.isfinite(ik_constraint.pole_angle)
    pole_angle = ik_constraint.pole_angle
    counts = (len(armature.data.bones), len(component.artifacts))
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert counts == (len(armature.data.bones), len(component.artifacts))
    assert abs(ik_constraint.pole_angle - pole_angle) < 1.0e-5
    old_pole = ik_stage.pole_bone
    old_bend_center = bend_center.name
    ik_stage.use_pole = False
    assert bpy.ops.coa_tools2.update_rig_component("EXEC_DEFAULT") == {"FINISHED"}
    assert old_pole not in armature.data.bones
    assert old_bend_center not in armature.data.bones
    assert not any(
        artifact.role
        in {
            stage_role + "pole_control",
            stage_role + "pole_bend_center",
            stage_role + "pole_distance_constraint",
        }
        for artifact in component.artifacts
    )
    print(
        "PHASE7B_PROJECTED_IK_OK",
        target_error,
        rest_joint_error,
        len(component.artifacts),
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
