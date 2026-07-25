"""Pose-bone selection compatibility for Blender 4.x and 5.x."""

from __future__ import annotations

import bpy


def active_pose_bone(armature):
    """Return the active pose bone across the Blender selection API change."""

    if bpy.context.active_object == armature:
        pose_bone = bpy.context.active_pose_bone
        if pose_bone is not None and pose_bone.id_data == armature:
            return pose_bone
    legacy_bone = getattr(armature.data.bones, "active", None)
    if legacy_bone is not None:
        return armature.pose.bones.get(legacy_bone.name)
    return None


def active_data_bone(armature):
    pose_bone = active_pose_bone(armature)
    return pose_bone.bone if pose_bone is not None else None


def _set_pose_bone_selected(pose_bone, selected: bool):
    if hasattr(pose_bone, "select"):
        pose_bone.select = selected
    elif hasattr(pose_bone.bone, "select"):
        pose_bone.bone.select = selected


def select_pose_bones(armature, bone_names, active_name: str):
    """Select pose bones and set the active bone across Blender versions."""

    names = set(bone_names)
    target = armature.pose.bones.get(active_name)
    if target is None or active_name not in names:
        return None
    if hasattr(armature.data.bones, "active"):
        try:
            for pose_bone in armature.pose.bones:
                _set_pose_bone_selected(pose_bone, pose_bone.name in names)
            armature.data.bones.active = target.bone
            return target
        except (AttributeError, RuntimeError, TypeError):
            pass

    # Blender 5.x keeps the active element on EditBones. Selection survives
    # the mode switch and becomes the active PoseBone on return.
    if bpy.context.active_object != armature:
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
    original_mode = armature.mode
    if original_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    for edit_bone in armature.data.edit_bones:
        selected = edit_bone.name in names
        edit_bone.select = selected
        edit_bone.select_head = selected
        edit_bone.select_tail = selected
    armature.data.edit_bones.active = armature.data.edit_bones[active_name]
    bpy.ops.object.mode_set(mode="POSE" if original_mode == "POSE" else "OBJECT")
    return target


def select_pose_bone(armature, bone_name: str, *, exclusive: bool = True):
    """Select one pose bone and make it active."""

    if exclusive:
        names = {bone_name}
    else:
        names = {
            pose_bone.name
            for pose_bone in armature.pose.bones
            if (
                getattr(pose_bone, "select", False)
                or getattr(pose_bone.bone, "select", False)
            )
        }
        names.add(bone_name)
    return select_pose_bones(armature, names, bone_name)
